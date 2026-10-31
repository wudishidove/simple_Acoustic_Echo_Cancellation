"""Windows login startup, single-instance signalling, and notification-area icon."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys
import threading
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "EchoMic"


def startup_command():
    executable = Path(sys.executable).resolve()
    command = [str(executable)]
    if not getattr(sys, "frozen", False):
        windowless = executable.with_name("pythonw.exe")
        if windowless.exists():
            command[0] = str(windowless)
        command.append(str(Path(__file__).with_name("echo_mic.py").resolve()))
    return subprocess.list2cmdline(command + ["--startup"])


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def set_startup(enabled):
    """Only edit this app's entry, for the current user; no elevation needed."""
    if enabled:
        command = startup_command()
        if len(command) > 260:
            raise ValueError("程式路徑過長，請將 EchoMic 移到較短的路徑後重試。")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass


class SingleInstance:
    """Keep one audio engine per login session; reopening asks it to show its UI."""
    def __init__(self, name=r"Local\EchoMic.Desktop.v1"):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.restype = wintypes.HANDLE
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.SetEvent.argtypes = [wintypes.HANDLE]
        self.api.SetEvent.restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.event = self.api.CreateEventW(None, False, False, name + ".Show")
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        self.mutex = self.api.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not self.mutex:
            self.close()
            raise ctypes.WinError(error)
        self.already_running = error == 183  # ERROR_ALREADY_EXISTS

    def request_show(self):
        if not self.api.SetEvent(self.event):
            raise ctypes.WinError(ctypes.get_last_error())

    def show_requested(self):
        return self.api.WaitForSingleObject(self.event, 0) == 0

    def close(self):
        for attribute in ("event", "mutex"):
            handle = getattr(self, attribute, None)
            if handle:
                self.api.CloseHandle(handle)
                setattr(self, attribute, None)


class TrayIcon:
    def __init__(self, events):
        # Import lazily so normal UI / command-line diagnostics don't create an icon.
        import pystray
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill="#101827")
        draw.rounded_rectangle((24, 10, 40, 37), radius=8, fill="#45d6b0")
        draw.arc((17, 22, 47, 47), 0, 180, fill="#e5edf8", width=4)
        draw.line((32, 47, 32, 54), fill="#e5edf8", width=4)
        draw.line((23, 55, 41, 55), fill="#e5edf8", width=4)
        self.ready = threading.Event()
        self.error = None
        self.icon = pystray.Icon("EchoMic", image, "Echo Mic｜回音消除麥克風", menu=pystray.Menu(
            pystray.MenuItem("開啟 Echo Mic", lambda icon, item: events.put(("show", "")), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("結束 Echo Mic", lambda icon, item: events.put(("quit", "")))))
        self.icon.run_detached(setup=self._setup)

    def _setup(self, icon):
        try:
            icon.visible = True
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()

    def show(self):
        if not self.ready.wait(3):
            raise RuntimeError("系統匣圖示未能啟動，視窗將保持開啟。")
        if self.error:
            raise self.error
        self.icon.visible = True

    def hide(self):
        self.icon.visible = False

    def stop(self):
        self.icon.stop()
