import unittest
import numpy as np
from aec_audio_processing import AudioProcessor
from echo_mic import FRAME, RATE, Capture, TimedBuffer, OutputBuffer, pcm, target
from unittest.mock import patch


class AudioTests(unittest.TestCase):
    def test_capture_clock_rejects_callback_delivery_jitter(self):
        observed = []
        capture = Capture({'defaultSampleRate': 48000}, 1, lambda t, x: observed.append(t))
        for i in range(100):
            jitter = (0, .002, -.002, .001)[i % 4]
            capture.raw.put((100 + i * .01 + jitter, bytes(FRAME * 4)))
            capture.drain()
        intervals = np.diff(observed)
        self.assertLess(float(np.max(np.abs(intervals - .01))), .000003)
        self.assertAlmostEqual(observed[-1], 100.99, delta=.001)

    def test_wasapi_capture_padding_never_dates_audio_in_future(self):
        capture = Capture({'defaultSampleRate': 48000}, 1, lambda *args: None)
        with patch('echo_mic.time.perf_counter', return_value=100.):
            capture.callback(bytes(FRAME * 4), FRAME,
                             {'input_buffer_adc_time': 500.01, 'current_time': 500.}, 0)
        timestamp, _ = capture.raw.get_nowait()
        self.assertAlmostEqual(timestamp, 99.99)

    def test_timestamp_gap_and_wrap(self):
        ring = TimedBuffer(seconds=.03)
        values = np.full((FRAME, 2), .25, dtype=np.float32)
        ring.write(100., values)
        np.testing.assert_allclose(ring.read(100., FRAME), values)
        np.testing.assert_array_equal(ring.read(100.01, FRAME), 0)
        ring.write(100.03, values * 2)
        np.testing.assert_array_equal(ring.read(100., FRAME), 0)
        np.testing.assert_allclose(ring.read(100.03, FRAME), .5)

    def test_keep_original_vb_cable_free(self):
        self.assertFalse(target('CABLE Input (VB-Audio Virtual Cable)'))
        self.assertTrue(target('Hi-Fi Cable Input (VB-Audio Hi-Fi Cable)'))
        self.assertTrue(target('CABLE-A Input (VB-Audio Cable A)'))
        self.assertFalse(target('Speakers (Realtek Audio)'))

    def test_pcm_saturates_instead_of_wrapping(self):
        result = np.frombuffer(pcm(np.array([-2., -1., 0., 1., 2.])), dtype='<i2')
        np.testing.assert_array_equal(result, [-32768, -32768, 0, 32767, 32767])

    def test_output_underflow_is_silence_and_backlog_bounded(self):
        out = OutputBuffer(2)
        out.write(bytes(FRAME * 2 * 4))
        data, _ = out.callback(None, FRAME * 2, {}, 0)
        self.assertEqual(len(data), FRAME * 2 * 2 * 4)
        self.assertEqual(out.underruns, 1)
        for _ in range(100):
            out.write(bytes(FRAME * 2 * 4))
        self.assertLessEqual(len(out.data), RATE * .1 * 2 * 4)
        self.assertGreater(out.dropped, 0)

    def test_webrtc_reduces_delayed_room_echo(self):
        rng = np.random.default_rng(7)
        seconds = 12
        noise = rng.normal(0, .12, RATE * seconds).astype(np.float32)
        # A colored signal and three delayed reflections model a speaker/room.
        reference = np.convolve(noise, np.ones(5) / 5, mode='same').astype(np.float32)
        recorded = np.zeros_like(reference)
        for delay, gain in ((.04, .65), (.047, .22), (.065, -.13)):
            offset = round(delay * RATE)
            recorded[offset:] += reference[:-offset] * gain
        processor = AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False, enable_vad=False)
        processor.set_stream_format(RATE, 1)
        processor.set_reverse_stream_format(RATE, 2)
        results = []
        for pos in range(0, len(reference), FRAME):
            reverse = np.repeat(reference[pos:pos+FRAME, None], 2, axis=1)
            processor.process_reverse_stream(pcm(reverse))
            processor.set_stream_delay(40)
            results.append(np.frombuffer(processor.process_stream(pcm(recorded[pos:pos+FRAME])), dtype='<i2').astype(np.float32) / 32768.)
        clean = np.concatenate(results)
        start = RATE * 8
        attenuation = 10 * np.log10(np.mean(recorded[start:] ** 2) / max(np.mean(clean[start:] ** 2), 1e-12))
        print(f'\nSynthetic echo attenuation: {attenuation:.1f} dB')
        self.assertGreater(attenuation, 10., 'AEC should suppress the delayed reference, not just route microphone audio')

    def test_near_end_voice_survives_without_reference(self):
        processor = AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False, enable_vad=False)
        processor.set_stream_format(RATE, 1)
        processor.set_reverse_stream_format(RATE, 2)
        t = np.arange(RATE * 2) / RATE
        voice = (.15 * np.sin(2 * np.pi * 213 * t) + .07 * np.sin(2 * np.pi * 617 * t)).astype(np.float32)
        results = []
        for pos in range(0, len(voice), FRAME):
            processor.process_reverse_stream(bytes(FRAME * 2 * 2))
            processor.set_stream_delay(40)
            results.append(np.frombuffer(processor.process_stream(pcm(voice[pos:pos+FRAME])), dtype='<i2').astype(np.float32) / 32768.)
        clean = np.concatenate(results)[RATE:]
        self.assertGreater(np.sqrt(np.mean(clean ** 2)), np.sqrt(np.mean(voice[RATE:] ** 2)) * .5)


if __name__ == '__main__':
    unittest.main()
