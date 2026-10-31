"""Native Windows DPI awareness and pixel metrics for the Tk 8.6 desktop UI."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk


def enable_high_dpi():
    """Call before creating Tk; the packaged EXE also declares this in its manifest."""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = wintypes.BOOL
        if setter(ctypes.c_void_p(-4)) or user32.IsProcessDPIAware():
            return
    except AttributeError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def window_dpi(window):
    try:
        getter = ctypes.windll.user32.GetDpiForWindow
        getter.argtypes = [wintypes.HWND]
        getter.restype = wintypes.UINT
        dpi = getter(window.winfo_id())
        if dpi:
            return dpi
    except AttributeError:
        pass
    return round(window.winfo_fpixels('1i'))


def dpi_awareness():
    value = ctypes.c_int()
    ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(value))
    return value.value


def work_area(window):
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    api = ctypes.windll.user32
    api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    api.MonitorFromWindow.restype = wintypes.HANDLE
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
    monitor = api.MonitorFromWindow(window.winfo_id(), 2)
    if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return info.work.right - info.work.left, info.work.bottom - info.work.top
    return window.winfo_screenwidth(), window.winfo_screenheight()


class DpiLayout:
    """Scale pixel distances as well as fonts, including after a monitor change.

    Tk 8.6 scales point fonts but does not scale pack/grid padding or canvas
    coordinates. Retain their original 96-DPI values so repeated changes never
    compound rounding errors. Widget values and audio state remain untouched.
    """

    STYLE_NAMES = ('.', 'Title.TLabel', 'CardHint.TLabel', 'Section.TLabel',
                   'Step.TLabel', 'TButton', 'Primary.TButton', 'TCheckbutton',
                   'TCombobox', 'TSpinbox', 'TNotebook', 'TNotebook.Tab',
                   'TScrollbar', 'MonitorHint.TLabel', 'MonitorTitle.TLabel',
                   'Meter.Horizontal.TProgressbar', 'Badge.TLabel', 'Footer.TLabel')

    def __init__(self, app):
        self.app = app
        self.scale = 1.0
        app.display = self
        self.widgets = {}
        self.applying = False
        style = ttk.Style(app)
        self.styles = {}
        for name in self.STYLE_NAMES:
            options = style.configure(name) or {}
            self.styles[name] = {key: value for key, value in options.items()
                                 if key in ('padding', 'borderwidth', 'thickness', 'arrowsize',
                                            'indicatorsize', 'indicatormargin', 'font')}
        self.tab_padding = style.map('TNotebook.Tab', 'padding')
        self.capture(app)
        self.apply(window_dpi(app) / 96)
        app.bind('<Configure>', self.on_configure, add='+')
        self.app.after(500, self.check_monitor)

    def px(self, value):
        return round(value * self.scale)

    def distances(self, value, scale):
        parts = self.app.tk.splitlist(value) if isinstance(value, str) else value
        if not isinstance(parts, (tuple, list)):
            return round(float(parts) * scale)
        return tuple(round(float(part) * scale) for part in parts)

    def capture(self, widget):
        if widget not in self.widgets:
            options = {}
            for key in ('padding', 'wraplength'):
                if key in widget.keys() and str(widget.cget(key)):
                    options[key] = self.distances(widget.cget(key), 1 / self.scale)
            if isinstance(widget, tk.Canvas):
                for key in ('width', 'height'):
                    options[key] = round(float(widget.cget(key)) / self.scale)
            manager = widget.winfo_manager()
            layout = widget.pack_info() if manager == 'pack' else widget.grid_info() if manager == 'grid' else {}
            spacing = {key: self.distances(layout[key], 1 / self.scale)
                       for key in ('padx', 'pady', 'ipadx', 'ipady') if key in layout}
            columns = {}
            if isinstance(widget, ttk.Frame):
                for column in range(widget.grid_size()[0]):
                    size = widget.grid_columnconfigure(column)['minsize']
                    if size:
                        columns[column] = round(size / self.scale)
            drawing = {}
            if isinstance(widget, tk.Canvas):
                for item in widget.find_all():
                    if widget.type(item) != 'window':
                        drawing[item] = ([v / self.scale for v in widget.coords(item)],
                                         float(widget.itemcget(item, 'width')) / self.scale)
            self.widgets[widget] = options, manager, spacing, columns, drawing
        for child in widget.winfo_children():
            self.capture(child)

    def apply(self, scale):
        if self.applying:
            return
        self.applying = True
        try:
            self.capture(self.app)
            self.scale = scale
            self.app.tk.call('tk', 'scaling', 96 * scale / 72)
            style = ttk.Style(self.app)
            for name, values in self.styles.items():
                style.configure(name, **{key: value if key == 'font' else self.distances(value, scale)
                                         for key, value in values.items()})
            style.map('TNotebook.Tab', padding=[(*entry[:-1], self.distances(entry[-1], scale))
                                                for entry in self.tab_padding])
            for widget, (options, manager, spacing, columns, drawing) in list(self.widgets.items()):
                if not widget.winfo_exists():
                    del self.widgets[widget]
                    continue
                widget.configure(**{key: self.distances(value, scale) for key, value in options.items()})
                if spacing:
                    setter = widget.pack_configure if manager == 'pack' else widget.grid_configure
                    setter(**{key: self.distances(value, scale) for key, value in spacing.items()})
                for column, size in columns.items():
                    widget.grid_columnconfigure(column, minsize=self.px(size))
                for item, (coords, width) in drawing.items():
                    widget.coords(item, *[v * scale for v in coords])
                    widget.itemconfigure(item, width=max(1, width * scale))
            self.resize_window()
        finally:
            self.applying = False

    def resize_window(self):
        available_width, available_height = work_area(self.app)
        width = min(self.px(1060), available_width - self.px(40))
        height = min(self.px(740), available_height - self.px(60))
        self.app.minsize(min(self.px(860), width), min(self.px(580), height))
        self.app.geometry(f'{width}x{height}')

    def check_monitor(self):
        scale = window_dpi(self.app) / 96
        if abs(scale - self.scale) > .01:
            self.apply(scale)
        self.app.after(500, self.check_monitor)

    def on_configure(self, event):
        if event.widget is self.app and not self.applying:
            scale = window_dpi(self.app) / 96
            if abs(scale - self.scale) > .01:
                self.apply(scale)
