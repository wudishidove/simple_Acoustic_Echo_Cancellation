import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from calibration import candidate_delays, choose_delay, measure_recording_offset, run_worker


def observation(scores, **changes):
    result = dict(assessment='echo_estimate_available', reference_correlation=.5,
                  estimated_speaker_correlated_fraction=.5, clipped_microphone_percent=0,
                  estimated_echo_lag_ms=51.,
                  estimated_correlated_echo_reduction_db={f'aec_only_{k}': v for k, v in scores.items()})
    result.update(changes)
    return result


class CalibrationTests(unittest.TestCase):
    def test_measured_50_point_1_includes_50_and_fine_neighbors(self):
        delays = candidate_delays(40, 50.1)
        self.assertTrue({40, 45, 48, 49, 50, 51, 52, 55, 60}.issubset(delays))
        self.assertTrue(all(isinstance(delay, int) for delay in delays))

    def test_fine_candidates_respect_supported_range(self):
        self.assertTrue(all(0 <= delay <= 500 for delay in candidate_delays(40, .1)))
        self.assertTrue(all(0 <= delay <= 500 for delay in candidate_delays(40, 499.9)))
        self.assertEqual(candidate_delays(40, -20), candidate_delays(40))

    def test_recording_offset_drives_the_candidate_set(self):
        rate = 48000
        rng = np.random.default_rng(25)
        reference = rng.normal(0, .12, rate * 12).astype(np.float32)
        near = rng.normal(0, .002, len(reference)).astype(np.float32)
        offset = round(.0501 * rate)
        near[offset:] += reference[:-offset] * .5
        recording = np.column_stack((near, reference, reference))
        measured = measure_recording_offset(recording, 40)
        self.assertAlmostEqual(measured, 50.1, delta=.2)
        self.assertIn(50, candidate_delays(40, measured))

    def test_path_delay_is_not_blindly_applied_as_aec_delay(self):
        rows = [observation({0: 25.5, 40: 25., 60: 25.6}), observation({0: 25.8, 40: 25.4, 60: 25.7})]
        result = choose_delay(rows, 40, 100)
        self.assertTrue(result['reliable'])
        self.assertEqual(result['measured_path_delay_ms'], 51.)
        self.assertEqual(result['selected_delay_ms'], 40)
        self.assertFalse(result['applied_change'])

    def test_repeatable_improvement_changes_delay(self):
        result = choose_delay([observation({40: 10, 60: 16, 80: 15.5}),
                               observation({40: 12, 60: 17, 80: 16.8})], 40, 99.9)
        self.assertEqual(result['selected_delay_ms'], 60)
        self.assertTrue(result['applied_change'])
        self.assertGreaterEqual(result['estimated_improvement_db'], 3)

    def test_one_bad_window_prevents_optimizing_only_the_median(self):
        rows = [observation({40: 10, 60: 16}), observation({40: 10, 60: 16}), observation({40: 15, 60: 12})]
        self.assertFalse(choose_delay(rows, 40, 100)['applied_change'])

    def test_silence_or_near_end_dominance_keeps_previous_value(self):
        rows = [observation({40: 5, 60: 15}, estimated_speaker_correlated_fraction=.04)] * 3
        result = choose_delay(rows, 40, 100)
        self.assertFalse(result['reliable'])
        self.assertEqual(result['selected_delay_ms'], 40)

    def test_dropouts_do_not_generate_a_new_setting(self):
        rows = [observation({40: 10, 60: 20})] * 3
        self.assertFalse(choose_delay(rows, 40, 95)['applied_change'])
        self.assertFalse(choose_delay(rows, 40, 100, xruns=1)['applied_change'])

    def test_cancellation_does_not_open_audio_or_save_recording(self):
        with tempfile.TemporaryDirectory() as temporary:
            request, report = Path(temporary) / 'request.json', Path(temporary) / 'report.json'
            request.write_text(json.dumps(dict(microphone_name='AM310', speaker_name='Q serial', delay_ms=40)), encoding='utf-8')
            report.with_suffix('.cancel').write_text('cancel', encoding='utf-8')
            with patch('calibration.read_probe', return_value=np.zeros(48000 * 20)), patch('calibration.pa.PyAudio') as audio:
                result = run_worker(request, report)
                audio.assert_not_called()
            self.assertEqual(result['state'], 'cancelled')
            self.assertFalse(result['audio_saved'])
            self.assertEqual(set(p.name for p in Path(temporary).iterdir()), {'request.json', 'report.json', 'report.cancel'})

    def test_unwritable_final_report_returns_error_without_opening_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            request, report = Path(temporary) / 'request.json', Path(temporary) / 'report.json'
            request.write_text(json.dumps(dict(microphone_name='AM310', speaker_name='Q serial', delay_ms=40)), encoding='utf-8')
            report.with_suffix('.cancel').write_text('cancel', encoding='utf-8')
            with patch('calibration.read_probe', return_value=np.zeros(48000 * 20)), \
                 patch('calibration.pa.PyAudio') as audio, \
                 patch('calibration.write_json', side_effect=PermissionError('report locked')), \
                 patch('calibration.LOG.exception') as log:
                result = run_worker(request, report)
            self.assertEqual(result['state'], 'error')
            self.assertFalse(result['audio_saved'])
            audio.assert_not_called()
            log.assert_called_once()


if __name__ == '__main__':
    unittest.main()
