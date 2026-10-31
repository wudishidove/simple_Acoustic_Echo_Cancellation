import queue
import unittest
from unittest.mock import patch
import uuid
import winreg

import desktop


class DesktopTests(unittest.TestCase):
    def test_startup_register_and_remove_only_our_value(self):
        key_path = 'Software\\EchoMicTests_' + uuid.uuid4().hex
        with patch.object(desktop, 'RUN_KEY', key_path), patch.object(desktop, 'startup_command', return_value='"C:\\程式 資料\\EchoMic.exe" --startup'):
            try:
                self.assertFalse(desktop.startup_enabled())
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, 'OtherApp', 0, winreg.REG_SZ, 'keep')
                desktop.set_startup(True)
                self.assertTrue(desktop.startup_enabled())
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    value, kind = winreg.QueryValueEx(key, desktop.RUN_NAME)
                    self.assertEqual(value, '"C:\\程式 資料\\EchoMic.exe" --startup')
                    self.assertEqual(kind, winreg.REG_SZ)
                desktop.set_startup(False)
                desktop.set_startup(False)
                self.assertFalse(desktop.startup_enabled())
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    self.assertEqual(winreg.QueryValueEx(key, 'OtherApp')[0], 'keep')
            finally:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)

    def test_packaged_startup_command_quotes_path_and_uses_startup_flag(self):
        with patch.object(desktop.sys, 'frozen', True, create=True), patch.object(desktop.sys, 'executable', r'D:\程式 資料\EchoMic.exe'):
            self.assertEqual(desktop.startup_command(), '"D:\\程式 資料\\EchoMic.exe" --startup')

    def test_source_startup_uses_windowless_python_and_absolute_script(self):
        command = desktop.startup_command()
        self.assertIn('pythonw.exe', command)
        self.assertIn(str(desktop.Path(desktop.__file__).with_name('echo_mic.py').resolve()), command)
        self.assertTrue(command.endswith(' --startup'))

    def test_single_instance_reopen_signal_and_release(self):
        name = 'Local\\EchoMicTest.' + uuid.uuid4().hex
        first = desktop.SingleInstance(name)
        try:
            self.assertFalse(first.already_running)
            second = desktop.SingleInstance(name)
            try:
                self.assertTrue(second.already_running)
                second.request_show()
                self.assertTrue(first.show_requested())
                self.assertFalse(first.show_requested(), 'Show request resets after consumption')
            finally:
                second.close()
        finally:
            first.close()
        third = desktop.SingleInstance(name)
        try:
            self.assertFalse(third.already_running)
        finally:
            third.close()

    def test_native_tray_show_restore_callback_hide_and_stop(self):
        events = queue.Queue()
        tray = desktop.TrayIcon(events)
        try:
            tray.show()
            self.assertTrue(tray.icon.visible)
            tray.icon()  # Default menu action used by double-click on Windows.
            self.assertEqual(events.get_nowait(), ('show', ''))
            tray.icon.menu.items[-1](tray.icon)
            self.assertEqual(events.get_nowait(), ('quit', ''))
            tray.hide()
            self.assertFalse(tray.icon.visible)
            tray.show()
            self.assertTrue(tray.icon.visible)
        finally:
            tray.stop()


if __name__ == '__main__':
    unittest.main()
