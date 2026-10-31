"""Play generated speech ONLY through Q serial for an acoustic room test."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
import wave
import numpy as np
import pyaudiowpatch as pa
import soxr


def play(repeats=2, wait=8):
    root = Path(__file__).resolve().parent
    with wave.open(str(root / 'assets' / 'calibration_speech.wav'), 'rb') as wav:
        if wav.getsampwidth() != 2:
            raise ValueError('Expected 16-bit generated WAV')
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)
        samples = samples.reshape(-1, wav.getnchannels()).mean(axis=1) / 32768.
        source_rate = wav.getframerate()
    with pa.PyAudio() as audio:
        speaker = next(d for d in audio.get_device_info_generator_by_host_api(host_api_type=pa.paWASAPI)
                       if d['maxOutputChannels'] and 'q serial' in d['name'].lower())
        rate = int(speaker['defaultSampleRate'])
        if source_rate != rate:
            samples = soxr.resample(samples, source_rate, rate).astype(np.float32)
        samples *= .20 / max(float(np.max(np.abs(samples))), 1e-9)
        signal = np.repeat(samples[:, None], min(2, int(speaker['maxOutputChannels'])), axis=1)
        time.sleep(wait)
        print(json.dumps(dict(state='playing', speaker=speaker['name'], seconds=len(samples) / rate * repeats,
                              peak_dbfs=-13.98, started_local=datetime.now().astimezone().isoformat()), ensure_ascii=False), flush=True)
        stream = audio.open(format=pa.paFloat32, channels=signal.shape[1], rate=rate, output=True,
                            output_device_index=speaker['index'], frames_per_buffer=rate // 100)
        try:
            for _ in range(repeats):
                for start in range(0, len(signal), rate // 10):
                    stream.write(signal[start:start + rate // 10].astype('<f4').tobytes())
        finally:
            stream.stop_stream()
            stream.close()
    print(json.dumps(dict(state='completed', ended_local=datetime.now().astimezone().isoformat())), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--wait', type=float, default=8)
    args = parser.parse_args()
    play(args.repeats, args.wait)
