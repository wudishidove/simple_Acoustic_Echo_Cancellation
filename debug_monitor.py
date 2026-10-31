"""Bounded, local-only AEC shadow monitor. Saves statistics, never microphone audio."""
from __future__ import annotations
import argparse
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import time

import numpy as np
import pyaudiowpatch as pa
from aec_audio_processing import AudioProcessor
from echo_mic import Capture, FRAME, RATE, TimedBuffer, level, pcm
from json_store import read_json, write_json

ROOT = Path(__file__).resolve().parent
ANALYSIS_RATE = 8000


def spectrum(data, length=2048):
    data = np.asarray(data, dtype=np.float64)
    blocks = np.lib.stride_tricks.sliding_window_view(data, length)[::length // 2]
    return np.fft.rfft(blocks * np.hanning(length), axis=1)


def coherent_power(reference_fft, signal_fft):
    # Remove approximate finite-window coherence bias. This is an estimate of
    # speaker-correlated energy, not a measurement of near-end voice quality.
    power_ref = np.mean(abs(reference_fft) ** 2, axis=0)
    power_sig = np.mean(abs(signal_fft) ** 2, axis=0)
    cross = np.mean(np.conj(reference_fft) * signal_fft, axis=0)
    explained = abs(cross) ** 2 / np.maximum(power_ref, 1e-20)
    explained = np.maximum(explained - power_sig / len(signal_fft), 0)
    mask = power_ref > max(float(power_ref.max()) * 1e-5, 1e-18)
    return float(explained[mask].sum()), float(power_sig[mask].sum())


def analyze_window(data, labels):
    raw = data[:, 0]
    ref = data[:, 1:3]
    # Select the louder stereo channel rather than risking anti-phase downmix.
    mono = ref[:, int(np.argmax(np.mean(ref * ref, axis=0)))]
    result = dict(mic_dbfs=round(level(raw), 1), reference_dbfs=round(level(ref), 1),
                  full_output_dbfs=round(level(data[:, -1]), 1),
                  clipped_microphone_percent=round(float(np.mean(abs(raw) >= .98)) * 100, 3))
    if result['reference_dbfs'] < -60 or len(raw) < ANALYSIS_RATE * 2:
        result.update(assessment='insufficient_speaker_reference',
                      note='喇叭參考過小，無法評估回音消除；總音量下降不可當作回音抑制。')
        return result
    nfft = 1 << (2 * len(raw) - 1).bit_length()
    centered_ref, centered_raw = mono - mono.mean(), raw - raw.mean()
    corr = np.fft.irfft(np.fft.rfft(centered_raw, nfft) * np.conj(np.fft.rfft(centered_ref, nfft)), nfft)
    lags = np.arange(-800, 4001)
    scores = corr[lags % nfft] / max(float(np.linalg.norm(centered_ref) * np.linalg.norm(centered_raw)), 1e-15)
    best = int(np.argmax(abs(scores)))
    result['estimated_echo_lag_ms'] = round(float(lags[best]) / 8, 2)
    result['reference_correlation'] = round(float(abs(scores[best])), 4)
    ref_fft = spectrum(mono)
    before, total = coherent_power(ref_fft, spectrum(raw))
    fraction = before / max(total, 1e-20)
    result['estimated_speaker_correlated_fraction'] = round(fraction, 4)
    if fraction < .08 or result['reference_correlation'] < .08:
        result.update(assessment='weak_echo_evidence', note='喇叭有聲，但麥克風與參考的相關性偏低，不能可靠推論抑制量。')
        return result
    reductions = {}
    for index, label in enumerate(labels, start=3):
        after, _ = coherent_power(ref_fft, spectrum(data[:, index]))
        reductions[label] = round(float(np.clip(10 * np.log10(max(before, 1e-20) / max(after, 1e-20)), -60, 60)), 2)
    result['estimated_correlated_echo_reduction_db'] = reductions
    candidates = {k: v for k, v in reductions.items() if k.startswith('aec_only_')}
    result['best_delay_in_this_window_ms'] = int(max(candidates, key=candidates.get).split('_')[-1])
    result.update(assessment='echo_estimate_available',
                  note='只估算與喇叭相關成分的下降；若同時說話，不能據此宣稱人聲品質或純回音 ERLE。')
    return result


def monitor(seconds=600, window_seconds=10, directory=None):
    directory = Path(directory) if directory else ROOT / 'logs' / ('debug_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    directory.mkdir(parents=True, exist_ok=True)
    status_path = directory / 'status.json'
    stop_path = directory / 'stop.request'
    started = time.monotonic()
    summaries = []
    status = dict(state='starting', pid=os.getpid(), duration_seconds=seconds,
                  audio_saved=False, output_routed=False, stop_file=str(stop_path),
                  started_local=datetime.now().astimezone().isoformat())
    write_json(status_path, status)
    audio = None
    streams = []
    try:
        # Initialize/open all WASAPI streams on this one thread.
        audio = pa.PyAudio()
        devices = list(audio.get_device_info_generator_by_host_api(host_api_type=pa.paWASAPI))
        mic = next(d for d in devices if d['maxInputChannels'] and not d['isLoopbackDevice'] and 'am310' in d['name'].lower())
        speaker = next(d for d in devices if d['isLoopbackDevice'] and 'q serial' in d['name'].lower())
        try:
            settings = read_json(ROOT / 'dist' / 'EchoMic' / 'settings.json')
        except (OSError, ValueError):
            settings = {}
        delay = int(settings.get('delay_ms', 40))
        delays = sorted(set([0, 20, 40, 60, 80, 120, 160, delay]))
        labels = ['aec_only_' + str(d) for d in delays] + ['current_aec_plus_ns']
        processors = []
        for d in delays + [delay]:
            ns = len(processors) == len(delays) and settings.get('noise_suppression', True)
            processor = AudioProcessor(enable_aec=True, enable_ns=ns, enable_agc=False, enable_vad=False)
            processor.set_stream_format(RATE, 1)
            processor.set_reverse_stream_format(RATE, 2)
            processors.append((d, processor))
        ring = TimedBuffer()
        mic_queue = deque()
        pending = np.empty(0, dtype=np.float32)
        pending_time = 0.
        def mic_sink(timestamp, data):
            nonlocal pending, pending_time
            if not len(pending):
                pending_time = timestamp
            pending = np.concatenate((pending, data.mean(axis=1)))
            while len(pending) >= FRAME:
                mic_queue.append((pending_time, pending[:FRAME].copy()))
                pending = pending[FRAME:]
                pending_time += .01
        def ref_sink(timestamp, data):
            ring.write(timestamp, np.repeat(data, 2, axis=1) if data.shape[1] == 1 else data[:, :2])
        captures = [Capture(speaker, min(2, int(speaker['maxInputChannels'])), ref_sink),
                    Capture(mic, min(2, int(mic['maxInputChannels'])), mic_sink)]
        for capture in captures:
            streams.append(audio.open(format=pa.paFloat32, channels=capture.channels, rate=capture.rate,
                input=True, input_device_index=capture.device['index'], frames_per_buffer=capture.rate // 100,
                stream_callback=capture.callback, start=False))
        for stream in streams:
            stream.start_stream()
        status.update(state='running', microphone=mic['name'], speaker=speaker['name'],
                      compared_delays_ms=delays, configured_delay_ms=delay)
        write_json(status_path, status)
        blocks, coverages = [], []
        frames = 0
        last_report = 0
        while time.monotonic() - started < seconds and not stop_path.exists():
            for capture in captures:
                capture.drain()
            while mic_queue and time.perf_counter() - mic_queue[0][0] >= .04:
                timestamp, raw = mic_queue.popleft()
                ref = ring.read(timestamp, FRAME)
                tags = round(timestamp * RATE) + np.arange(FRAME, dtype=np.int64)
                with ring.lock:
                    coverage = float(np.mean(ring.tags[tags % ring.size] == tags))
                outputs = []
                reverse, forward = pcm(ref), pcm(raw)
                for d, processor in processors:
                    processor.process_reverse_stream(reverse)
                    processor.set_stream_delay(d)
                    output = processor.process_stream(forward)
                    outputs.append(np.frombuffer(output, dtype='<i2').astype(np.float32) / 32768.)
                samples = np.column_stack([raw, ref] + outputs)
                # Six-sample boxcar low-pass for lightweight 8 kHz diagnostic
                # analysis. The actual AEC above always receives full 48 kHz.
                blocks.append(samples.reshape(80, 6, -1).mean(axis=1))
                coverages.append(coverage)
                frames += 1
                if len(blocks) >= window_seconds * 100:
                    summary = analyze_window(np.concatenate(blocks), labels)
                    summary.update(elapsed_seconds=round(time.monotonic() - started, 1),
                                   reference_coverage_percent=round(float(np.mean(coverages)) * 100, 2),
                                   capture_xruns=sum(c.overflows for c in captures))
                    summaries.append(summary)
                    with (directory / 'metrics.jsonl').open('a', encoding='utf-8') as log:
                        log.write(json.dumps(summary, ensure_ascii=False, allow_nan=False) + '\n')
                    status['latest_window'] = summary
                    blocks.clear()
                    coverages.clear()
            elapsed = time.monotonic() - started
            if elapsed - last_report >= 1:
                status.update(elapsed_seconds=round(elapsed, 1), frames_processed=frames,
                              remaining_seconds=max(0, round(seconds - elapsed)),
                              microphone_dbfs=round(level(raw), 1) if frames else None,
                              speaker_dbfs=round(level(ref), 1) if frames else None)
                write_json(status_path, status)
                last_report = elapsed
            if not all(s.is_active() for s in streams):
                raise RuntimeError('音訊裝置已中斷')
            time.sleep(.002)
        status['state'] = 'stopped_by_user' if stop_path.exists() else 'completed'
        status['windows_analyzed'] = len(summaries)
    except Exception as exc:
        status.update(state='error', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        for stream in reversed(streams):
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if audio:
            audio.terminate()
        status['ended_local'] = datetime.now().astimezone().isoformat()
        write_json(status_path, status)
        write_json(directory / 'summary.json', dict(status=status, windows=summaries))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AM310 + Q serial 本機背景回音診斷；不保存錄音。')
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--window', type=int, default=10)
    parser.add_argument('--directory')
    args = parser.parse_args()
    if not 3 <= args.seconds <= 3600 or not 3 <= args.window <= 30:
        parser.error('seconds 須介於 3～3600；window 須介於 3～30')
    monitor(args.seconds, args.window, args.directory)
