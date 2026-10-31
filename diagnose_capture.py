"""Read-only hardware check. No recording is saved and no output is played."""
import json
import time
import numpy as np
import pyaudiowpatch as pa
from echo_mic import Capture, list_devices


def run(seconds=3):
    devices, defaults = list_devices()
    mic = next(d for d in devices if d['index'] == defaults['defaultInputDevice'])
    speaker = next(d for d in devices if d['index'] == defaults['defaultOutputDevice'])
    loop = next(d for d in devices if d['isLoopbackDevice'] and d['name'] == speaker['name'] + ' [Loopback]')
    counts = {}
    captures = []
    for label, device in (('microphone', mic), ('speaker', loop)):
        counts[label] = dict(frames=0, peak=0., max_timestamp_age_ms=0.)
        def sink(timestamp, data, label=label):
            stats = counts[label]
            stats['frames'] += len(data)
            stats['peak'] = max(stats['peak'], float(np.max(np.abs(data))) if len(data) else 0.)
            stats['max_timestamp_age_ms'] = max(stats['max_timestamp_age_ms'], (time.perf_counter() - timestamp) * 1000)
        captures.append(Capture(device, min(2, device['maxInputChannels']), sink))
    with pa.PyAudio() as audio:
        streams = []
        try:
            for capture in captures:
                streams.append(audio.open(format=pa.paFloat32, channels=capture.channels, rate=capture.rate,
                    input=True, input_device_index=capture.device['index'], frames_per_buffer=capture.rate // 100,
                    stream_callback=capture.callback))
            until = time.perf_counter() + seconds
            while time.perf_counter() < until:
                for capture in captures:
                    capture.drain()
                time.sleep(.002)
            for capture in captures:
                capture.drain()
        finally:
            for stream in reversed(streams):
                stream.stop_stream()
                stream.close()
    print(json.dumps(counts, indent=2))
    if counts['microphone']['frames'] < seconds * 48000 * .8:
        raise RuntimeError('Microphone capture produced too few frames')


if __name__ == '__main__':
    run()
