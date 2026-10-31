"""Local, bounded calibration. Recordings remain in memory and are never saved."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import logging
from pathlib import Path
import sys
import time
import wave

import numpy as np
import pyaudiowpatch as pa
import soxr
from aec_audio_processing import AudioProcessor

from echo_mic import Capture, FRAME, RATE, TimedBuffer, pcm, virtual
from debug_monitor import ANALYSIS_RATE, analyze_window
from json_store import read_json, write_json

LOG = logging.getLogger('EchoMic')


class Cancelled(Exception):
    pass


def probe_path():
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return bundle / 'assets' / 'calibration_speech.wav'


def read_probe(path=None):
    path = Path(path) if path else probe_path()
    with wave.open(str(path), 'rb') as wav:
        if wav.getsampwidth() != 2:
            raise ValueError('校正音檔格式錯誤，請重新執行 Build.ps1')
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)
        data = data.reshape(-1, wav.getnchannels()).mean(axis=1) / 32768.
        rate = wav.getframerate()
    if rate != RATE:
        data = soxr.resample(data, rate, RATE).astype(np.float32)
    if not RATE * 12 <= len(data) <= RATE * 30:
        raise ValueError('校正音檔長度須介於 12～30 秒')
    data *= .20 / max(float(np.max(np.abs(data))), 1e-9)
    return data


def choose_delay(windows, current_delay, coverage_percent, xruns=0):
    """Keep the current setting unless a repeatable, material benefit exists."""
    result = dict(previous_delay_ms=current_delay, selected_delay_ms=current_delay,
                  applied_change=False, reliable=False)
    valid = [w for w in windows if w.get('assessment') == 'echo_estimate_available'
             and w.get('reference_correlation', 0) >= .12
             and w.get('estimated_speaker_correlated_fraction', 0) >= .15
             and w.get('clipped_microphone_percent', 100) < .1]
    if coverage_percent < 98 or xruns:
        result.update(reason='capture_quality', message='擷取有缺口或中斷，保留原設定；請關閉其他高負載程式後重試。')
        return result
    if len(valid) < 2:
        result.update(reason='insufficient_evidence', message='有效回音訊號不足，保留原設定；請確認喇叭有聲、靠近正常使用音量，並保持安靜。')
        return result
    keys = set.intersection(*(set(w['estimated_correlated_echo_reduction_db']) for w in valid))
    keys = [key for key in keys if key.startswith('aec_only_')]
    baseline_key = f'aec_only_{current_delay}'
    if baseline_key not in keys:
        result.update(reason='missing_baseline', message='缺少目前參數的對照結果，保留原設定。')
        return result
    scores = {int(key.rsplit('_', 1)[-1]): float(np.median([
        w['estimated_correlated_echo_reduction_db'][key] for w in valid])) for key in keys}
    # Differences under 1 dB are treated as equivalent; prefer staying close to
    # the user's existing value rather than chasing estimation noise.
    best_score = max(scores.values())
    tied = [d for d, value in scores.items() if best_score - value <= 1.]
    winner = min(tied, key=lambda d: (abs(d - current_delay), d))
    delta = np.array([w['estimated_correlated_echo_reduction_db'][f'aec_only_{winner}']
                      - w['estimated_correlated_echo_reduction_db'][baseline_key] for w in valid])
    result.update(reliable=True, valid_windows=len(valid), median_scores_db={str(k): round(v, 2) for k, v in sorted(scores.items())},
                  measured_path_delay_ms=round(float(np.median([w['estimated_echo_lag_ms'] for w in valid])), 1),
                  estimated_improvement_db=round(float(np.median(delta)), 2))
    if winner != current_delay and float(np.median(delta)) >= 3. and np.count_nonzero(delta >= 2.) >= 2 and np.min(delta) >= -1.:
        result.update(selected_delay_ms=winner, applied_change=True, reason='repeatable_improvement',
                      message=f'已選用 {winner} ms；喇叭相關成分的估計抑制量，比原設定改善約 {float(np.median(delta)):.1f} dB。')
    else:
        result.update(reason='equivalent_or_uncertain', message=f'保留 {current_delay} ms；其他候選沒有穩定、明確的改善。')
    return result


def candidate_delays(current_delay, measured_delay=None):
    delays = {0, 20, 40, 60, 80, 120, 160, 200, current_delay}
    if measured_delay is not None and 0 <= measured_delay <= 500:
        center = int(np.floor(measured_delay + .5))
        delays.update(max(0, min(500, center + offset)) for offset in (-10, -5, -2, -1, 0, 1, 2, 5, 10))
    return sorted(delays)


def measure_recording_offset(recording, current_delay):
    offsets = []
    for pos in range(RATE * 4, len(recording) - RATE * 4 + 1, RATE * 4):
        samples = recording[pos:pos + RATE * 4].reshape(-1, 6, 3).mean(axis=1)
        # Only the raw/reference pair is needed here. Reusing the scorer also
        # applies the same signal-quality gate before selecting fine candidates.
        check = analyze_window(np.column_stack((samples, samples[:, 0])), [f'aec_only_{current_delay}'])
        if (check.get('assessment') == 'echo_estimate_available'
                and check.get('reference_correlation', 0) >= .12
                and check.get('estimated_speaker_correlated_fraction', 0) >= .15):
            offsets.append(check['estimated_echo_lag_ms'])
    return float(np.median(offsets)) if offsets else None


def evaluate(recording, current_delay, coverage_percent, xruns, status, cancelled):
    status('analyzing', 0, '正在量測訊號偏移並建立細部延遲候選…')
    measured_delay = measure_recording_offset(recording, current_delay)
    delays = candidate_delays(current_delay, measured_delay)
    processors = []
    for delay in delays:
        processor = AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False, enable_vad=False)
        processor.set_stream_format(RATE, 1)
        processor.set_reverse_stream_format(RATE, 2)
        processors.append((delay, processor))
    labels = [f'aec_only_{d}' for d in delays]
    blocks, windows = [], []
    for frame_index, pos in enumerate(range(0, len(recording) - FRAME + 1, FRAME)):
        if frame_index % 100 == 0:
            if cancelled():
                raise Cancelled()
            status('analyzing', min(99, round(100 * pos / len(recording))), '正在比較 AEC 延遲候選…')
        frame = recording[pos:pos + FRAME]
        raw, reference = frame[:, 0], frame[:, 1:3]
        reverse, forward = pcm(reference), pcm(raw)
        outputs = []
        for delay, processor in processors:
            processor.process_reverse_stream(reverse)
            processor.set_stream_delay(delay)
            outputs.append(np.frombuffer(processor.process_stream(forward), dtype='<i2').astype(np.float32) / 32768.)
        # First four seconds are only for AEC convergence, not scoring.
        if pos < RATE * 4:
            continue
        samples = np.column_stack([raw, reference] + outputs)
        blocks.append(samples.reshape(80, 6, -1).mean(axis=1))
        if len(blocks) == 400:
            window = analyze_window(np.concatenate(blocks), labels)
            native_raw = recording[pos + FRAME - RATE * 4:pos + FRAME, 0]
            window['clipped_microphone_percent'] = round(float(np.mean(np.abs(native_raw) >= .98)) * 100, 3)
            window['ending_second'] = round((pos + FRAME) / RATE, 2)
            windows.append(window)
            blocks.clear()
    result = choose_delay(windows, current_delay, coverage_percent, xruns)
    result.update(windows=windows, reference_coverage_percent=round(coverage_percent, 3), capture_xruns=xruns,
                  candidate_delays_ms=delays, audio_saved=False,
                  initial_measured_offset_ms=measured_delay,
                  rounded_offset_candidate_ms=int(np.floor(measured_delay + .5)) if measured_delay is not None and 0 <= measured_delay <= 500 else None,
                  note='量測的是相關回音成分；聲學路徑延遲不直接當作 AEC 參數，亦不代表雙向人聲品質。')
    return result


def run_worker(request_path, report_path):
    request_path, report_path = Path(request_path), Path(report_path)
    cancel_path = report_path.with_suffix('.cancel')
    request = read_json(request_path)
    metadata = dict(state='starting', audio_saved=False,
                    microphone=request['microphone_name'], speaker=request['speaker_name'],
                    started_local=datetime.now().astimezone().isoformat())
    def status(state, progress, message):
        metadata.update(state=state, progress_percent=progress, message=message)
        try:
            write_json(report_path, metadata, retry_timeout=.1)
        except PermissionError:
            # Progress is advisory; a temporary lock must not discard a valid capture.
            LOG.warning('Skipping locked calibration progress snapshot: %s', report_path, exc_info=True)
    def cancelled():
        return cancel_path.exists()
    audio, streams = None, []
    try:
        speech = read_probe()
        if cancelled():
            raise Cancelled()
        audio = pa.PyAudio()
        devices = list(audio.get_device_info_generator_by_host_api(host_api_type=pa.paWASAPI))
        mic = next((d for d in devices if d['name'] == request['microphone_name'] and d['maxInputChannels'] and not d['isLoopbackDevice']), None)
        speaker = next((d for d in devices if d['name'] == request['speaker_name'] and d['maxOutputChannels']), None)
        loop = next((d for d in devices if d['isLoopbackDevice'] and d['name'] == request['speaker_name'] + ' [Loopback]'), None)
        if mic is None or speaker is None or loop is None or virtual(mic['name']) or virtual(speaker['name']):
            raise ValueError('裝置已改變或不是實體音訊裝置；請重新整理再校正。')
        ring, mic_queue = TimedBuffer(), deque()
        pending, pending_time = np.empty(0, dtype=np.float32), 0.
        def mic_sink(timestamp, samples):
            nonlocal pending, pending_time
            if not len(pending):
                pending_time = timestamp
            pending = np.concatenate((pending, samples.mean(axis=1)))
            while len(pending) >= FRAME:
                mic_queue.append((pending_time, pending[:FRAME].copy()))
                pending = pending[FRAME:]
                pending_time += .01
        def ref_sink(timestamp, samples):
            ring.write(timestamp, np.repeat(samples, 2, axis=1) if samples.shape[1] == 1 else samples[:, :2])
        captures = [Capture(loop, min(2, int(loop['maxInputChannels'])), ref_sink),
                    Capture(mic, min(2, int(mic['maxInputChannels'])), mic_sink)]
        for capture in captures:
            streams.append(audio.open(format=pa.paFloat32, channels=capture.channels, rate=capture.rate,
                input=True, input_device_index=capture.device['index'], frames_per_buffer=capture.rate // 100,
                stream_callback=capture.callback, start=False))
        output_rate = int(speaker['defaultSampleRate'])
        signal = np.concatenate((np.zeros(RATE, dtype=np.float32), speech, np.zeros(RATE, dtype=np.float32)))
        if output_rate != RATE:
            signal = soxr.resample(signal, RATE, output_rate).astype(np.float32)
        channels = min(2, int(speaker['maxOutputChannels']))
        signal = np.repeat(signal[:, None], channels, axis=1).astype('<f4')
        played = 0
        def play_callback(data, count, info, flags):
            nonlocal played
            if cancelled():
                return bytes(count * channels * 4), pa.paComplete
            chunk = signal[played:played + count]
            played += len(chunk)
            output = chunk.tobytes()
            output += bytes((count - len(chunk)) * channels * 4)
            return output, pa.paComplete if played >= len(signal) else pa.paContinue
        streams.append(audio.open(format=pa.paFloat32, channels=channels, rate=output_rate,
            output=True, output_device_index=speaker['index'], frames_per_buffer=output_rate // 100,
            stream_callback=play_callback, start=False))
        status('capturing', 0, '正在播放校正語音；請保持安靜，不要調整喇叭音量。')
        for stream in streams:
            stream.start_stream()
        started = time.monotonic()
        duration = len(signal) / output_rate
        frames, coverages = [], []
        last_status = 0.
        while time.monotonic() - started < duration + .3:
            if cancelled():
                raise Cancelled()
            for capture in captures:
                capture.drain()
            while mic_queue and time.perf_counter() - mic_queue[0][0] >= .04:
                timestamp, raw = mic_queue.popleft()
                reference = ring.read(timestamp, FRAME)
                tags = round(timestamp * RATE) + np.arange(FRAME, dtype=np.int64)
                with ring.lock:
                    coverages.append(float(np.mean(ring.tags[tags % ring.size] == tags)))
                frames.append(np.column_stack((raw, reference)))
            elapsed = time.monotonic() - started
            if elapsed - last_status >= .5:
                status('capturing', min(99, round(100 * elapsed / duration)), f'校正語音播放中，約剩 {max(0, round(duration - elapsed))} 秒；請保持安靜。')
                last_status = elapsed
            if not all(stream.is_active() for stream in streams[:-1]):
                raise ValueError('校正時音訊裝置已中斷，原設定未變更。')
            time.sleep(.002)
        for stream in reversed(streams):
            stream.stop_stream()
            stream.close()
        streams.clear()
        audio.terminate()
        audio = None
        if len(frames) < (duration - 1) * 100:
            raise ValueError('校正音訊不完整，原設定未變更。')
        recording = np.concatenate(frames)
        result = evaluate(recording, int(request['delay_ms']), float(np.mean(coverages)) * 100,
                          sum(c.overflows for c in captures), status, cancelled)
        metadata.update(state='completed', progress_percent=100, result=result, message=result['message'])
    except Cancelled:
        metadata.update(state='cancelled', message='校正已取消；原設定未變更。')
    except Exception as exc:
        metadata.update(state='error', message=str(exc), error=type(exc).__name__)
    finally:
        for stream in reversed(streams):
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if audio:
            audio.terminate()
        metadata['ended_local'] = datetime.now().astimezone().isoformat()
        try:
            write_json(report_path, metadata)
        except OSError:
            LOG.exception('Saving final calibration report: %s', report_path)
            metadata.update(state='error', message='無法儲存校正報告；原設定未變更，請確認記錄資料夾可寫入後重試。')
    return metadata
