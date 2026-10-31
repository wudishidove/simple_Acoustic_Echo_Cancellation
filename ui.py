"""Standard-library desktop presentation; bundled with the portable application."""
from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from display import DpiLayout

BG = "#f3f5f8"
INK = "#172b3a"
MUTED = "#637586"
ACCENT = "#087f72"
FONT = "Microsoft JhengHei UI"


class ScrollPage(ttk.Frame):
    """Keep settings reachable on small displays and at larger Windows font sizes."""

    def __init__(self, parent):
        super().__init__(parent, style="Card.TFrame")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.content = ttk.Frame(self.canvas, padding=(22, 20), style="Card.TFrame")
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._resize)

    def _resize(self, event=None):
        self.canvas.itemconfigure(self.item, width=self.canvas.winfo_width())
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.bar.grid(row=0, column=1, sticky="ns")
        else:
            self.bar.grid_remove()
            self.canvas.yview_moveto(0)
        px = getattr(self.winfo_toplevel(), 'display', None)
        unit = px.px if px else round
        width = max(unit(140), self.canvas.winfo_width() - unit(48))
        for label in self._labels(self.content):
            if isinstance(label, ttk.Checkbutton):
                name = f"Wrap{self.winfo_id()}.TCheckbutton"
                ttk.Style(self).configure(name, wraplength=max(unit(100), width - unit(24)))
                label.configure(style=name)
            elif label.cget("wraplength"):
                label.configure(wraplength=width)

    @staticmethod
    def _labels(parent):
        for child in parent.winfo_children():
            if isinstance(child, (ttk.Label, ttk.Checkbutton)):
                yield child
            yield from ScrollPage._labels(child)


def configure_styles(app):
    style = ttk.Style(app)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 10), background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background="white")
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Card.TLabel", background="white")
    style.configure("Title.TLabel", font=(FONT, 23, "bold"))
    style.configure("Eyebrow.TLabel", foreground=ACCENT, font=(FONT, 9, "bold"))
    style.configure("Hint.TLabel", foreground=MUTED)
    style.configure("CardHint.TLabel", background="white", foreground=MUTED, font=(FONT, 9))
    style.configure("Section.TLabel", background="white", font=(FONT, 12, "bold"))
    style.configure("Step.TLabel", background="#e6f4f0", foreground=ACCENT, padding=(8, 4), font=(FONT, 10, "bold"))
    style.configure("TButton", background="white", foreground=INK, bordercolor="#d7e0e6",
                    lightcolor="white", darkcolor="white", padding=(14, 9), borderwidth=1)
    style.map("TButton", background=[("active", "#edf3f5"), ("disabled", "#f1f3f5")],
              foreground=[("disabled", "#99a6b1")])
    style.configure("Primary.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, font=(FONT, 11, "bold"))
    style.map("Primary.TButton", background=[("disabled", "#dce7e4"), ("active", "#06685e")],
              foreground=[("disabled", "#8caaa3")], bordercolor=[("disabled", "#dce7e4")])
    style.configure("TCheckbutton", background="white", foreground=INK, padding=(0, 5),
                    indicatorsize=13, indicatormargin=(0, 0, 4, 0))
    style.map("TCheckbutton", background=[("active", "#f0f7f5")], foreground=[("disabled", "#99a6b1")])
    for name in ("TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground="white", background="#edf2f5", foreground=INK,
                        bordercolor="#d7e0e6", arrowcolor=MUTED, padding=8, arrowsize=14)
        style.map(name, fieldbackground=[("readonly", "white"), ("disabled", "#f1f3f5")],
                  foreground=[("disabled", "#99a6b1")])
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TScrollbar", background="#d5dfe5", troughcolor="#f2f5f7",
                    bordercolor="#f2f5f7", lightcolor="#d5dfe5", darkcolor="#d5dfe5",
                    arrowcolor=MUTED, gripcount=0, arrowsize=14)
    style.map("TScrollbar", background=[("active", "#b4c6d1"), ("pressed", "#9eb4c2")])
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 11), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", "white"), ("active", "#e8eef2")],
              foreground=[("selected", ACCENT)], padding=[("selected", (18, 11))],
              lightcolor=[("selected", "white")], expand=[("selected", (0, 0, 0, 0))])
    style.configure("Monitor.TFrame", background="#172e3b")
    style.configure("Monitor.TLabel", background="#172e3b", foreground="#f1f7fa")
    style.configure("MonitorHint.TLabel", background="#172e3b", foreground="#a9bfca", font=(FONT, 9))
    style.configure("MonitorTitle.TLabel", background="#172e3b", foreground="white", font=(FONT, 12, "bold"))
    style.configure("Meter.Horizontal.TProgressbar", troughcolor="#2c4553", background="#5bd7b6",
                    borderwidth=0, lightcolor="#5bd7b6", darkcolor="#5bd7b6", thickness=7)
    style.configure("Badge.TLabel", background="#e4f1ec", foreground=ACCENT, padding=(12, 7), font=(FONT, 9, "bold"))
    style.configure("Footer.TFrame", background="white")
    style.configure("Footer.TLabel", background="white", font=(FONT, 9), foreground=MUTED)
    app.option_add("*TCombobox*Listbox.font", (FONT, 10))
    app.option_add("*TCombobox*Listbox.background", "white")
    app.option_add("*TCombobox*Listbox.foreground", INK)


def section(parent, number, title, hint):
    header = ttk.Frame(parent, style="Card.TFrame")
    header.pack(fill="x")
    ttk.Label(header, text=number, style="Step.TLabel").pack(side="left", padx=(0, 10))
    ttk.Label(header, text=title, style="Section.TLabel").pack(side="left")
    ttk.Label(parent, text=hint, style="CardHint.TLabel", wraplength=440,
              justify="left").pack(fill="x", pady=(7, 10))


def build_ui(app, default_delay):
    configure_styles(app)
    app.configure(bg=BG)
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "EchoMic.ico"
    if icon.exists():
        app.iconbitmap(default=str(icon))
    app.columnconfigure(0, weight=1)
    app.rowconfigure(1, weight=1)

    header = ttk.Frame(app, padding=(26, 18, 26, 16))
    header.grid(row=0, column=0, sticky="ew")
    logo = tk.Canvas(header, width=48, height=48, bg=BG, highlightthickness=0)
    logo.pack(side="left", padx=(0, 14))
    logo.create_oval(0, 0, 47, 47, fill=ACCENT, outline=ACCENT)
    logo.create_line(24, 14, 24, 27, fill="white", width=8, capstyle="round")
    logo.create_arc(14, 17, 34, 35, start=180, extent=180, outline="white", width=2, style="arc")
    logo.create_line(24, 35, 24, 39, fill="white", width=2)
    logo.create_line(19, 39, 29, 39, fill="white", width=2)
    brand = ttk.Frame(header)
    brand.pack(side="left")
    ttk.Label(brand, text="Echo Mic", style="Title.TLabel").pack(anchor="w")
    ttk.Label(brand, text="讓對話清楚，讓回音安靜。", style="Hint.TLabel").pack(anchor="w")
    app.activity = ttk.Label(header, text="●  尚未啟動", style="Badge.TLabel")
    app.activity.pack(side="right")

    body = ttk.Frame(app, padding=(26, 0, 26, 18))
    body.grid(row=1, column=0, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=0, minsize=274)
    body.rowconfigure(0, weight=1)
    app.notebook = ttk.Notebook(body)
    app.notebook.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
    pages = [ScrollPage(app.notebook) for _ in range(3)]
    for page, title in zip(pages, ("音訊裝置", "音效與校正", "一般設定")):
        app.notebook.add(page, text=title)
    app.settings_pages = pages
    devices, tuning, preferences = [page.content for page in pages]

    section(devices, "01", "你的麥克風", "選擇收錄你說話聲音的實體麥克風。")
    app.mic_combo = ttk.Combobox(devices, state="readonly", width=24)
    app.mic_combo.pack(fill="x", pady=(0, 20))
    section(devices, "02", "正在發聲的喇叭", "勾選需要消除回音的喇叭，可複選。")
    app.speakers_frame = ttk.Frame(devices, style="Card.TFrame")
    app.speakers_frame.pack(fill="x", pady=(0, 20))
    section(devices, "03", "處理後的輸出", "將清晰人聲送至獨立的虛擬音訊裝置。")
    app.out_combo = ttk.Combobox(devices, state="readonly", width=24)
    app.out_combo.pack(fill="x", pady=(0, 14))
    actions = ttk.Frame(devices, style="Card.TFrame")
    actions.pack(fill="x")
    app.refresh_button = ttk.Button(actions, text="重新整理裝置", command=app.refresh)
    app.refresh_button.pack(side="left", padx=(0, 8))
    app.install_button = ttk.Button(actions, text="安裝虛擬裝置…", command=app.install_driver)
    app.install_button.pack(side="left")
    ttk.Label(devices, text="首次使用：安裝虛擬裝置後，再重新整理清單。",
              style="CardHint.TLabel", wraplength=440).pack(fill="x", pady=(12, 0))

    section(tuning, "AEC", "音效調整", "先使用預設值，再依使用環境微調；變更將於下次啟動時生效。")
    app.delay = tk.IntVar(value=app.saved.get("delay_ms", default_delay))
    app.gain = tk.DoubleVar(value=app.saved.get("gain", 1.0))
    app.ns = tk.BooleanVar(value=app.saved.get("noise_suppression", True))
    app.advanced = ttk.Frame(tuning, style="Card.TFrame")
    app.advanced.pack(fill="x", pady=(4, 20))
    app.advanced.columnconfigure(0, weight=1)
    ttk.Label(app.advanced, text="回音延遲  /  ms", style="Card.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(app.advanced, from_=0, to=500, increment=10, textvariable=app.delay, width=7).grid(row=0, column=1, pady=6)
    ttk.Label(app.advanced, text="麥克風音量  /  倍", style="Card.TLabel").grid(row=1, column=0, sticky="w")
    ttk.Spinbox(app.advanced, from_=0.1, to=3, increment=.1, textvariable=app.gain, width=7).grid(row=1, column=1, pady=6)
    ttk.Checkbutton(app.advanced, text="啟用背景降噪", variable=app.ns).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Separator(tuning).pack(fill="x", pady=(0, 20))
    ttk.Label(tuning, text="找到適合房間的延遲", style="Section.TLabel").pack(anchor="w")
    app.calibration_hint = ttk.Label(tuning, text="預設 40 ms。校正會暫停輸出，並播放約 20 秒測試語音。請保持安靜，不要調整喇叭音量。",
        style="CardHint.TLabel", wraplength=440, justify="left")
    app.calibration_hint.pack(fill="x", pady=(10, 14))
    previous = app.saved.get("calibration", {}).get("result", {})
    if previous.get("measured_path_delay_ms") is not None:
        app.calibration_hint["text"] = (f"目前 AEC 設定：{app.delay.get()} ms；最近測得訊號偏移：{previous['measured_path_delay_ms']:g} ms（非套用值）。\n"
            "校正會暫停輸出並播放約 20 秒語音，請保持安靜、不調整喇叭音量。")
    app.calibrate_button = ttk.Button(tuning, text="校正延遲（約 25 秒）", command=app.calibrate)
    app.calibrate_button.pack(anchor="w")
    ttk.Label(tuning, text="校正前，請在「音訊裝置」只勾選一個實體喇叭。",
              style="CardHint.TLabel", wraplength=440).pack(fill="x", pady=(12, 0))

    section(preferences, "APP", "日常使用", "設定 Windows 登入後的啟動方式與視窗關閉行為。")
    app.startup_button = ttk.Button(preferences, command=app.toggle_startup)
    app.startup_button.pack(anchor="w", pady=(2, 12))
    ttk.Label(preferences, text="開啟後，登入 Windows 時會在系統匣使用上次儲存的音訊設定啟動。",
              style="CardHint.TLabel", wraplength=440).pack(fill="x", pady=(0, 16))
    app.minimize_on_close = tk.BooleanVar(value=app.saved.get("minimize_on_close", True))
    app.close_behavior_check = ttk.Checkbutton(preferences, text="關閉視窗時，縮到系統匣繼續運作",
        variable=app.minimize_on_close, command=app.save_close_behavior)
    app.close_behavior_check.pack(anchor="w")
    ttk.Label(preferences, text="從系統匣圖示可重新開啟視窗或結束程式。停止或結束程式後，虛擬麥克風將不再收到音訊。",
              style="CardHint.TLabel", wraplength=440).pack(fill="x", pady=(8, 22))
    ttk.Separator(preferences).pack(fill="x", pady=(0, 20))
    ttk.Label(preferences, text="音訊留在你的電腦", style="Section.TLabel").pack(anchor="w")
    ttk.Label(preferences, text="音訊只在本機記憶體處理，不儲存錄音，也不上傳。",
              style="CardHint.TLabel", wraplength=440).pack(fill="x", pady=(8, 0))
    app.update_startup_button()

    app.monitor_page = ScrollPage(body)
    app.monitor_page.canvas.configure(bg=BG, width=274)
    app.monitor_page.content.configure(style="TFrame", padding=0)
    app.monitor_page.grid(row=0, column=1, sticky="nsew", pady=(42, 0))
    sidebar = app.monitor_page.content
    sidebar.columnconfigure(0, weight=1)
    monitor = ttk.Frame(sidebar, style="Monitor.TFrame", padding=20)
    monitor.grid(row=0, column=0, sticky="ew")
    ttk.Label(monitor, text="即時音量", style="MonitorTitle.TLabel").pack(anchor="w")
    ttk.Label(monitor, text="48 kHz  /  WebRTC AEC", style="MonitorHint.TLabel").pack(anchor="w", pady=(3, 14))
    app.meters = {}
    for key, label in (("mic", "原始麥克風"), ("reference", "喇叭參考"), ("clean", "處理後輸出")):
        row = ttk.Frame(monitor, style="Monitor.TFrame")
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=label, style="Monitor.TLabel").pack(side="left")
        number = ttk.Label(row, text="−∞ dB", style="MonitorHint.TLabel", width=8, anchor="e")
        number.pack(side="right")
        meter = ttk.Progressbar(monitor, style="Meter.Horizontal.TProgressbar", maximum=60)
        meter.pack(fill="x", pady=(0, 14))
        app.meters[key] = meter, number
    guide = ttk.Frame(sidebar, style="Card.TFrame", padding=18)
    guide.grid(row=1, column=0, sticky="ew", pady=(14, 0))
    ttk.Label(guide, text="接著，在通話軟體…", style="Section.TLabel").pack(anchor="w")
    ttk.Label(guide, text="Discord、OBS 或遊戲的\n麥克風請選擇", style="CardHint.TLabel").pack(anchor="w", pady=(8, 6))
    ttk.Label(guide, text="Hi-Fi Cable Output", style="Section.TLabel").pack(anchor="w")
    ttk.Label(guide, text="VB-Audio Hi-Fi Cable", style="CardHint.TLabel").pack(anchor="w", pady=(2, 0))

    app.footer = ttk.Frame(app, style="Footer.TFrame", padding=(26, 15))
    app.footer.grid(row=2, column=0, sticky="ew")
    app.footer.columnconfigure(0, weight=1)
    app.footer.columnconfigure(1, weight=0)
    app.status = ttk.Label(app.footer, text="準備中", style="Card.TLabel", wraplength=530)
    app.status.grid(row=0, column=0, sticky="w")
    app.destination = ttk.Label(app.footer, text="", style="Footer.TLabel", wraplength=530)
    app.destination.grid(row=1, column=0, sticky="w", pady=(5, 0))
    buttons = ttk.Frame(app.footer, style="Footer.TFrame")
    buttons.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))
    app.start_button = ttk.Button(buttons, text="啟動回音消除", style="Primary.TButton", command=app.start)
    app.start_button.pack(side="left")
    app.stop_button = ttk.Button(buttons, text="停止", command=app.stop, state="disabled", width=8)
    app.stop_button.pack(side="left", padx=(8, 0))

    def resize_footer(event):
        px = app.display.px
        available = max(px(220), event.width - buttons.winfo_reqwidth() - px(76))
        app.status.configure(wraplength=available)
        app.destination.configure(wraplength=available)
    app.footer.bind("<Configure>", resize_footer)

    def mousewheel(event):
        widget = event.widget
        while widget is not None:
            if isinstance(widget, ScrollPage):
                if widget.bar.winfo_ismapped():
                    widget.canvas.yview_scroll(-int(event.delta / 120), "units")
                return
            widget = getattr(widget, "master", None)
    # Attach to this toplevel rather than bind_all, so destroyed test windows leave no callbacks.
    app.bind("<MouseWheel>", mousewheel, add="+")
    app.display = DpiLayout(app)


def update_activity(app):
    running = bool(app.engine and app.engine.thread.is_alive())
    if app.calibrating:
        text, background, foreground = "●  校正中", "#fff1d6", "#94631b"
    elif running:
        text, background, foreground = "●  回音消除中", "#ddf4eb", ACCENT
    else:
        text, background, foreground = "●  尚未啟動", "#e7ecf0", MUTED
    app.activity.configure(text=text, background=background, foreground=foreground)
