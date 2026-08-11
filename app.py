"""Tkinter UI tuned for HR call-in pattern tracking and prediction."""

import json
import os
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from humanPredict import (
    DurationTracker,
    HRCallInAnalyzer,
    MarkovChainPredictor,
    day_of_week_label,
    decode_state,
    entry_to_state,
    format_duration,
    is_hr_activity,
    time_of_day_bucket,
)
from pdf_export import write_text_pdf


def app_dir() -> Path:
    """Folder for logs/settings. Next to the .exe when frozen; else project folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


LOG_PATH = app_dir() / "hr_pattern_log.json"
SETTINGS_PATH = app_dir() / "hr_settings.json"
HR_ACTIVITY = "HR call-in"
PRESETS = [
    "HR call-in",
    "Manager talk",
    "Write-up",
    "Warning",
    "Deadline",
    "Meeting",
    "Complaint",
    "Normal day",
]
BEFORE_HR_CHOICES = [
    "Deadline",
    "Complaint",
    "Manager talk",
    "Write-up",
    "Warning",
    "Meeting",
    "Normal day",
    "Other / skip",
]

# Palette from stephenv.net
BG = "#000000"
PANEL = "#122040"
SURFACE = "#1b1f22"
TEXT = "#ffffff"
MUTED = "#a8b3c7"
ACCENT = "#3b82f6"
PRIMARY_BG = "#ffffff"
PRIMARY_FG = "#1b1f22"
INPUT_BG = "#0a0a0a"
WARN = "#f59e0b"
URGENT = "#ef4444"
OK_GREEN = "#22c55e"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SMALL = ("Segoe UI", 9)


class ToolTip:
    """Hover tip for explaining controls."""

    def __init__(self, widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        tk.Label(
            tw,
            text=self.text,
            justify="left",
            background=PANEL,
            foreground=TEXT,
            relief="solid",
            borderwidth=1,
            highlightbackground=ACCENT,
            highlightthickness=1,
            font=FONT_SMALL,
            padx=10,
            pady=8,
            wraplength=320,
        ).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def now_defaults() -> tuple[str, str]:
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


def normalize_entry(raw) -> dict | None:
    if isinstance(raw, str):
        activity = raw.strip()
        if not activity:
            return None
        return {
            "activity": activity,
            "started_at": None,
            "duration_min": None,
            "notes": "",
            "person": "",
            "workplace": "",
        }
    if not isinstance(raw, dict):
        return None
    activity = str(raw.get("activity", "")).strip()
    if not activity:
        return None
    duration = raw.get("duration_min")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = None
    return {
        "activity": activity,
        "started_at": raw.get("started_at"),
        "duration_min": duration,
        "notes": str(raw.get("notes") or ""),
        "person": str(raw.get("person") or ""),
        "workplace": str(raw.get("workplace") or ""),
    }


def format_entry_line(index: int, entry: dict) -> str:
    activity = entry["activity"]
    duration = format_duration(entry.get("duration_min"))
    notes = (entry.get("notes") or "").strip().replace("\n", " ")
    note_bit = ""
    if notes:
        preview = notes if len(notes) <= 28 else notes[:25] + "..."
        note_bit = f"  ·  note: {preview}"
    who = (entry.get("person") or "").strip()
    where = (entry.get("workplace") or "").strip()
    who_bit = ""
    if who or where:
        who_bit = f"  ·  {who or '?'} @ {where or '?'}"
    started_at = entry.get("started_at")
    if not started_at:
        return f"{index}. {activity}  ·  {duration}{who_bit}{note_bit}"
    try:
        dt = datetime.fromisoformat(started_at)
        when = f"{day_of_week_label(dt)} {dt.strftime('%Y-%m-%d %H:%M')}"
        bucket = time_of_day_bucket(dt.hour)
        marker = " ★" if is_hr_activity(activity) else ""
        return (
            f"{index}. {when}  ·  {activity}{marker}  ·  {duration}  ·  "
            f"{bucket}{who_bit}{note_bit}"
        )
    except (TypeError, ValueError):
        return f"{index}. {activity}  ·  {duration}{who_bit}{note_bit}"


class ActivityLoggerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HumanPredict — HR Call-In Patterns")
        self.geometry("760x980")
        self.minsize(680, 820)
        self.configure(bg=BG)

        self.entries: list[dict] = []
        self._view_indices: list[int] = []
        self._selected_index: int | None = None
        self._notes_placeholder = True
        self._reminder_job = None
        self.settings = self._load_settings()
        self.analyzer = HRCallInAnalyzer(target_activity=HR_ACTIVITY)

        self._apply_theme()
        self._build_ui()
        self._load_log()
        self._sync_day_label()
        self.refresh_estimate(show_reminder_popup=True)
        self._schedule_reminder_check()

    # --- settings ---
    def _default_settings(self) -> dict:
        return {
            "person": "",
            "workplace": "",
            "reminders_enabled": True,
            "reminder_within_days": 3,
            "last_reminder_key": "",
            "hr_only_filter": False,
        }

    def _load_settings(self) -> dict:
        data = self._default_settings()
        if SETTINGS_PATH.exists():
            try:
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return data

    def _save_settings(self):
        self.settings["person"] = self.person_var.get().strip()
        self.settings["workplace"] = self.workplace_var.get().strip()
        self.settings["reminders_enabled"] = bool(self.reminders_var.get())
        self.settings["hr_only_filter"] = bool(self.hr_only_var.get())
        try:
            SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass

    # --- theme ---
    def _apply_theme(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=TEXT, font=FONT, borderwidth=0)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=FONT)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=FONT_SMALL)
        style.configure("Result.TLabel", background=PANEL, foreground=ACCENT, font=FONT_BOLD)
        style.configure("Warn.TLabel", background=PANEL, foreground=WARN, font=FONT_BOLD)
        style.configure("Urgent.TLabel", background=PANEL, foreground=URGENT, font=FONT_BOLD)
        style.configure("Ok.TLabel", background=PANEL, foreground=OK_GREEN, font=FONT_BOLD)
        style.configure(
            "Card.TLabelframe",
            background=PANEL,
            foreground=TEXT,
            bordercolor=ACCENT,
            borderwidth=1,
            relief="solid",
            padding=8,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=PANEL,
            foreground=ACCENT,
            font=FONT_BOLD,
        )
        style.configure(
            "TEntry",
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            padding=6,
        )
        style.map("TEntry", fieldbackground=[("focus", SURFACE)], bordercolor=[("focus", ACCENT)])
        style.configure(
            "TSpinbox",
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=ACCENT,
            arrowsize=12,
            padding=4,
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("readonly", INPUT_BG), ("focus", SURFACE)],
            foreground=[("readonly", TEXT)],
            arrowcolor=[("!disabled", TEXT)],
        )
        style.configure(
            "TCheckbutton",
            background=BG,
            foreground=TEXT,
            font=FONT_SMALL,
            focuscolor=ACCENT,
        )
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure(
            "Panel.TCheckbutton",
            background=PANEL,
            foreground=TEXT,
            font=FONT_SMALL,
            focuscolor=ACCENT,
        )
        style.map("Panel.TCheckbutton", background=[("active", PANEL)])
        for name, pad in (
            ("Primary.TButton", (14, 8)),
            ("Ghost.TButton", (10, 6)),
            ("Preset.TButton", (8, 5)),
        ):
            style.configure(
                name,
                background=PRIMARY_BG if "Primary" in name else (PANEL if "Preset" in name else SURFACE),
                foreground=PRIMARY_FG if "Primary" in name else TEXT,
                font=FONT_BOLD if "Primary" in name else (FONT_SMALL if "Preset" in name else FONT),
                borderwidth=0 if "Primary" in name else 1,
                bordercolor=ACCENT,
                padding=pad,
                focuscolor=ACCENT,
            )
        style.map(
            "Primary.TButton",
            background=[("active", MUTED), ("pressed", ACCENT)],
            foreground=[("active", PRIMARY_FG), ("pressed", TEXT)],
        )
        style.map(
            "Ghost.TButton",
            background=[("active", PANEL), ("pressed", ACCENT)],
            foreground=[("active", TEXT), ("pressed", TEXT)],
        )
        style.map(
            "Preset.TButton",
            background=[("active", ACCENT), ("pressed", PRIMARY_BG)],
            foreground=[("active", TEXT), ("pressed", PRIMARY_FG)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=TEXT,
        )

    def _build_ui(self):
        pad = {"padx": 14, "pady": 6}

        # Scrollable shell for the denser UI
        shell = ttk.Frame(self, style="TFrame")
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        root = ttk.Frame(canvas, style="TFrame")
        root_id = canvas.create_window((0, 0), window=root, anchor="nw")

        def _on_frame_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(root_id, width=event.width)

        root.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _wheel)

        # Brand / help
        brand = ttk.Frame(root, style="TFrame")
        brand.pack(fill="x", **pad)
        title_row = ttk.Frame(brand, style="TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text="HumanPredict", style="Title.TLabel").pack(side="left")
        help_btn = ttk.Button(title_row, text="Help", style="Ghost.TButton", command=self.show_help)
        help_btn.pack(side="right")
        ToolTip(help_btn, "Guide to every feature in this app.")
        ttk.Label(
            brand,
            text="HR call-in tracker — hover controls for tips. Scroll for chart & notes.",
            style="Muted.TLabel",
            wraplength=700,
        ).pack(anchor="w", pady=(2, 0))

        # Profile
        profile = ttk.LabelFrame(root, text="Who / where", style="Card.TLabelframe")
        profile.pack(fill="x", **pad)
        prow = ttk.Frame(profile, style="Panel.TFrame")
        prow.pack(fill="x")
        self.person_var = tk.StringVar(value=self.settings.get("person", ""))
        self.workplace_var = tk.StringVar(value=self.settings.get("workplace", ""))
        pcol = ttk.Frame(prow, style="Panel.TFrame")
        pcol.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(pcol, text="Person", style="PanelMuted.TLabel").pack(anchor="w")
        person_entry = ttk.Entry(pcol, textvariable=self.person_var)
        person_entry.pack(fill="x", pady=(2, 0))
        ToolTip(person_entry, "Who this log is about (e.g. granddaughter’s name). Saved on each event.")
        wcol = ttk.Frame(prow, style="Panel.TFrame")
        wcol.pack(side="left", fill="x", expand=True)
        ttk.Label(wcol, text="Workplace", style="PanelMuted.TLabel").pack(anchor="w")
        work_entry = ttk.Entry(wcol, textvariable=self.workplace_var)
        work_entry.pack(fill="x", pady=(2, 0))
        ToolTip(work_entry, "Employer or location label for this pattern log.")
        person_entry.bind("<FocusOut>", lambda _e: self._save_settings())
        work_entry.bind("<FocusOut>", lambda _e: self._save_settings())

        # Log event
        add_frame = ttk.LabelFrame(root, text="Log / edit event", style="Card.TLabelframe")
        add_frame.pack(fill="x", **pad)

        date_default, time_default = now_defaults()
        self.activity_var = tk.StringVar(value=HR_ACTIVITY)
        self.date_var = tk.StringVar(value=date_default)
        self.time_var = tk.StringVar(value=time_default)
        self.duration_var = tk.IntVar(value=30)
        self.day_var = tk.StringVar(value="")

        row1 = ttk.Frame(add_frame, style="Panel.TFrame")
        row1.pack(fill="x", pady=(0, 6))
        ttk.Label(row1, text="Event", style="PanelMuted.TLabel").pack(anchor="w")
        entry = ttk.Entry(row1, textvariable=self.activity_var)
        entry.pack(fill="x", pady=(2, 0))
        ToolTip(entry, "What happened. Use HR call-in for HR department meetings.")

        row2 = ttk.Frame(add_frame, style="Panel.TFrame")
        row2.pack(fill="x", pady=(0, 6))
        date_col = ttk.Frame(row2, style="Panel.TFrame")
        date_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(date_col, text="Date (YYYY-MM-DD)", style="PanelMuted.TLabel").pack(anchor="w")
        date_entry = ttk.Entry(date_col, textvariable=self.date_var, width=14)
        date_entry.pack(fill="x", pady=(2, 0))
        date_entry.bind("<KeyRelease>", lambda _e: self._sync_day_label())
        ToolTip(date_entry, "Event date — drives gap estimates between HR call-ins.")

        time_col = ttk.Frame(row2, style="Panel.TFrame")
        time_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(time_col, text="Time (HH:MM)", style="PanelMuted.TLabel").pack(anchor="w")
        time_entry = ttk.Entry(time_col, textvariable=self.time_var, width=10)
        time_entry.pack(fill="x", pady=(2, 0))
        time_entry.bind("<KeyRelease>", lambda _e: self._sync_day_label())
        ToolTip(time_entry, "Event time (24-hour).")

        day_col = ttk.Frame(row2, style="Panel.TFrame")
        day_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(day_col, text="Day", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Label(day_col, textvariable=self.day_var, style="Panel.TLabel").pack(anchor="w", pady=(4, 0))

        dur_col = ttk.Frame(row2, style="Panel.TFrame")
        dur_col.pack(side="left", fill="x", expand=True)
        ttk.Label(dur_col, text="Duration (min)", style="PanelMuted.TLabel").pack(anchor="w")
        dur_spin = ttk.Spinbox(dur_col, from_=1, to=24 * 60, width=8, textvariable=self.duration_var)
        dur_spin.pack(fill="x", pady=(2, 0))
        ToolTip(dur_spin, "How long it lasted, in minutes.")

        notes_new = ttk.Frame(add_frame, style="Panel.TFrame")
        notes_new.pack(fill="x", pady=(0, 6))
        ttk.Label(notes_new, text="Notes for this event", style="PanelMuted.TLabel").pack(anchor="w")
        self.new_notes_text = tk.Text(
            notes_new,
            height=3,
            wrap="word",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            highlightcolor=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            relief="flat",
            padx=8,
            pady=6,
        )
        self.new_notes_text.pack(fill="x", pady=(2, 0))
        self._reset_new_notes()
        self.new_notes_text.bind("<FocusIn>", self._clear_notes_placeholder)
        ToolTip(self.new_notes_text, "Details: who called, what was said, outcome.")

        row3 = ttk.Frame(add_frame, style="Panel.TFrame")
        row3.pack(fill="x")
        use_now_btn = ttk.Button(row3, text="Use now", style="Ghost.TButton", command=self._use_now)
        use_now_btn.pack(side="left")
        ToolTip(use_now_btn, "Fill date/time with now.")
        clear_form_btn = ttk.Button(
            row3, text="New entry", style="Ghost.TButton", command=self.clear_form
        )
        clear_form_btn.pack(side="left", padx=(6, 0))
        ToolTip(clear_form_btn, "Clear the form to add a brand-new event (exit edit mode).")

        log_hr_btn = ttk.Button(
            row3,
            text="Log HR call-in",
            style="Primary.TButton",
            command=lambda: self.add_activity(HR_ACTIVITY),
        )
        log_hr_btn.pack(side="right", padx=(8, 0))
        ToolTip(log_hr_btn, "Save an HR call-in. You’ll be asked what happened before it.")
        self.update_btn = ttk.Button(
            row3, text="Update selected", style="Ghost.TButton", command=self.update_selected
        )
        self.update_btn.pack(side="right", padx=(8, 0))
        ToolTip(self.update_btn, "Save changes to the event selected in the log.")
        add_btn = ttk.Button(row3, text="Add event", style="Ghost.TButton", command=self.add_activity)
        add_btn.pack(side="right")
        ToolTip(add_btn, "Add a new event using the Event name above.")

        presets = ttk.Frame(root, style="TFrame")
        presets.pack(fill="x", padx=14, pady=(0, 4))
        tips = {
            "HR call-in": "Called into HR.",
            "Manager talk": "Talk with a manager.",
            "Write-up": "Formal write-up.",
            "Warning": "Verbal/informal warning.",
            "Deadline": "Work deadline.",
            "Meeting": "Other meeting.",
            "Complaint": "A complaint was involved.",
            "Normal day": "Ordinary day.",
        }
        for name in PRESETS:
            btn = ttk.Button(
                presets,
                text=name,
                style="Preset.TButton",
                command=lambda n=name: self._set_preset(n),
            )
            btn.pack(side="left", padx=(0, 6), pady=2)
            ToolTip(btn, tips.get(name, name))

        # Estimate
        est_frame = ttk.LabelFrame(root, text="Next HR call-in estimate", style="Card.TLabelframe")
        est_frame.pack(fill="x", **pad)
        est_btns = ttk.Frame(est_frame, style="Panel.TFrame")
        est_btns.pack(fill="x")
        estimate_btn = ttk.Button(
            est_btns,
            text="Estimate next HR call-in",
            style="Primary.TButton",
            command=lambda: self.refresh_estimate(show_reminder_popup=True),
        )
        estimate_btn.pack(side="left")
        ToolTip(estimate_btn, "Estimate from gaps between past HR dates. Needs 2+ HR entries.")
        sequence_btn = ttk.Button(
            est_btns, text="Sequence forecast", style="Ghost.TButton", command=self.predict_sequence
        )
        sequence_btn.pack(side="left", padx=(8, 0))
        ToolTip(sequence_btn, "Guess the next event type from recent order.")
        self.reminders_var = tk.BooleanVar(value=bool(self.settings.get("reminders_enabled", True)))
        rem_chk = ttk.Checkbutton(
            est_btns,
            text="Reminders",
            variable=self.reminders_var,
            style="Panel.TCheckbutton",
            command=self._save_settings,
        )
        rem_chk.pack(side="right")
        ToolTip(rem_chk, "Pop up when the estimated HR window is within 3 days or overdue.")

        self.confidence_var = tk.StringVar(value="Confidence: No data")
        self.confidence_label = ttk.Label(
            est_frame, textvariable=self.confidence_var, style="PanelMuted.TLabel"
        )
        self.confidence_label.pack(anchor="w", pady=(8, 0))

        self.reminder_var = tk.StringVar(value="")
        self.reminder_label = ttk.Label(
            est_frame, textvariable=self.reminder_var, style="Warn.TLabel", wraplength=700
        )
        self.reminder_label.pack(anchor="w", pady=(4, 0))

        self.result_var = tk.StringVar(
            value="Log two or more HR call-ins with dates to estimate the next one."
        )
        ttk.Label(
            est_frame, textvariable=self.result_var, style="Result.TLabel", wraplength=700
        ).pack(anchor="w", pady=(8, 6))

        self.dist_text = tk.Text(
            est_frame,
            height=7,
            wrap="word",
            state="disabled",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            highlightcolor=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            relief="flat",
            padx=8,
            pady=6,
        )
        self.dist_text.pack(fill="x")

        # Chart
        chart_frame = ttk.LabelFrame(
            root, text="Pattern chart (gaps + weekdays)", style="Card.TLabelframe"
        )
        chart_frame.pack(fill="x", **pad)
        self.chart_canvas = tk.Canvas(
            chart_frame,
            height=150,
            bg=INPUT_BG,
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
        )
        self.chart_canvas.pack(fill="x")
        ToolTip(self.chart_canvas, "Left: days between HR call-ins. Right: which weekdays HR happens on.")

        # Log list
        list_frame = ttk.LabelFrame(
            root, text="Event log  ·  oldest → newest  ·  ★ = HR", style="Card.TLabelframe"
        )
        list_frame.pack(fill="both", expand=True, **pad)
        filter_row = ttk.Frame(list_frame, style="Panel.TFrame")
        filter_row.pack(fill="x", pady=(0, 6))
        self.hr_only_var = tk.BooleanVar(value=bool(self.settings.get("hr_only_filter", False)))
        hr_chk = ttk.Checkbutton(
            filter_row,
            text="Show HR call-ins only",
            variable=self.hr_only_var,
            style="Panel.TCheckbutton",
            command=self._on_filter_changed,
        )
        hr_chk.pack(side="left")
        ToolTip(hr_chk, "Hide non-HR events in the list. Full log is still used for estimates.")

        list_inner = ttk.Frame(list_frame, style="Panel.TFrame")
        list_inner.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            list_inner,
            height=8,
            bg=INPUT_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=TEXT,
            activestyle="none",
            highlightthickness=1,
            highlightbackground=ACCENT,
            highlightcolor=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            relief="flat",
        )
        lb_scroll = ttk.Scrollbar(list_inner, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=lb_scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        lb_scroll.pack(side="right", fill="y", padx=(6, 0))
        self.listbox.bind("<<ListboxSelect>>", self._on_event_selected)
        ToolTip(self.listbox, "Click an event to load it into the form for editing.")

        btn_row = ttk.Frame(root, style="TFrame")
        btn_row.pack(fill="x", padx=14, pady=(4, 0))
        for text, cmd, tip in (
            ("Remove selected", self.remove_selected, "Delete the highlighted event."),
            ("Clear all", self.clear_all, "Erase the entire log."),
            ("Save PDF", self.print_log, "Save the full log and estimate as a PDF, then optionally print it."),
            ("Export text", self.export_log_text, "Save report as .txt."),
            ("Backup JSON", self.backup_json, "Save a full JSON backup of the log."),
        ):
            b = ttk.Button(btn_row, text=text, style="Ghost.TButton", command=cmd)
            b.pack(side="left", padx=(0, 6))
            ToolTip(b, tip)
        save_btn = ttk.Button(btn_row, text="Save", style="Ghost.TButton", command=self.save_log)
        save_btn.pack(side="right")
        ToolTip(save_btn, "Write log + settings to disk (also auto-saves).")

        notes_frame = ttk.LabelFrame(
            root, text="Notes for selected event", style="Card.TLabelframe"
        )
        notes_frame.pack(fill="x", **pad)
        self.selected_event_var = tk.StringVar(
            value="Select an event to view notes or load it into the edit form."
        )
        ttk.Label(
            notes_frame,
            textvariable=self.selected_event_var,
            style="PanelMuted.TLabel",
            wraplength=700,
        ).pack(anchor="w")
        self.selected_notes_text = tk.Text(
            notes_frame,
            height=4,
            wrap="word",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            highlightcolor=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            relief="flat",
            padx=8,
            pady=6,
        )
        self.selected_notes_text.pack(fill="x", pady=(6, 6))
        save_notes_btn = ttk.Button(
            notes_frame, text="Save notes", style="Primary.TButton", command=self.save_selected_notes
        )
        save_notes_btn.pack(anchor="e")
        ToolTip(save_notes_btn, "Store notes for the selected event without changing other fields.")

        ttk.Label(
            root,
            text="Estimates are pattern helpers · not guarantees",
            style="Muted.TLabel",
        ).pack(anchor="e", padx=14, pady=(0, 12))

    # --- form helpers ---
    def _set_preset(self, name: str):
        self.activity_var.set(name)
        if is_hr_activity(name):
            self.duration_var.set(30)
        elif name == "Normal day":
            self.duration_var.set(480)
        else:
            self.duration_var.set(20)

    def _clear_notes_placeholder(self, _event=None):
        if self._notes_placeholder:
            self.new_notes_text.delete("1.0", tk.END)
            self._notes_placeholder = False

    def _read_new_notes(self) -> str:
        if self._notes_placeholder:
            return ""
        return self.new_notes_text.get("1.0", tk.END).strip()

    def _reset_new_notes(self):
        self.new_notes_text.delete("1.0", tk.END)
        self.new_notes_text.insert(
            "1.0",
            "Who called her in, what was said, outcome, anything that happened before…",
        )
        self._notes_placeholder = True

    def _use_now(self):
        date_s, time_s = now_defaults()
        self.date_var.set(date_s)
        self.time_var.set(time_s)
        self._sync_day_label()

    def clear_form(self):
        self._selected_index = None
        self.activity_var.set(HR_ACTIVITY)
        self.duration_var.set(30)
        self._reset_new_notes()
        self._use_now()
        self.listbox.selection_clear(0, tk.END)
        self.selected_event_var.set("Select an event to view notes or load it into the edit form.")
        self.selected_notes_text.delete("1.0", tk.END)

    def _sync_day_label(self):
        try:
            dt = self._parse_started_at()
            self.day_var.set(f"{day_of_week_label(dt)} · {time_of_day_bucket(dt.hour)}")
        except ValueError:
            self.day_var.set("invalid date/time")

    def _parse_started_at(self) -> datetime:
        try:
            return datetime.strptime(
                f"{self.date_var.get().strip()} {self.time_var.get().strip()}",
                "%Y-%m-%d %H:%M",
            )
        except ValueError as exc:
            raise ValueError("Use date YYYY-MM-DD and time HH:MM.") from exc

    def _collect_form_entry(self, activity: str | None = None) -> dict:
        name = (activity if activity is not None else self.activity_var.get()).strip()
        if not name:
            raise ValueError("Event name is required.")
        started = self._parse_started_at()
        duration = int(self.duration_var.get())
        if duration < 1:
            raise ValueError("Duration must be at least 1 minute.")
        return {
            "activity": name,
            "started_at": started.isoformat(timespec="minutes"),
            "duration_min": duration,
            "notes": self._read_new_notes(),
            "person": self.person_var.get().strip(),
            "workplace": self.workplace_var.get().strip(),
        }

    def _prompt_before_hr(self, hr_started: datetime):
        choice = simpledialog.askstring(
            "What happened before HR?",
            "Optional: log a leading event (helps find warning signs).\n\n"
            "Type one of:\n  " + ", ".join(BEFORE_HR_CHOICES) + "\n\n"
            "Or leave blank to skip.",
            parent=self,
        )
        if not choice:
            return
        choice = choice.strip()
        if not choice or choice.lower().startswith("other"):
            return
        # Match preset case-insensitively
        matched = next((p for p in BEFORE_HR_CHOICES[:-1] if p.lower() == choice.lower()), choice)
        prior = hr_started.timestamp() - 24 * 3600
        prior_dt = datetime.fromtimestamp(prior)
        note = simpledialog.askstring(
            "Before-HR notes",
            f"Optional notes for “{matched}” the day before HR:",
            parent=self,
        )
        self.entries.append(
            {
                "activity": matched,
                "started_at": prior_dt.isoformat(timespec="minutes"),
                "duration_min": 30,
                "notes": (note or "").strip(),
                "person": self.person_var.get().strip(),
                "workplace": self.workplace_var.get().strip(),
            }
        )

    def add_activity(self, name: str | None = None):
        try:
            entry = self._collect_form_entry(name)
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid input", str(exc) or "Check the form fields.")
            return

        if is_hr_activity(entry["activity"]):
            if messagebox.askyesno(
                "Before HR checklist",
                "Log what happened 1 day before this HR call-in?\n\n"
                "(Deadline, Complaint, Manager talk, etc.)",
            ):
                self._prompt_before_hr(datetime.fromisoformat(entry["started_at"]))

        self.entries.append(entry)
        self.entries.sort(key=lambda e: e.get("started_at") or "")
        self._refresh_list()
        self.clear_form()
        self._autosave()
        self.refresh_estimate(show_reminder_popup=True)
        self._select_entry_matching(entry)

    def update_selected(self):
        if self._selected_index is None:
            messagebox.showinfo("No event selected", "Click an event in the log first.")
            return
        try:
            entry = self._collect_form_entry()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid input", str(exc) or "Check the form fields.")
            return
        # Keep notes from selected notes pane if user edited there more recently
        pane_notes = self.selected_notes_text.get("1.0", tk.END).strip()
        if pane_notes and not self._read_new_notes():
            entry["notes"] = pane_notes
        elif self._read_new_notes():
            entry["notes"] = self._read_new_notes()
        else:
            entry["notes"] = pane_notes

        self.entries[self._selected_index] = entry
        self.entries.sort(key=lambda e: e.get("started_at") or "")
        # Reselect by identity after sort
        self._refresh_list()
        self._autosave()
        self.refresh_estimate(show_reminder_popup=False)
        self._select_entry_matching(entry)
        messagebox.showinfo("Updated", "Event updated.")

    def _select_entry_matching(self, entry: dict):
        for i, item in enumerate(self.entries):
            if item is entry or (
                item.get("started_at") == entry.get("started_at")
                and item.get("activity") == entry.get("activity")
                and item.get("notes") == entry.get("notes")
            ):
                self._selected_index = i
                # find in view
                if i in self._view_indices:
                    view_i = self._view_indices.index(i)
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(view_i)
                    self.listbox.see(view_i)
                    self._load_entry_into_form(i)
                break

    def _on_filter_changed(self):
        self._save_settings()
        selected = self._selected_index
        self._refresh_list()
        if selected is not None and selected in self._view_indices:
            view_i = self._view_indices.index(selected)
            self.listbox.selection_set(view_i)
            self.listbox.see(view_i)

    def _on_event_selected(self, _event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        view_i = selection[0]
        if view_i >= len(self._view_indices):
            return
        index = self._view_indices[view_i]
        self._load_entry_into_form(index)

    def _load_entry_into_form(self, index: int):
        self._selected_index = index
        entry = self.entries[index]
        self.activity_var.set(entry.get("activity", ""))
        started = entry.get("started_at")
        if started:
            try:
                dt = datetime.fromisoformat(started)
                self.date_var.set(dt.strftime("%Y-%m-%d"))
                self.time_var.set(dt.strftime("%H:%M"))
            except ValueError:
                pass
        if entry.get("duration_min") is not None:
            self.duration_var.set(int(entry["duration_min"]))
        if entry.get("person"):
            self.person_var.set(entry["person"])
        if entry.get("workplace"):
            self.workplace_var.set(entry["workplace"])
        self._sync_day_label()
        notes = entry.get("notes") or ""
        self.new_notes_text.delete("1.0", tk.END)
        self.new_notes_text.insert("1.0", notes)
        self._notes_placeholder = False
        self.selected_event_var.set(format_entry_line(index + 1, entry))
        self.selected_notes_text.delete("1.0", tk.END)
        self.selected_notes_text.insert("1.0", notes)

    def save_selected_notes(self):
        if self._selected_index is None:
            messagebox.showinfo("No event selected", "Select an event in the log first.")
            return
        notes = self.selected_notes_text.get("1.0", tk.END).strip()
        self.entries[self._selected_index]["notes"] = notes
        self.new_notes_text.delete("1.0", tk.END)
        self.new_notes_text.insert("1.0", notes)
        self._notes_placeholder = False
        self._refresh_list()
        if self._selected_index in self._view_indices:
            view_i = self._view_indices.index(self._selected_index)
            self.listbox.selection_set(view_i)
        self.selected_event_var.set(
            format_entry_line(self._selected_index + 1, self.entries[self._selected_index])
        )
        self._autosave()

    def remove_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = self._view_indices[selection[0]]
        del self.entries[index]
        self.clear_form()
        self._refresh_list()
        self._autosave()
        self.refresh_estimate(show_reminder_popup=False)

    def clear_all(self):
        if not self.entries:
            return
        if messagebox.askyesno("Clear log", "Remove all events?"):
            self.entries.clear()
            self.clear_form()
            self._refresh_list()
            self._set_dist("")
            self.result_var.set("Log cleared.")
            self.confidence_var.set("Confidence: No data")
            self.reminder_var.set("")
            self._draw_chart({})
            self._autosave()

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        self._view_indices = []
        hr_only = bool(self.hr_only_var.get())
        display_n = 0
        for i, entry in enumerate(self.entries):
            if hr_only and not is_hr_activity(entry.get("activity", "")):
                continue
            display_n += 1
            self._view_indices.append(i)
            self.listbox.insert(tk.END, format_entry_line(display_n, entry))

    # --- estimate / chart / reminders ---
    def refresh_estimate(self, show_reminder_popup: bool = False):
        report = self.analyzer.analyze(self.entries)
        self.result_var.set(report["message"])

        conf = report.get("confidence_label", "No data")
        detail = report.get("confidence_detail", "")
        self.confidence_var.set(f"Confidence: {conf} — {detail}")
        level = report.get("confidence", "none")
        style = {
            "stronger": "Ok.TLabel",
            "fair": "Warn.TLabel",
            "weak": "Urgent.TLabel",
            "none": "PanelMuted.TLabel",
        }.get(level, "PanelMuted.TLabel")
        self.confidence_label.configure(style=style)

        reminder = report.get("reminder")
        if reminder and self.reminders_var.get():
            self.reminder_var.set(f"{reminder['title']}: {reminder['text']}")
            self.reminder_label.configure(
                style="Urgent.TLabel" if reminder["level"] == "urgent" else "Warn.TLabel"
            )
            if show_reminder_popup:
                self._maybe_popup_reminder(reminder, report)
        else:
            self.reminder_var.set("")

        lines = [f"HR call-ins logged: {report['hr_count']}"]
        person = self.person_var.get().strip()
        workplace = self.workplace_var.get().strip()
        if person or workplace:
            lines.append(f"Tracking: {person or '—'} @ {workplace or '—'}")

        if report["last_hr"] is not None:
            last = report["last_hr"]
            lines.append(
                f"Last HR: {day_of_week_label(last)} {last.strftime('%Y-%m-%d %H:%M')} "
                f"({report['days_since_last']} day(s) ago)"
            )
        if report["gaps_days"]:
            gaps = ", ".join(str(g) for g in report["gaps_days"])
            lines.append(f"Gaps between call-ins (days): {gaps}")
            lines.append(
                f"Typical gap: median {report['median_gap_days']:.1f}d  ·  "
                f"avg {report['avg_gap_days']:.1f}d  ·  "
                f"range {report['min_gap_days']}-{report['max_gap_days']}d"
            )
        if report["predicted_next"] is not None:
            nxt = report["predicted_next"]
            lines.append(
                f"Estimated next: {day_of_week_label(nxt)} {nxt.strftime('%Y-%m-%d %H:%M')}"
            )
            if report["overdue_days"] is not None:
                lines.append(f"Status: overdue by ~{report['overdue_days']} day(s)")
            elif report["days_until_predicted"] is not None:
                lines.append(f"Status: ~{report['days_until_predicted']} day(s) away")
        if report["typical_day"] or report["typical_time"]:
            lines.append(
                f"Most common window: {report['typical_day'] or '—'} / "
                f"{report['typical_time'] or '—'}"
            )
        if report["day_of_week_counts"]:
            day_bits = ", ".join(
                f"{d}×{c}" for d, c in report["day_of_week_counts"].most_common()
            )
            lines.append(f"Day pattern: {day_bits}")
        if report["time_bucket_counts"]:
            time_bits = ", ".join(
                f"{t}×{c}" for t, c in report["time_bucket_counts"].most_common()
            )
            lines.append(f"Time pattern: {time_bits}")
        if report["avg_duration_min"] is not None:
            lines.append(f"Avg HR meeting length: {format_duration(report['avg_duration_min'])}")
        if report["leading_context"]:
            lead_bits = ", ".join(
                f"{name}×{count}" for name, count in report["leading_context"].most_common(5)
            )
            lines.append(f"Often preceded by: {lead_bits}")
        elif report["hr_count"] >= 1:
            lines.append(
                "Tip: when logging HR, use the before-HR checklist to capture warning signs."
            )

        self._set_dist("\n".join(lines))
        self._draw_chart(report)

    def _maybe_popup_reminder(self, reminder: dict, report: dict):
        key_date = ""
        if report.get("predicted_next") is not None:
            key_date = report["predicted_next"].strftime("%Y-%m-%d")
        key = f"{reminder['level']}|{key_date}|{reminder['title']}"
        if self.settings.get("last_reminder_key") == key:
            return
        self.settings["last_reminder_key"] = key
        self._save_settings()
        messagebox.showwarning(reminder["title"], reminder["text"])

    def _schedule_reminder_check(self):
        if self._reminder_job is not None:
            self.after_cancel(self._reminder_job)
        # Recheck every 6 hours while the app is open
        self._reminder_job = self.after(6 * 60 * 60 * 1000, self._timed_reminder)

    def _timed_reminder(self):
        self.refresh_estimate(show_reminder_popup=True)
        self._schedule_reminder_check()

    def _draw_chart(self, report: dict):
        c = self.chart_canvas
        c.delete("all")
        width = max(c.winfo_width(), 680)
        height = 150
        c.create_rectangle(0, 0, width, height, fill=INPUT_BG, outline="")

        gaps = report.get("gaps_days") or []
        days = report.get("day_of_week_counts") or {}

        # Left panel: gaps
        c.create_text(12, 14, anchor="w", fill=MUTED, font=FONT_SMALL, text="Days between HR")
        left_x0, left_x1 = 12, width // 2 - 16
        plot_top, plot_bot = 28, height - 18
        if gaps:
            max_gap = max(gaps) or 1
            bar_w = max(10, (left_x1 - left_x0) // max(len(gaps), 1) - 6)
            for i, gap in enumerate(gaps):
                x = left_x0 + i * (bar_w + 6)
                h = int((gap / max_gap) * (plot_bot - plot_top))
                c.create_rectangle(
                    x, plot_bot - h, x + bar_w, plot_bot, fill=ACCENT, outline=""
                )
                c.create_text(
                    x + bar_w / 2, plot_bot + 8, fill=MUTED, font=("Segoe UI", 8), text=str(gap)
                )
        else:
            c.create_text(
                left_x0,
                70,
                anchor="w",
                fill=MUTED,
                font=FONT_SMALL,
                text="Need 2+ HR dates to chart gaps",
            )

        # Right panel: weekdays
        c.create_text(
            width // 2 + 8, 14, anchor="w", fill=MUTED, font=FONT_SMALL, text="HR by weekday"
        )
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        counts = [days.get(d, 0) for d in labels]
        max_c = max(counts) if any(counts) else 1
        right_x0 = width // 2 + 8
        slot = max(16, (width - right_x0 - 12) // 7)
        for i, (label, count) in enumerate(zip(labels, counts)):
            x = right_x0 + i * slot
            h = int((count / max_c) * (plot_bot - plot_top)) if count else 0
            color = ACCENT if count else SURFACE
            c.create_rectangle(x, plot_bot - h, x + slot - 6, plot_bot, fill=color, outline="")
            c.create_text(
                x + (slot - 6) / 2,
                plot_bot + 8,
                fill=MUTED,
                font=("Segoe UI", 8),
                text=label[:2],
            )
            if count:
                c.create_text(
                    x + (slot - 6) / 2,
                    plot_bot - h - 8,
                    fill=TEXT,
                    font=("Segoe UI", 8),
                    text=str(count),
                )

    def predict_sequence(self):
        order = 2
        states = self._state_sequence()
        if len(states) <= order:
            messagebox.showinfo(
                "Need more data",
                f"Need more than {order} dated events for a sequence forecast.",
            )
            return

        model = MarkovChainPredictor(order=order)
        model.fit(states)
        durations = DurationTracker()
        durations.fit(self.entries)
        history = states[-order:]
        next_state, confidence = model.predict_next(history)
        distribution = model.predict_distribution(history)
        if next_state is None:
            messagebox.showinfo(
                "No sequence match",
                "That recent sequence has not been seen before. "
                "The gap-based HR estimate is usually more useful.",
            )
            return

        activity, day, bucket = decode_state(next_state)
        avg_duration = durations.predict(activity, day, bucket)
        when_bits = [bit for bit in (day, bucket) if bit]
        when_txt = f" ({', '.join(when_bits)})" if when_bits else ""
        lines = [
            "Sequence forecast (Markov — what tends to follow the latest events):",
            f"Recent: {history}",
            f"Next event likely: {activity}{when_txt}  ·  "
            f"~{format_duration(avg_duration)}  ·  {confidence:.1%}",
            "",
            "Probabilities:",
        ]
        for state, prob in sorted(distribution.items(), key=lambda x: -x[1]):
            act, d, b = decode_state(state)
            avg = durations.predict(act, d, b)
            context = " · ".join(x for x in (d, b) if x)
            suffix = f" [{context}]" if context else ""
            marker = " ★" if is_hr_activity(act) else ""
            lines.append(f"  {act}{marker}{suffix}: {prob:.1%}  (~{format_duration(avg)})")

        self.refresh_estimate(show_reminder_popup=False)
        current = self.dist_text.get("1.0", tk.END).rstrip()
        self._set_dist(current + "\n\n" + "\n".join(lines))

    def _state_sequence(self) -> list[str]:
        return [entry_to_state(entry) for entry in self.entries if entry_to_state(entry)]

    def _set_dist(self, text: str):
        self.dist_text.configure(state="normal")
        self.dist_text.delete("1.0", tk.END)
        self.dist_text.insert(tk.END, text)
        self.dist_text.configure(state="disabled")

    # --- print / export / backup ---
    def build_printable_report(self) -> str:
        lines = [
            "HumanPredict — HR Call-In Pattern Log",
            f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Person: {self.person_var.get().strip() or '—'}",
            f"Workplace: {self.workplace_var.get().strip() or '—'}",
            "=" * 56,
            "",
            "EVENT LOG",
            "-" * 56,
        ]
        if not self.entries:
            lines.append("(No events logged.)")
        else:
            for i, entry in enumerate(self.entries, start=1):
                lines.append(format_entry_line(i, entry))
                notes = (entry.get("notes") or "").strip()
                lines.append(f"    Notes: {notes or '(none)'}")
                lines.append("")
        report = self.analyzer.analyze(self.entries)
        lines.extend(
            [
                "NEXT HR CALL-IN ESTIMATE",
                "-" * 56,
                f"Confidence: {report.get('confidence_label')} — {report.get('confidence_detail')}",
                report["message"],
                "",
                self.dist_text.get("1.0", tk.END).strip(),
                "",
                "=" * 56,
                "Note: Estimates are based on past gaps and are not guarantees.",
            ]
        )
        return "\n".join(lines)

    def print_log(self):
        if not self.entries:
            messagebox.showinfo("Nothing to save", "Log an event first, then save a PDF.")
            return

        default_name = f"HumanPredict_HR_log_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        path = filedialog.asksaveasfilename(
            title="Save log as PDF",
            defaultextension=".pdf",
            initialfile=default_name,
            initialdir=str(app_dir()),
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return

        report = self.build_printable_report()
        try:
            write_text_pdf(
                path,
                report,
                title="HumanPredict HR Call-In Pattern Log",
            )
        except OSError as exc:
            messagebox.showerror("PDF failed", f"Could not save PDF:\n{exc}")
            return

        messagebox.showinfo("PDF saved", f"Report saved as PDF:\n{path}")

        if messagebox.askyesno(
            "Print PDF?",
            "Do you want to print this PDF now?\n\n"
            "Choose Yes to open the Windows print dialog.\n"
            "Choose No to keep the file only.",
        ):
            try:
                os.startfile(path, "print")
            except OSError:
                try:
                    os.startfile(path)
                    messagebox.showinfo(
                        "Opened PDF",
                        "Could not send directly to the printer.\n"
                        "The PDF was opened — use Print from your PDF viewer.",
                    )
                except OSError as exc:
                    messagebox.showerror("Print failed", f"Could not open the PDF:\n{exc}")

    def export_log_text(self):
        if not self.entries:
            messagebox.showinfo("Nothing to export", "Log an event first, then export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export log as text",
            defaultextension=".txt",
            initialfile=f"HumanPredict_HR_log_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(self.build_printable_report(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported", f"Log saved as text:\n{path}")

    def backup_json(self):
        path = filedialog.asksaveasfilename(
            title="Backup log as JSON",
            defaultextension=".json",
            initialfile=f"HumanPredict_HR_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "settings": {
                "person": self.person_var.get().strip(),
                "workplace": self.workplace_var.get().strip(),
            },
            "entries": self.entries,
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        messagebox.showinfo("Backup saved", f"JSON backup written to:\n{path}")

    def show_help(self):
        messagebox.showinfo(
            "HumanPredict help",
            "HR call-in tracker\n\n"
            "• Who/where — person and workplace labels on each event\n"
            "• Log HR call-in — saves HR and offers a before-HR checklist\n"
            "• Update selected — edit date/time/duration/notes of a log row\n"
            "• Estimate — gap-based next date + Weak/Fair/Stronger confidence\n"
            "• Reminders — popup when the window is near or overdue\n"
            "• Chart — gaps between HR dates and weekday counts\n"
            "• HR only filter — show only ★ call-ins in the list\n"
            "• Save PDF — creates a PDF, then asks if you want to print it\n"
            "• Export text / Backup JSON — other file copies\n\n"
            "Hover any control for a short tip.\n"
            "Estimates are helpers, not guarantees.",
        )

    def save_log(self):
        self._autosave()
        messagebox.showinfo("Saved", f"Log:\n{LOG_PATH}\n\nSettings:\n{SETTINGS_PATH}")

    def _autosave(self):
        self._save_settings()
        self._write_log()

    def _write_log(self):
        LOG_PATH.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")

    def _load_log(self):
        paths = [LOG_PATH, app_dir() / "activity_log.json"]
        for path in paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                self.entries = []
                for raw in data:
                    entry = normalize_entry(raw)
                    if entry:
                        self.entries.append(entry)
                self.entries.sort(key=lambda e: e.get("started_at") or "")
                self._refresh_list()
                if path != LOG_PATH:
                    self._write_log()
                return
            except (json.JSONDecodeError, OSError):
                continue


if __name__ == "__main__":
    app = ActivityLoggerApp()
    app.mainloop()
