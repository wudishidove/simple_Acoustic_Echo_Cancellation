import json
import unittest
from unittest.mock import Mock, patch

import test_calibration_ui as calibration_ui
from test_calibration_ui import FakeEngine


class DesktopUiTests(unittest.TestCase):
    setUp = calibration_ui.CalibrationUiTests.setUp

    def test_compact_window_keeps_transport_visible_and_settings_scrollable(self):
        self.app.deiconify()
        px = self.app.display.px
        self.app.geometry(f'{px(860)}x{px(580)}')
        self.app.update()
        for tab in range(3):
            self.app.notebook.select(tab)
            self.app.update()
            self.assertTrue(self.app.start_button.winfo_ismapped())
            self.assertTrue(self.app.stop_button.winfo_ismapped())
            self.assertLessEqual(self.app.footer.winfo_y() + self.app.footer.winfo_height(),
                                 self.app.winfo_height())
            self.assertLessEqual(self.app.start_button.winfo_rootx() + self.app.start_button.winfo_width(),
                                 self.app.winfo_rootx() + self.app.winfo_width())
        self.app.notebook.select(0)
        # Several HDMI / USB endpoints should scroll rather than push the footer off screen.
        from tkinter import ttk
        for index in range(15):
            ttk.Checkbutton(self.app.speakers_frame, text=f'HDMI audio endpoint {index}').pack(anchor='w')
        self.app.update()
        page = self.app.settings_pages[0]
        self.assertTrue(page.bar.winfo_ismapped())
        page.canvas.yview_moveto(1)
        self.app.update()
        self.assertGreater(page.canvas.yview()[0], 0)
        bottom = self.app.install_button.winfo_rooty() + self.app.install_button.winfo_height()
        self.assertLessEqual(bottom, page.canvas.winfo_rooty() + page.canvas.winfo_height())

    def test_dpi_changes_preserve_settings_and_keep_layout_inside_window(self):
        from tkinter import ttk
        from display import dpi_awareness
        self.assertEqual(dpi_awareness(), 2)
        self.app.deiconify()
        self.app.delay.set(70)
        self.app.gain.set(1.4)
        original_mic = self.app.mic_combo.current()
        self.app.engine = FakeEngine(self.app.events)
        errors = []
        self.app.report_callback_exception = lambda *error: errors.append(error)
        for dpi in (96, 120, 144, 192, 240, 96, 240):
            with self.subTest(dpi=dpi), patch('display.window_dpi', return_value=dpi):
                self.app.display.check_monitor()
                self.app.update()
                px = self.app.display.px
                self.assertAlmostEqual(self.app.display.scale, dpi / 96)
                padding = ttk.Style(self.app).lookup('Primary.TButton', 'padding')
                self.assertEqual(int(self.app.tk.splitlist(padding)[0]), px(14))
                for index in range(3):
                    self.app.notebook.select(index)
                    self.app.update()
                    self.assertTrue(self.app.start_button.winfo_ismapped())
                    self.assertLessEqual(self.app.footer.winfo_y() + self.app.footer.winfo_height(),
                                         self.app.winfo_height())
                    right = self.app.stop_button.winfo_rootx() + self.app.stop_button.winfo_width()
                    self.assertLessEqual(right, self.app.winfo_rootx() + self.app.winfo_width())
                self.assertEqual(self.app.delay.get(), 70)
                self.assertEqual(self.app.gain.get(), 1.4)
                self.assertEqual(self.app.mic_combo.current(), original_mic)
                self.assertTrue(self.app.engine.alive)
        self.assertEqual(errors, [])

    def test_missing_devices_show_setup_instead_of_blank_speaker_panel(self):
        with patch('echo_mic.list_devices', return_value=([], dict(defaultInputDevice=-1, defaultOutputDevice=-1))):
            self.app.refresh()
        self.assertEqual(self.app.mic_combo.current(), -1)
        self.assertEqual(self.app.out_combo.current(), -1)
        self.assertEqual(self.app.speaker_vars, [])
        self.assertTrue(self.app.speakers_frame.winfo_children())
        self.assertIn('安裝', self.app.status['text'])

    def test_startup_button_toggles_actual_windows_setting(self):
        with patch('echo_mic.startup_enabled', side_effect=[False, True, True, False]), patch('echo_mic.set_startup') as setter:
            self.app.toggle_startup()
            setter.assert_called_with(True)
            self.assertIn('已開啟', self.app.startup_button['text'])
            self.app.toggle_startup()
            setter.assert_called_with(False)
            self.assertIn('已關閉', self.app.startup_button['text'])

    def test_tray_preserves_running_audio_and_restores_window(self):
        engine = self.app.engine = FakeEngine(self.app.events)
        self.assertTrue(self.app.minimize_on_close.get(), 'Close to tray is enabled by default')
        with patch('echo_mic.TrayIcon') as factory:
            self.assertTrue(self.app.on_window_close())
            self.assertTrue(engine.alive)
            self.assertFalse(self.app.closing)
            self.assertEqual(self.app.state(), 'withdrawn')
            self.app.events.put(('show', ''))
            self.app.poll()
            self.assertEqual(self.app.state(), 'normal')
            factory.return_value.hide.assert_called_once()
            self.assertTrue(engine.alive)

    def test_tray_failure_keeps_window_available(self):
        with patch('echo_mic.TrayIcon', side_effect=OSError('tray unavailable')), patch('echo_mic.LOG.exception'), patch('echo_mic.messagebox.showerror') as error:
            self.assertFalse(self.app.on_window_close())
            self.assertEqual(self.app.state(), 'normal')
            self.assertFalse(self.app.closing)
            error.assert_called_once()

    def test_close_unchecked_stops_audio_and_exits(self):
        self.app.minimize_on_close.set(False)
        self.app.engine = FakeEngine(self.app.events)
        with patch.object(self.app, 'destroy') as destroy, patch('echo_mic.TrayIcon') as tray:
            self.app.on_window_close()
            self.app.poll()
            self.assertFalse(self.app.engine.alive)
            self.assertTrue(self.app.closing)
            destroy.assert_called_once()
            tray.assert_not_called()

    def test_close_to_tray_preserves_calibration_and_pending_start(self):
        self.app.calibrating = True
        self.app.startup_pending = True
        with patch('echo_mic.TrayIcon'):
            self.app.on_window_close()
        self.assertTrue(self.app.calibrating)
        self.assertFalse(self.app.calibration_cancelled)
        self.assertTrue(self.app.startup_pending)

    def test_close_preference_saved_and_restored_without_changing_audio_settings(self):
        self.app.close_behavior_check.invoke()
        saved = json.loads(self.settings.read_text(encoding='utf-8'))
        self.assertFalse(saved['minimize_on_close'])
        self.assertEqual(saved['delay_ms'], 40)
        self.assertFalse(saved['noise_suppression'])
        restored = calibration_ui.App()
        try:
            self.assertFalse(restored.minimize_on_close.get())
        finally:
            restored.destroy()
        self.app.close_behavior_check.invoke()
        self.assertTrue(json.loads(self.settings.read_text(encoding='utf-8'))['minimize_on_close'])

    def test_failed_preference_save_restores_previous_selection(self):
        with patch('echo_mic.write_json', side_effect=OSError('read only')), patch('echo_mic.messagebox.showerror') as error:
            self.app.close_behavior_check.invoke()
        self.assertTrue(self.app.minimize_on_close.get())
        self.assertEqual(self.settings.read_text(encoding='utf-8'), self.original)
        error.assert_called_once()

    def test_startup_waits_for_saved_devices_then_starts(self):
        self.app.startup_pending = True
        with patch.object(self.app, 'start') as start:
            self.app._startup_attempt()
            start.assert_not_called()
            self.assertTrue(self.app.startup_pending)
            self.app.saved.update(microphone_name='AM310', output_name='Hi-Fi Cable Input (VB-Audio Hi-Fi Cable)',
                                  speaker_names=['Q serial [Loopback]'])
            self.app._startup_attempt()
            start.assert_called_once()
            self.assertFalse(self.app.startup_pending)

    def test_missing_original_device_never_uses_fallback(self):
        self.app.startup_pending = True
        self.app.startup_attempts = 19
        self.app.saved.update(microphone_name='Missing USB mic', output_name='Hi-Fi Cable Input (VB-Audio Hi-Fi Cable)',
                              speaker_names=['Q serial [Loopback]'])
        with patch.object(self.app, 'start') as start:
            self.app._startup_attempt()
            start.assert_not_called()
            self.assertFalse(self.app.startup_pending)
            self.assertEqual(self.app.state(), 'normal')

    def test_user_stop_cancels_pending_login_start(self):
        self.app.startup_pending = True
        self.app.stop()
        with patch.object(self.app, 'refresh') as refresh:
            self.app._startup_attempt()
            refresh.assert_not_called()

    def test_tray_quit_stops_audio_and_destroys_icon(self):
        self.assertTrue(self.app.minimize_on_close.get())
        self.app.engine = FakeEngine(self.app.events)
        tray = self.app.tray = Mock()
        self.app.events.put(('quit', ''))
        with patch.object(self.app, 'destroy') as destroy:
            self.app.poll()
            self.assertTrue(self.app.closing)
            self.assertFalse(self.app.engine.alive)
            destroy.assert_called_once()
