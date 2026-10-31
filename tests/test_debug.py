import unittest
import numpy as np
from debug_monitor import analyze_window, ANALYSIS_RATE


class DiagnosticTests(unittest.TestCase):
    def test_silence_does_not_claim_echo_suppression(self):
        data = np.zeros((ANALYSIS_RATE * 3, 5), dtype=np.float32)
        result = analyze_window(data, ['aec_only_40', 'current_aec_plus_ns'])
        self.assertEqual(result['assessment'], 'insufficient_speaker_reference')
        self.assertNotIn('estimated_correlated_echo_reduction_db', result)

    def test_correlated_reduction_excludes_unrelated_near_end_signal(self):
        rng = np.random.default_rng(42)
        n = ANALYSIS_RATE * 10
        reference = rng.normal(0, .15, n)
        near_end = rng.normal(0, .015, n)
        echo = np.roll(reference, 320)
        raw = .5 * echo + near_end
        clean = .05 * echo + near_end
        data = np.column_stack([raw, reference, reference, clean, clean])
        result = analyze_window(data, ['aec_only_40', 'current_aec_plus_ns'])
        self.assertEqual(result['assessment'], 'echo_estimate_available')
        self.assertAlmostEqual(result['estimated_echo_lag_ms'], 40, delta=.25)
        self.assertAlmostEqual(result['estimated_correlated_echo_reduction_db']['aec_only_40'], 20, delta=2)


if __name__ == '__main__':
    unittest.main()
