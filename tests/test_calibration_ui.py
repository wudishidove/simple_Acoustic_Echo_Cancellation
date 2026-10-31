import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from echo_mic import App


class FakeEngine:
    def __init__(self, events):
        self.events, self.alive, self.error = events, True, None
        self.thread = self
        self.stats = dict(mic=-90, reference=-90, clean=-90)
        import threading
        self.lock = threading.Lock()

    def is_alive(self):
        return self.alive

    def stop(self):
        self.alive = False
        self.events.put(('stopped', ''))


class CalibrationUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = Path(self.temporary.name) / 'settings.json'
        self.original = json.dumps(dict(delay_ms=40, noise_suppression=False))
        self.settings.write_text(self.original, encoding='utf-8')
        def device(index, name, inputs=0, outputs=0, loop=False):
            return dict(index=index, name=name, maxInputChannels=inputs,
                        maxOutputChannels=outputs, isLoopbackDevice=loop)
        devices = [device(1, 'AM310', inputs=1), device(2, 'Q serial', outputs=2),
                   device(3, 'Q serial [Loopback]', inputs=2, loop=True),
                   device(4, 'Hi-Fi Cable Input (VB-Audio Hi-Fi Cable)', outputs=2)]
        self.patches = [patch('echo_mic.SETTINGS', self.settings),
                        patch('echo_mic.list_devices', return_value=(devices, dict(defaultInputDevice=1, defaultOutputDevice=2)))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.temporary.cleanup)
        try:
            self.app = App()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.scheduled = []
        self.app.after = lambda delay, callback: self.scheduled.append((delay, callback))
        self.launched = False
        def launch():
            self.launched = True
            self.app.calibration_report = Path(self.temporary.name) / 'calibration.json'
        self.app._launch_calibration = launch

    def pause_and_launch(self):
        self.app.engine = FakeEngine(self.app.events)
        self.app.calibrate()
        self.assertFalse(self.launched, 'Worker must wait until previous audio streams have stopped')
        self.assertFalse(self.app.engine.alive)
        self.app.poll()
        self.assertTrue(self.launched)

    def test_pause_apply_persist_and_resume(self):
        self.pause_and_launch()
        self.app._finish_calibration(dict(state='completed', message='selected 60',
            result=dict(selected_delay_ms=60, measured_path_delay_ms=51)))
        saved = json.loads(self.settings.read_text(encoding='utf-8'))
        self.assertEqual(saved['delay_ms'], 60)
        self.assertFalse(saved['noise_suppression'])
        self.assertEqual(self.app.delay.get(), 60)
        self.assertTrue(any(callback == self.app.start for _, callback in self.scheduled))
        self.assertFalse(self.app.calibrating)

    def test_late_completed_result_cannot_override_cancellation(self):
        self.pause_and_launch()
        self.app.stop()
        self.app._finish_calibration(dict(state='completed', message='selected 60',
            result=dict(selected_delay_ms=60)))
        self.assertEqual(self.settings.read_text(encoding='utf-8'), self.original)
        self.assertFalse(any(callback == self.app.start for _, callback in self.scheduled))
        self.assertEqual(self.app.delay.get(), 40)

    def test_worker_error_preserves_configuration_and_recovers_controls(self):
        self.pause_and_launch()
        self.app._finish_calibration(dict(state='error', message='device disconnected'))
        self.assertEqual(self.settings.read_text(encoding='utf-8'), self.original)
        self.assertEqual(str(self.app.calibrate_button['state']), 'normal')
        self.assertTrue(any(callback == self.app.start for _, callback in self.scheduled))

    def test_poll_reads_final_report_after_observing_worker_exit(self):
        self.pause_and_launch()
        from json_store import write_json
        write_json(self.app.calibration_report, dict(state='analyzing', message='working'))
        def complete():
            write_json(self.app.calibration_report, dict(state='completed', message='completed',
                result=dict(selected_delay_ms=60)))
            return 0
        self.app.calibration_process = Mock()
        self.app.calibration_process.poll.side_effect = complete
        self.app._poll_calibration()
        self.assertFalse(self.app.calibrating)
        self.assertEqual(self.app.delay.get(), 60)
        self.assertIsNone(self.app.calibration_process)

    def test_final_report_read_is_retried_without_discarding_result(self):
        self.pause_and_launch()
        process = self.app.calibration_process = Mock()
        process.poll.return_value = 0
        report = dict(state='completed', message='completed', result=dict(selected_delay_ms=60))
        with patch('echo_mic.read_json', side_effect=[PermissionError('file locked'), report]):
            self.app._poll_calibration()
            self.assertTrue(self.app.calibrating)
            self.assertIs(self.app.calibration_process, process)
            self.assertEqual(self.app.delay.get(), 40)
            self.app._poll_calibration()
        self.assertFalse(self.app.calibrating)
        self.assertEqual(self.app.delay.get(), 60)


if __name__ == '__main__':
    unittest.main()
