"""Windows WASAPI + WebRTC AEC virtual microphone. All audio stays in memory."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import pyaudiowpatch as pa
import soxr
from aec_audio_processing import AudioProcessor
from desktop import SingleInstance, TrayIcon, set_startup, startup_enabled
from ui import build_ui, update_activity
from display import enable_high_dpi, dpi_awareness, window_dpi
from json_store import read_json, write_json

RATE = 48000
FRAME = RATE // 100
DEFAULT_DELAY_MS = 40
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SETTINGS = APP_DIR / "settings.json"
LOG = logging.getLogger("EchoMic")


def virtual(name: str) -> bool:
    return any(s in name.lower() for s in ("cable", "virtual audio", "voicemeeter", "echo cancelled", "回音消除"))


def target(name: str) -> bool:
    """Never take over the user's existing, original VB-CABLE."""
    n = name.lower()
    return any(s in n for s in ("hi-fi cable", "hifi cable", "cable-a input", "cable-b input", "line 1 (virtual audio cable)", "echo cancelled mic", "回音消除麥克風"))


def list_devices():
    with pa.PyAudio() as audio:
        devices = list(audio.get_device_info_generator_by_host_api(host_api_type=pa.paWASAPI))
        defaults = audio.get_host_api_info_by_type(pa.paWASAPI)
    return devices, defaults


def pcm(samples: np.ndarray) -> bytes:
    return np.clip(samples * 32768.0, -32768, 32767).astype("<i2").tobytes()


def level(samples: np.ndarray) -> float:
    return max(-90.0, 20.0 * math.log10(max(float(np.sqrt(np.mean(samples * samples))), 1e-6)))


class TimedBuffer:
    """Timestamped circular buffer; missing/expired samples read as silence."""
    def __init__(self, seconds=3):
        self.size = int(RATE * seconds)
        self.data = np.zeros((self.size, 2), dtype=np.float32)
        self.tags = np.full(self.size, -1, dtype=np.int64)
        self.lock = threading.Lock()
        self.last_write = 0.0

    def write(self, timestamp, samples):
        if len(samples) > self.size:
            timestamp += (len(samples) - self.size) / RATE
            samples = samples[-self.size:]
        tags = round(timestamp * RATE) + np.arange(len(samples), dtype=np.int64)
        indices = tags % self.size
        with self.lock:
            self.data[indices] = samples
            self.tags[indices] = tags
            self.last_write = time.perf_counter()

    def read(self, timestamp, count):
        tags = round(timestamp * RATE) + np.arange(count, dtype=np.int64)
        indices = tags % self.size
        with self.lock:
            data = self.data[indices].copy()
            valid = self.tags[indices] == tags
        data[~valid] = 0
        return data


class OutputBuffer:
    def __init__(self, channels, rate=RATE):
        self.channels = channels
        self.rate = rate
        self.data = bytearray()
        self.lock = threading.Lock()
        self.underruns = 0
        self.dropped = 0

    def write(self, data):
        with self.lock:
            self.data.extend(data)
            limit = int(self.rate * .10) * self.channels * 4
            if len(self.data) > limit:
                excess = len(self.data) - int(self.rate * .04) * self.channels * 4
                del self.data[:excess]
                self.dropped += 1

    def callback(self, in_data, count, time_info, status):
        needed = count * self.channels * 4
        with self.lock:
            data = bytes(self.data[:needed])
            del self.data[:needed]
            if len(data) < needed:
                self.underruns += 1
                data += bytes(needed - len(data))
        return data, pa.paContinue


@dataclass
class Config:
    microphone: int
    speakers: list[int]
    output: int
    delay_ms: int = DEFAULT_DELAY_MS
    noise_suppression: bool = True
    gain: float = 1.0


class Capture:
    """Convert one hardware stream to timestamped 48 kHz frames off the callback."""
    def __init__(self, device, channels, sink):
        self.device, self.channels, self.sink = device, channels, sink
        self.rate = int(device["defaultSampleRate"])
        self.resampler = soxr.ResampleStream(self.rate, RATE, channels, dtype="float32", quality="LQ") if self.rate != RATE else None
        self.pending = np.empty((0, channels), dtype=np.float32)
        self.next_time = None
        self.raw = queue.Queue(maxsize=50)
        self.overflows = 0
        self.errors = 0

    def callback(self, data, count, time_info, status):
        # This pinned WASAPI backend reports currentTime + capture padding,
        # rather than subtracting padding. Its ADC timestamp can be in the future.
        # Correct that sign before mapping to our process-wide monotonic clock.
        now = time.perf_counter()
        delta = time_info.get("input_buffer_adc_time", 0) - time_info.get("current_time", 0)
        age = abs(delta) if 0 < abs(delta) < 2 and time_info.get("input_buffer_adc_time", 0) else count / self.rate
        timestamp = now - age
        if status:
            self.overflows += 1
        try:
            self.raw.put_nowait((timestamp, data))
        except queue.Full:
            self.overflows += 1
        return None, pa.paContinue

    def drain(self):
        while True:
            try:
                timestamp, data = self.raw.get_nowait()
            except queue.Empty:
                return
            samples = np.frombuffer(data, dtype="<f4").reshape(-1, self.channels)
            # Callback delivery has millisecond jitter: directly re-anchoring
            # each packet punches gaps into the render reference. Keep sample
            # continuity and slowly track the hardware clock instead.
            if self.next_time is None or abs(timestamp - self.next_time) > .03:
                self.next_time = timestamp
            clock_error = timestamp - self.next_time
            if self.resampler is None:
                converted = samples
            else:
                converted = self.resampler.resample_chunk(samples)
            if len(converted):
                self.sink(self.next_time, converted)
                self.next_time += len(converted) / RATE
                # 10-second tracking constant at 100 packets/second, bounded to
                # 200 ppm per update. AEC handles the remaining acoustic delay.
                self.next_time += float(np.clip(clock_error * .001, -.000002, .000002))


class EchoEngine:
    def __init__(self, config: Config, events=None):
        self.config = config
        self.events = events or queue.Queue()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.error = None
        self.stats = {"mic": -90., "reference": -90., "clean": -90., "frames": 0, "xruns": 0}
        self.lock = threading.Lock()

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("處理程式已在執行")
        self.thread = threading.Thread(target=self._run, name="WebRTC-AEC", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        streams = []
        audio = None
        try:
            audio = pa.PyAudio()
            cfg = self.config
            mic = audio.get_device_info_by_index(cfg.microphone)
            output = audio.get_device_info_by_index(cfg.output)
            if mic["isLoopbackDevice"] or virtual(mic["name"]) or not mic["maxInputChannels"]:
                raise ValueError("請選擇實體麥克風，避免音訊循環")
            if not target(output["name"]):
                raise ValueError("輸出必須是新增的 Hi-Fi Cable 或額外虛擬音訊裝置；原有 VB-CABLE 不會被使用")
            references = []
            captures = []
            for index in cfg.speakers:
                device = audio.get_device_info_by_index(index)
                if not device["isLoopbackDevice"] or virtual(device["name"]):
                    raise ValueError("回音參考只能選實體喇叭的 loopback")
                ring = TimedBuffer()
                references.append(ring)
                def sink(timestamp, data, ring=ring):
                    if data.shape[1] == 1:
                        data = np.repeat(data, 2, axis=1)
                    elif data.shape[1] > 2:
                        data = np.repeat(data.mean(axis=1, keepdims=True), 2, axis=1)
                    ring.write(timestamp, data)
                captures.append(Capture(device, min(int(device["maxInputChannels"]), 2), sink))
            if not references:
                raise ValueError("請至少選一個實際發聲的喇叭")

            mic_queue = deque()
            mic_pending = np.empty(0, dtype=np.float32)
            mic_time = None
            def microphone_sink(timestamp, data):
                nonlocal mic_pending, mic_time
                mono = data.mean(axis=1)
                if not len(mic_pending):
                    mic_time = timestamp
                elif abs(timestamp - (mic_time + len(mic_pending) / RATE)) > .1:
                    mic_pending = np.empty(0, dtype=np.float32)
                    mic_time = timestamp
                mic_pending = np.concatenate((mic_pending, mono))
                while len(mic_pending) >= FRAME:
                    mic_queue.append((mic_time, mic_pending[:FRAME].copy()))
                    mic_pending = mic_pending[FRAME:]
                    mic_time += .01
                while len(mic_queue) > 20:
                    mic_queue.popleft()
                    with self.lock:
                        self.stats["xruns"] += 1

            captures.append(Capture(mic, min(int(mic["maxInputChannels"]), 2), microphone_sink))
            processor = AudioProcessor(enable_aec=True, enable_ns=cfg.noise_suppression,
                                       ns_level=2, enable_agc=False, enable_vad=False)
            processor.set_stream_format(RATE, 1)
            processor.set_reverse_stream_format(RATE, 2)
            processor.set_stream_delay(cfg.delay_ms)
            channels = min(int(output["maxOutputChannels"]), 2)
            output_rate = int(output["defaultSampleRate"])
            output_resampler = soxr.ResampleStream(RATE, output_rate, channels, dtype="float32", quality="LQ") if output_rate != RATE else None
            out_buffer = OutputBuffer(channels, output_rate)
            # A small prefill avoids repeated startup underruns.
            out_buffer.write(bytes((output_rate * 3 // 100) * channels * 4))
            for capture in captures:
                streams.append(audio.open(format=pa.paFloat32, channels=capture.channels,
                    rate=capture.rate, input=True, input_device_index=int(capture.device["index"]),
                    frames_per_buffer=capture.rate // 100, stream_callback=capture.callback, start=False))
            streams.append(audio.open(format=pa.paFloat32, channels=channels, rate=output_rate,
                output=True, output_device_index=cfg.output, frames_per_buffer=output_rate // 100,
                stream_callback=out_buffer.callback, start=False))
            for stream in streams:
                stream.start_stream()
            self.ready.set()
            self.events.put(("started", output["name"]))
            LOG.info("Started microphone=%s references=%s output=%s", mic["name"], cfg.speakers, output["name"])
            frames = 0
            while not self.stop_event.is_set():
                for capture in captures:
                    capture.drain()
                # Let loopback packets arrive before reading the same time range.
                now = time.perf_counter()
                while mic_queue and now - mic_queue[0][0] >= .04:
                    timestamp, raw = mic_queue.popleft()
                    reference = sum((r.read(timestamp, FRAME) for r in references),
                                    np.zeros((FRAME, 2), dtype=np.float32))
                    np.clip(reference, -1, 1, out=reference)
                    processor.process_reverse_stream(pcm(reference))
                    processor.set_stream_delay(cfg.delay_ms)
                    clean = np.frombuffer(processor.process_stream(pcm(raw)), dtype="<i2").astype(np.float32) / 32768.
                    clean = np.clip(clean * cfg.gain, -1., 1.)
                    outgoing = np.repeat(clean[:, None], channels, axis=1).astype("<f4")
                    if output_resampler:
                        outgoing = output_resampler.resample_chunk(outgoing)
                    out_buffer.write(outgoing.astype("<f4").tobytes())
                    frames += 1
                    if frames % 10 == 0:
                        with self.lock:
                            self.stats.update(mic=level(raw), reference=level(reference), clean=level(clean),
                                              frames=frames, xruns=sum(c.overflows for c in captures) + out_buffer.dropped,
                                              underruns=out_buffer.underruns)
                if not all(s.is_active() for s in streams):
                    raise RuntimeError("音訊裝置已中斷；請重新整理並再次啟動")
                self.stop_event.wait(.002)
        except Exception as exc:
            self.error = str(exc)
            LOG.exception("Audio engine stopped")
            self.events.put(("error", str(exc)))
        finally:
            for stream in reversed(streams):
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    LOG.exception("Closing stream")
            if audio:
                audio.terminate()
            self.ready.set()
            self.events.put(("stopped", ""))


class App(tk.Tk):
    def __init__(self, startup=False, instance=None):
        enable_high_dpi()
        super().__init__()
        if startup:
            self.withdraw()
        self.instance = instance
        self.tray = None
        self.startup_pending = startup
        self.startup_attempts = 0
        self.title("Echo Mic｜回音消除麥克風")
        self.engine = None
        self.events = queue.Queue()
        self.saved = self.load_settings()
        self.speaker_vars = []
        self.mics, self.outputs = [], []
        self.closing = False
        self.calibrating = False
        self.calibration_process = None
        self.calibration_waiting = False
        self.calibration_cancelled = False
        self.resume_after_calibration = False
        build_ui(self, DEFAULT_DELAY_MS)
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.on_window_close)
        self.after(100, self.poll)
        if startup:
            self.after(300, self.start_in_background)

    def update_startup_button(self):
        try:
            enabled = startup_enabled()
            self.startup_button['text'] = '開機自動啟動：已開啟' if enabled else '開機自動啟動：已關閉'
        except OSError:
            LOG.exception('Reading login startup setting')
            self.startup_button['text'] = '開機自動啟動：無法讀取'

    def toggle_startup(self):
        try:
            enabled = not startup_enabled()
            set_startup(enabled)
            self.update_startup_button()
            self.status['text'] = ('已開啟：下次登入 Windows 後在系統匣啟動，使用上次已儲存的音訊設定。'
                                   if enabled else '已關閉開機自動啟動。')
        except (OSError, ValueError) as exc:
            messagebox.showerror('無法變更開機啟動', str(exc), parent=self)

    def save_close_behavior(self):
        updated = dict(self.saved, minimize_on_close=self.minimize_on_close.get())
        try:
            write_json(SETTINGS, updated)
            self.saved = updated
        except OSError as exc:
            self.minimize_on_close.set(self.saved.get('minimize_on_close', True))
            messagebox.showerror('無法儲存關閉設定', str(exc), parent=self)

    def on_window_close(self):
        if self.closing:
            return
        if self.minimize_on_close.get():
            return self.minimize_to_tray()
        self.close()

    def minimize_to_tray(self):
        if self.closing:
            return False
        try:
            if self.tray is None:
                self.tray = TrayIcon(self.events)
            self.tray.show()
            self.withdraw()
            return True
        except Exception as exc:
            LOG.exception('Showing tray icon')
            if self.tray:
                self.tray.stop()
                self.tray = None
            self.show_window()
            messagebox.showerror('無法縮小到系統匣', str(exc), parent=self)
            return False

    def show_window(self):
        if self.closing:
            return
        self.deiconify()
        self.lift()
        self.focus_force()
        if self.tray:
            self.tray.hide()

    def start_in_background(self):
        if self.minimize_to_tray():
            self._startup_attempt()
        else:
            self.startup_pending = False

    def _startup_attempt(self):
        if not self.startup_pending or self.closing:
            return
        self.startup_attempts += 1
        self.refresh()
        # Do not silently route a different microphone or speaker after login.
        names = {d['name'] for d, var in self.speaker_vars if var.get()}
        saved_refs = set(self.saved.get('speaker_names', []))
        ready = (any(d['name'] == self.saved.get('microphone_name') for d in self.mics)
                 and any(d['name'] == self.saved.get('output_name') for d in self.outputs)
                 and bool(saved_refs) and saved_refs == names)
        if ready:
            self.startup_pending = False
            self.start()
        elif self.startup_attempts < 20:
            self.status['text'] = '登入後正在等待上次使用的音訊裝置…'
            self.after(1500, self._startup_attempt)
        else:
            self.startup_pending = False
            self.show_window()
            self.status['text'] = '無法自動啟動：請確認上次的音訊裝置，選好後按「啟動回音消除」。'

    def destroy(self):
        # Tk's timer queue outlives widget commands; release callbacks before teardown.
        for job in self.tk.call('after', 'info'):
            self.after_cancel(job)
        if self.tray:
            self.tray.stop()
            self.tray = None
        super().destroy()

    @staticmethod
    def load_settings():
        try:
            return read_json(SETTINGS)
        except (OSError, ValueError):
            return {}

    def refresh(self):
        try:
            devices, defaults = list_devices()
            self.mics = [d for d in devices if d["maxInputChannels"] and not d["isLoopbackDevice"] and not virtual(d["name"])]
            self.outputs = [d for d in devices if d["maxOutputChannels"] and target(d["name"])]
            refs = [d for d in devices if d["isLoopbackDevice"] and not virtual(d["name"]) and "steam streaming" not in d["name"].lower()]
            for combo, options, key, default in ((self.mic_combo, self.mics, "microphone_name", defaults["defaultInputDevice"]),
                                                  (self.out_combo, self.outputs, "output_name", -1)):
                combo["values"] = [d["name"] for d in options]
                if options:
                    selected = next((i for i, d in enumerate(options) if d["name"] == self.saved.get(key)), None)
                    if selected is None:
                        selected = next((i for i, d in enumerate(options) if d["index"] == default), 0)
                    combo.current(selected)
                else:
                    combo.set("尚未安裝獨立虛擬裝置" if key == "output_name" else "找不到實體麥克風")
            for child in self.speakers_frame.winfo_children():
                child.destroy()
            self.speaker_vars = []
            default_speaker = next((d["name"] for d in devices if d["index"] == defaults["defaultOutputDevice"]), "")
            saved_refs = self.saved.get("speaker_names", [default_speaker + " [Loopback]"])
            for d in refs:
                var = tk.BooleanVar(value=d["name"] in saved_refs)
                ttk.Checkbutton(self.speakers_frame, text=d["name"].replace(" [Loopback]", ""), variable=var).pack(anchor="w", pady=self.display.px(2))
                self.speaker_vars.append((d, var))
            if not refs:
                ttk.Label(self.speakers_frame, text="找不到可用喇叭，請連接裝置後重新整理。",
                          style="CardHint.TLabel", wraplength=self.display.px(380)).pack(anchor="w")
            self.status["text"] = "裝置已就緒，按下啟動即可開始。" if self.outputs else "請先安裝虛擬裝置，再重新整理清單。"
            self.destination["text"] = "通話軟體的麥克風請選 Hi-Fi Cable Output。"
        except Exception as exc:
            LOG.exception("Enumerating devices")
            self.status["text"] = str(exc)

    def install_driver(self):
        script = APP_DIR / "Install-VirtualMic.ps1"
        if not script.exists():
            script = APP_DIR.parent.parent / "Install-VirtualMic.ps1"
        if not script.exists():
            messagebox.showerror("找不到安裝工具", "請使用完整的 EchoMic 資料夾，保留 Install-VirtualMic.ps1 與 drivers 資料夾。")
            return
        try:
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            self.status["text"] = "已開啟官方安裝程式。完成安裝／重新啟動後，重新整理裝置。"
        except OSError as exc:
            messagebox.showerror("安裝程式無法啟動", str(exc))

    def start(self):
        self.startup_pending = False
        if self.calibrating:
            return
        if self.engine and self.engine.thread.is_alive():
            return
        try:
            if self.mic_combo.current() < 0 or self.out_combo.current() < 0:
                raise ValueError("請先選擇原始麥克風與新的虛擬裝置")
            mic, output = self.mics[self.mic_combo.current()], self.outputs[self.out_combo.current()]
            speakers = [d for d, var in self.speaker_vars if var.get()]
            if not speakers:
                raise ValueError("請勾選至少一個實際發聲的喇叭")
            delay, gain = self.delay.get(), self.gain.get()
            if not 0 <= delay <= 500 or not .1 <= gain <= 3:
                raise ValueError("延遲範圍為 0～500 ms，音量倍率範圍為 0.1～3")
            updated = dict(self.saved, microphone_name=mic["name"], output_name=output["name"],
                              speaker_names=[d["name"] for d in speakers], delay_ms=delay,
                              gain=gain, noise_suppression=self.ns.get())
            write_json(SETTINGS, updated)
            self.saved = updated
            self.engine = EchoEngine(Config(int(mic["index"]), [int(d["index"]) for d in speakers],
                                           int(output["index"]), delay, self.ns.get(), gain), self.events)
            self.start_button["state"] = "disabled"
            self.stop_button["state"] = "normal"
            self.refresh_button["state"] = "disabled"
            self.install_button["state"] = "disabled"
            self.mic_combo["state"] = self.out_combo["state"] = "disabled"
            self.status["text"] = "正在開啟音訊裝置…"
            self.engine.start()
        except Exception as exc:
            self.show_window()
            messagebox.showerror("無法啟動", str(exc))

    def stop(self):
        self.startup_pending = False
        if self.calibrating:
            if not self.calibration_cancelled:
                self.calibration_cancel_time = time.monotonic()
            self.calibration_cancelled = True
            self.resume_after_calibration = False
            if self.calibration_process:
                self.calibration_report.with_suffix('.cancel').write_text('cancel', encoding='utf-8')
            self.status["text"] = "正在取消校正；原設定不變…"
            return
        if self.engine:
            self.engine.stop()
            self.status["text"] = "正在停止…"

    def close(self):
        self.startup_pending = False
        self.closing = True
        if self.calibrating or (self.engine and self.engine.thread.is_alive()):
            self.stop()
        else:
            self.destroy()

    def _calibration_controls(self, busy):
        for widget in (self.refresh_button, self.install_button, self.calibrate_button, self.start_button):
            widget['state'] = 'disabled' if busy else 'normal'
        for combo in (self.mic_combo, self.out_combo):
            combo['state'] = 'disabled' if busy else 'readonly'
        for widget in list(self.advanced.winfo_children()) + list(self.speakers_frame.winfo_children()):
            if widget.winfo_class() in ('TSpinbox', 'TCheckbutton'):
                widget['state'] = 'disabled' if busy else 'normal'
        self.stop_button['state'] = 'normal' if busy else 'disabled'
        self.stop_button['text'] = '取消校正' if busy else '停止'

    def calibrate(self):
        self.startup_pending = False
        if self.calibrating:
            return
        try:
            selected = [d for d, var in self.speaker_vars if var.get()]
            if self.mic_combo.current() < 0 or len(selected) != 1:
                raise ValueError('請選擇原始麥克風，並只勾選一個要校正的實體喇叭。')
            delay = self.delay.get()
            if not 0 <= delay <= 500:
                raise ValueError('延遲範圍為 0～500 ms')
            self.calibration_request = dict(microphone_name=self.mics[self.mic_combo.current()]['name'],
                speaker_name=selected[0]['name'].removesuffix(' [Loopback]'), delay_ms=delay)
            self.calibrating = True
            self.calibration_cancelled = False
            self.resume_after_calibration = bool(self.engine and self.engine.thread.is_alive())
            self._calibration_controls(True)
            if self.resume_after_calibration:
                self.calibration_waiting = True
                self.status['text'] = '校正前正在暫停麥克風輸出…'
                self.engine.stop()
            else:
                self._launch_calibration()
        except Exception as exc:
            if self.calibrating:
                self._finish_calibration(dict(state='error', message=str(exc)))
            else:
                messagebox.showerror('無法校正', str(exc))

    def _launch_calibration(self):
        try:
            directory = APP_DIR / 'logs'
            directory.mkdir(exist_ok=True)
            prefix = directory / ('calibration_' + time.strftime('%Y%m%d_%H%M%S') + '_' + str(time.time_ns() % 1_000_000))
            request_path = prefix.with_suffix('.request.json')
            self.calibration_report = prefix.with_suffix('.json')
            self.calibration_read_attempts = 0
            request_path.write_text(json.dumps(self.calibration_request, ensure_ascii=False), encoding='utf-8')
            command = [sys.executable]
            if not getattr(sys, 'frozen', False):
                command.append(str(Path(__file__).resolve()))
            command += ['--calibrate-worker', str(request_path), str(self.calibration_report)]
            self.calibration_process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            self.calibration_deadline = time.monotonic() + 90
            self.status['text'] = '準備校正語音；請保持安靜…'
        except Exception as exc:
            self._finish_calibration(dict(state='error', message=str(exc)))

    def _poll_calibration(self):
        if not self.calibration_process:
            return
        # Check exit BEFORE reading: a terminated worker has already published its final snapshot.
        exit_code = self.calibration_process.poll()
        try:
            report = read_json(self.calibration_report)
        except (OSError, ValueError):
            report = {}
        if exit_code is None:
            if time.monotonic() > self.calibration_deadline or (self.calibration_cancelled and time.monotonic() - self.calibration_cancel_time > 5):
                self.calibration_process.terminate()
                self.calibration_process.wait(timeout=5)
                self.calibration_process = None
                self._finish_calibration(dict(state='cancelled' if self.calibration_cancelled else 'error',
                    message='校正逾時，原設定未變更；請確認裝置後重試。'))
                return
            if report and not self.calibration_cancelled:
                self.status['text'] = report.get('message', '校正中…')
            return
        if report.get('state') not in ('completed', 'cancelled', 'error'):
            self.calibration_read_attempts = getattr(self, 'calibration_read_attempts', 0) + 1
            if self.calibration_read_attempts <= 10:
                return  # Let the next UI tick retry a briefly locked final report without blocking Tk.
            report = dict(state='error', message='無法讀取完整校正結果；原設定未變更，請確認記錄資料夾或重新嘗試。')
            LOG.error('Missing final calibration report: %s (exit code %s)', self.calibration_report, exit_code)
        self.calibration_process = None
        self._finish_calibration(report)

    def _finish_calibration(self, report):
        self.calibrating = self.calibration_waiting = False
        self._calibration_controls(False)
        message = report.get('message', '校正未完成；原設定未變更。')
        if report.get('state') == 'completed' and not self.calibration_cancelled:
            result = report['result']
            selected = int(result['selected_delay_ms'])
            try:
                updated = dict(self.saved, delay_ms=selected,
                    microphone_name=self.calibration_request['microphone_name'],
                    speaker_names=[self.calibration_request['speaker_name'] + ' [Loopback]'],
                    calibration=dict(report=str(self.calibration_report), result=result,
                                     ended_local=report.get('ended_local')))
                write_json(SETTINGS, updated)
                self.saved = updated
                self.delay.set(selected)
                path_delay = result.get('measured_path_delay_ms')
                if path_delay is not None:
                    message += f'\n測得訊號偏移：{path_delay:g} ms；實際 AEC 設定：{selected} ms。'
            except OSError as exc:
                message = f'校正結果未儲存，原設定保留：{exc}'
        if self.calibration_cancelled:
            message = '校正已取消；原設定未變更。'
        self.calibration_hint['text'] = message
        self.status['text'] = message
        resume = self.resume_after_calibration and not self.closing and not self.calibration_cancelled
        self.resume_after_calibration = False
        if resume:
            self.after(150, self.start)

    def poll(self):
        if self.instance and self.instance.show_requested():
            self.show_window()
        while True:
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "show":
                self.show_window()
            elif kind == "quit":
                self.closing = True
                self.stop()
            elif kind == "started":
                self.status["text"] = "回音消除運作中｜48 kHz · WebRTC AEC"
                self.destination["text"] = f"處理結果正送往：{text}；請在其他軟體選擇對應的錄製端。"
            elif kind == "error":
                self.status["text"] = f"已停止：{text}"
                if not self.closing:
                    self.show_window()
                    messagebox.showerror("音訊處理錯誤", text)
            elif kind == "stopped":
                if self.calibration_waiting:
                    self.calibration_waiting = False
                    if self.calibration_cancelled:
                        self._finish_calibration(dict(state='cancelled', message='校正已取消；原設定未變更。'))
                    else:
                        self._launch_calibration()
                    continue
                self.start_button["state"] = "normal"
                self.stop_button["state"] = "disabled"
                self.refresh_button["state"] = self.install_button["state"] = "normal"
                self.mic_combo["state"] = self.out_combo["state"] = "readonly"
                if not self.engine.error:
                    self.status["text"] = "已停止；新虛擬麥克風目前靜音"
        self._poll_calibration()
        update_activity(self)
        if self.engine:
            with self.engine.lock:
                stats = self.engine.stats.copy()
            for key, (meter, number) in self.meters.items():
                meter["value"] = max(0, stats[key] + 60)
                number["text"] = f"{stats[key]:.0f} dB"
        if self.closing and not self.calibrating and (not self.engine or not self.engine.thread.is_alive()):
            self.destroy()
            return
        self.after(100, self.poll)


def main():
    (APP_DIR / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(APP_DIR / "logs" / "echo_mic.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--smoke-test", type=float, metavar="SECONDS")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--startup", action="store_true", help="登入後在系統匣使用上次設定啟動")
    parser.add_argument("--calibrate-worker", nargs=2, metavar=('REQUEST', 'REPORT'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.calibrate_worker:
        from calibration import run_worker
        report = run_worker(*args.calibrate_worker)
        if report['state'] == 'error':
            raise SystemExit(1)
    elif args.self_check:
        from calibration import read_probe
        calibration_seconds = len(read_probe()) / RATE
        processor = AudioProcessor(enable_aec=True, enable_agc=False)
        processor.set_stream_format(RATE, 1)
        processor.set_reverse_stream_format(RATE, 2)
        processor.process_reverse_stream(bytes(FRAME * 4))
        assert len(processor.process_stream(bytes(FRAME * 2))) == FRAME * 2
        devices, defaults = list_devices()
        window = App()
        window.update()
        footer = window.footer
        layout_fits = (footer.winfo_y() + footer.winfo_height() <= window.winfo_height()
                       and window.start_button.winfo_ismapped()
                       and window.stop_button.winfo_ismapped())
        assert layout_fits, 'Window content is clipped'
        window.withdraw()
        window.update_idletasks()
        tray = TrayIcon(window.events)
        try:
            tray.show()
            tray_ok = tray.icon.visible
        finally:
            tray.stop()
        result = dict(ok=True, bundled_runtime=bool(getattr(sys, 'frozen', False)),
                      dpi_aware=dpi_awareness() == 2, window_dpi=window_dpi(window),
                      ui_scale=window.display.scale,
                      device_count=len(devices), aec=processor.aec_enabled(),
                      mics=len(window.mics), independent_outputs=len(window.outputs),
                      defaults=defaults, calibration_button=bool(window.calibrate_button.winfo_exists()),
                      startup_button=bool(window.startup_button.winfo_exists()),
                      close_behavior_checkbox=bool(window.close_behavior_check.winfo_exists()),
                      minimize_on_close=window.minimize_on_close.get(),
                      tray_backend=tray_ok, layout_fits=layout_fits,
                      calibration_probe_seconds=round(calibration_seconds, 2), default_delay_ms=DEFAULT_DELAY_MS)
        window.destroy()
        (APP_DIR / "logs" / "self-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        LOG.info("Self-check passed: %s", result)
    elif args.list_devices:
        devices, defaults = list_devices()
        print(json.dumps(dict(devices=devices, defaults=defaults), ensure_ascii=False, indent=2))
    elif args.smoke_test:
        devices, defaults = list_devices()
        outputs = [d for d in devices if d["maxOutputChannels"] and target(d["name"])]
        if not outputs:
            raise SystemExit("尚未安裝新增的虛擬音訊裝置；未使用現有 VB-CABLE。")
        loop = next(d for d in devices if d["isLoopbackDevice"] and d["name"] == next(x["name"] for x in devices if x["index"] == defaults["defaultOutputDevice"]) + " [Loopback]")
        engine = EchoEngine(Config(int(defaults["defaultInputDevice"]), [int(loop["index"])], int(outputs[0]["index"])))
        engine.start()
        engine.ready.wait(10)
        time.sleep(args.smoke_test)
        engine.stop()
        engine.thread.join(10)
        print(json.dumps(dict(error=engine.error, stats=engine.stats), indent=2))
        if engine.error or engine.thread.is_alive():
            raise SystemExit(1)
    else:
        instance = SingleInstance()
        try:
            if instance.already_running:
                if not args.startup:
                    instance.request_show()
                return
            App(startup=args.startup, instance=instance).mainloop()
        finally:
            instance.close()


if __name__ == "__main__":
    main()
