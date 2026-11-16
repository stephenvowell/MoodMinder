"""Mood Minder — daily mood journal with pattern insights (stephenv.net colors)."""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mood_engine import (
    EMOTION_PRESETS,
    LOW_MOOD_THRESHOLD,
    SLEEP_QUALITIES,
    MoodPatternAnalyzer,
    day_of_week_label,
    time_of_day_bucket,
    VERSION,
)
from pdf_export import write_text_pdf


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


LOG_PATH = app_dir() / "mood_log.json"
SETTINGS_PATH = app_dir() / "mood_settings.json"

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
    def __init__(self, widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
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

    def _hide(self, _e=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def now_defaults() -> tuple[str, str]:
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


def normalize_entry(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        mood = int(float(raw.get("mood")))
    except (TypeError, ValueError):
        return None
    mood = max(1, min(10, mood))
    emotions = raw.get("emotions") or []
    if isinstance(emotions, str):
        emotions = [e.strip() for e in emotions.split(",") if e.strip()]
    emotions = [str(e).strip().lower() for e in emotions if str(e).strip()]
    sleep_hours = raw.get("sleep_hours")
    try:
        sleep_hours = float(sleep_hours) if sleep_hours is not None else None
    except (TypeError, ValueError):
        sleep_hours = None
    return {
        "started_at": raw.get("started_at"),
        "mood": mood,
        "emotions": emotions,
        "sleep_hours": sleep_hours,
        "sleep_quality": str(raw.get("sleep_quality") or "").strip().lower(),
        "food": str(raw.get("food") or "").strip(),
        "ate_with": str(raw.get("ate_with") or "").strip(),
        "talked_to": str(raw.get("talked_to") or "").strip(),
        "talked_about": str(raw.get("talked_about") or "").strip(),
        "events": str(raw.get("events") or "").strip(),
        "location": str(raw.get("location") or "").strip(),
        "thoughts": str(raw.get("thoughts") or "").strip(),
        "notes": str(raw.get("notes") or "").strip(),
    }


def format_entry_line(index: int, entry: dict) -> str:
    mood = entry.get("mood", "?")
    low = ""
    try:
        if float(mood) <= LOW_MOOD_THRESHOLD:
            low = " ★"
    except (TypeError, ValueError):
        pass
    emos = ",".join(entry.get("emotions") or [])[:24]
    emo_bit = f"  ·  {emos}" if emos else ""
    loc = entry.get("location") or ""
    loc_bit = f"  ·  {loc}" if loc else ""
    started = entry.get("started_at")
    if not started:
        return f"{index}. mood {mood}/10{low}{emo_bit}{loc_bit}"
    try:
        dt = datetime.fromisoformat(started)
        when = f"{day_of_week_label(dt)} {dt.strftime('%Y-%m-%d %H:%M')}"
        return f"{index}. {when}  ·  mood {mood}/10{low}{emo_bit}{loc_bit}"
    except ValueError:
        return f"{index}. mood {mood}/10{low}{emo_bit}{loc_bit}"


class MoodMinderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Mood Minder {VERSION}")
        self.geometry("780x1000")
        self.minsize(700, 840)
        self.configure(bg=BG)

        self.entries: list[dict] = []
        self._view_indices: list[int] = []
        self._corr_indices: list[int] = []
        self._selected_index: int | None = None
        self._reminder_job = None
        self.emotion_vars: dict[str, tk.BooleanVar] = {}
        self.settings = self._load_settings()
        self.analyzer = MoodPatternAnalyzer()

        self._apply_theme()
        self._build_ui()
        self._load_log()
        self._sync_day_label()
        self.refresh_insights(show_reminder_popup=True)
        self._schedule_reminder_check()

    def _default_settings(self) -> dict:
        return {
            "person": "",
            "reminders_enabled": True,
            "last_reminder_key": "",
            "low_only_filter": False,
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
        self.settings["reminders_enabled"] = bool(self.reminders_var.get())
        self.settings["low_only_filter"] = bool(self.low_only_var.get())
        try:
            SETTINGS_PATH.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            pass

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
        style.map("TEntry", fieldbackground=[("focus", SURFACE)])
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
            "TCombobox",
            fieldbackground=INPUT_BG,
            foreground=TEXT,
            bordercolor=ACCENT,
            arrowsize=12,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT_BG)],
            foreground=[("readonly", TEXT)],
        )
        style.configure(
            "Panel.TCheckbutton",
            background=PANEL,
            foreground=TEXT,
            font=FONT_SMALL,
            focuscolor=ACCENT,
        )
        style.map("Panel.TCheckbutton", background=[("active", PANEL)])
        style.configure(
            "TCheckbutton",
            background=BG,
            foreground=TEXT,
            font=FONT_SMALL,
            focuscolor=ACCENT,
        )
        style.configure(
            "Primary.TButton",
            background=PRIMARY_BG,
            foreground=PRIMARY_FG,
            font=FONT_BOLD,
            borderwidth=0,
            padding=(14, 8),
        )
        style.map(
            "Primary.TButton",
            background=[("active", MUTED), ("pressed", ACCENT)],
            foreground=[("pressed", TEXT)],
        )
        style.configure(
            "Ghost.TButton",
            background=SURFACE,
            foreground=TEXT,
            font=FONT,
            borderwidth=1,
            bordercolor=ACCENT,
            padding=(10, 6),
        )
        style.map(
            "Ghost.TButton",
            background=[("active", PANEL), ("pressed", ACCENT)],
        )
        style.configure(
            "Preset.TButton",
            background=PANEL,
            foreground=TEXT,
            font=FONT_SMALL,
            borderwidth=1,
            bordercolor=ACCENT,
            padding=(6, 4),
        )
        style.map(
            "Preset.TButton",
            background=[("active", ACCENT)],
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

        # Brand
        brand = ttk.Frame(root, style="TFrame")
        brand.pack(fill="x", **pad)
        title_row = ttk.Frame(brand, style="TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text="Mood Minder", style="Title.TLabel").pack(side="left")
        help_btn = ttk.Button(title_row, text="Help", style="Ghost.TButton", command=self.show_help)
        help_btn.pack(side="right")
        ToolTip(help_btn, "How Mood Minder works and important disclaimers.")
        ttk.Label(
            brand,
            text="Track mood, sleep, food, people, events, location, and thoughts — "
            "then see what correlates with low days. Hover controls for tips.",
            style="Muted.TLabel",
            wraplength=720,
        ).pack(anchor="w", pady=(2, 0))

        # Profile
        profile = ttk.LabelFrame(root, text="Profile", style="Card.TLabelframe")
        profile.pack(fill="x", **pad)
        self.person_var = tk.StringVar(value=self.settings.get("person", ""))
        ttk.Label(profile, text="Your name (optional)", style="PanelMuted.TLabel").pack(anchor="w")
        person_entry = ttk.Entry(profile, textvariable=self.person_var)
        person_entry.pack(fill="x", pady=(2, 0))
        person_entry.bind("<FocusOut>", lambda _e: self._save_settings())
        ToolTip(person_entry, "Optional label stored with your journal.")

        # Check-in
        check = ttk.LabelFrame(root, text="Daily check-in", style="Card.TLabelframe")
        check.pack(fill="x", **pad)

        date_default, time_default = now_defaults()
        self.date_var = tk.StringVar(value=date_default)
        self.time_var = tk.StringVar(value=time_default)
        self.day_var = tk.StringVar(value="")
        self.mood_var = tk.IntVar(value=5)
        self.sleep_hours_var = tk.DoubleVar(value=7.0)
        self.sleep_quality_var = tk.StringVar(value="fair")
        self.food_var = tk.StringVar()
        self.ate_with_var = tk.StringVar()
        self.talked_to_var = tk.StringVar()
        self.talked_about_var = tk.StringVar()
        self.events_var = tk.StringVar()
        self.location_var = tk.StringVar()

        row = ttk.Frame(check, style="Panel.TFrame")
        row.pack(fill="x", pady=(0, 6))
        for label, var, width, tip in (
            ("Date", self.date_var, 12, "YYYY-MM-DD"),
            ("Time", self.time_var, 8, "HH:MM"),
        ):
            col = ttk.Frame(row, style="Panel.TFrame")
            col.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Label(col, text=label, style="PanelMuted.TLabel").pack(anchor="w")
            e = ttk.Entry(col, textvariable=var, width=width)
            e.pack(fill="x", pady=(2, 0))
            e.bind("<KeyRelease>", lambda _e: self._sync_day_label())
            ToolTip(e, tip)
        day_col = ttk.Frame(row, style="Panel.TFrame")
        day_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(day_col, text="Day", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Label(day_col, textvariable=self.day_var, style="Panel.TLabel").pack(
            anchor="w", pady=(4, 0)
        )
        mood_col = ttk.Frame(row, style="Panel.TFrame")
        mood_col.pack(side="left", fill="x", expand=True)
        ttk.Label(mood_col, text="Mood (1–10)", style="PanelMuted.TLabel").pack(anchor="w")
        mood_spin = ttk.Spinbox(mood_col, from_=1, to=10, width=6, textvariable=self.mood_var)
        mood_spin.pack(fill="x", pady=(2, 0))
        ToolTip(mood_spin, "1 = very low / depressed · 10 = excellent")

        # Emotions
        ttk.Label(check, text="Emotions", style="PanelMuted.TLabel").pack(anchor="w")
        emo_row = ttk.Frame(check, style="Panel.TFrame")
        emo_row.pack(fill="x", pady=(2, 6))
        for i, name in enumerate(EMOTION_PRESETS):
            var = tk.BooleanVar(value=False)
            self.emotion_vars[name] = var
            cb = ttk.Checkbutton(
                emo_row, text=name, variable=var, style="Panel.TCheckbutton"
            )
            cb.grid(row=i // 5, column=i % 5, sticky="w", padx=4, pady=2)

        row2 = ttk.Frame(check, style="Panel.TFrame")
        row2.pack(fill="x", pady=(0, 6))
        sh = ttk.Frame(row2, style="Panel.TFrame")
        sh.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(sh, text="Sleep hours", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Spinbox(
            sh, from_=0, to=24, increment=0.5, width=6, textvariable=self.sleep_hours_var
        ).pack(fill="x", pady=(2, 0))
        sq = ttk.Frame(row2, style="Panel.TFrame")
        sq.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Label(sq, text="Sleep quality", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Combobox(
            sq,
            values=SLEEP_QUALITIES,
            textvariable=self.sleep_quality_var,
            state="readonly",
        ).pack(fill="x", pady=(2, 0))
        loc = ttk.Frame(row2, style="Panel.TFrame")
        loc.pack(side="left", fill="x", expand=True)
        ttk.Label(loc, text="Location", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Entry(loc, textvariable=self.location_var).pack(fill="x", pady=(2, 0))

        for label, var, tip in (
            ("Food (what you ate)", self.food_var, "Comma-separated foods or meals"),
            ("Ate with", self.ate_with_var, "alone, partner, friends, family…"),
            ("Talked to", self.talked_to_var, "Who you spoke with"),
            ("Talked about", self.talked_about_var, "Topics, comma-separated"),
            ("Events", self.events_var, "Day events, comma-separated"),
        ):
            ttk.Label(check, text=label, style="PanelMuted.TLabel").pack(anchor="w")
            e = ttk.Entry(check, textvariable=var)
            e.pack(fill="x", pady=(2, 6))
            ToolTip(e, tip)

        ttk.Label(check, text="Thoughts", style="PanelMuted.TLabel").pack(anchor="w")
        self.thoughts_text = tk.Text(
            check,
            height=3,
            wrap="word",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            padx=8,
            pady=6,
        )
        self.thoughts_text.pack(fill="x", pady=(2, 6))
        ToolTip(self.thoughts_text, "What you were thinking about today.")

        btns = ttk.Frame(check, style="Panel.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="Use now", style="Ghost.TButton", command=self._use_now).pack(
            side="left"
        )
        ttk.Button(btns, text="New entry", style="Ghost.TButton", command=self.clear_form).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            btns, text="Save check-in", style="Primary.TButton", command=self.add_checkin
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            btns, text="Update selected", style="Ghost.TButton", command=self.update_selected
        ).pack(side="right")

        # Why this mood
        why = ttk.LabelFrame(root, text="Why this mood", style="Card.TLabelframe")
        why.pack(fill="x", **pad)
        self.why_text = tk.Text(
            why,
            height=7,
            wrap="word",
            state="disabled",
            bg=INPUT_BG,
            fg=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            padx=8,
            pady=6,
        )
        self.why_text.pack(fill="x")
        ToolTip(
            self.why_text,
            "Plain-language explanation based on your past low-mood patterns.",
        )

        # Insights + timing estimate
        insights = ttk.LabelFrame(
            root,
            text="Insights  ·  days until mood change / next low",
            style="Card.TLabelframe",
        )
        insights.pack(fill="x", **pad)
        ib = ttk.Frame(insights, style="Panel.TFrame")
        ib.pack(fill="x")
        ttk.Button(
            ib,
            text="Refresh estimate",
            style="Primary.TButton",
            command=lambda: self.refresh_insights(show_reminder_popup=True),
        ).pack(side="left")
        self.reminders_var = tk.BooleanVar(
            value=bool(self.settings.get("reminders_enabled", True))
        )
        ttk.Checkbutton(
            ib,
            text="Reminders",
            variable=self.reminders_var,
            style="Panel.TCheckbutton",
            command=self._save_settings,
        ).pack(side="right")

        self.confidence_var = tk.StringVar(value="Confidence: No data")
        self.confidence_label = ttk.Label(
            insights, textvariable=self.confidence_var, style="PanelMuted.TLabel"
        )
        self.confidence_label.pack(anchor="w", pady=(8, 0))
        self.reminder_var = tk.StringVar(value="")
        self.reminder_label = ttk.Label(
            insights, textvariable=self.reminder_var, style="Warn.TLabel", wraplength=720
        )
        self.reminder_label.pack(anchor="w", pady=(4, 0))
        self.result_var = tk.StringVar(
            value="Log check-ins to estimate days until mood changes and see correlates."
        )
        ttk.Label(
            insights, textvariable=self.result_var, style="Result.TLabel", wraplength=720
        ).pack(anchor="w", pady=(6, 4))
        self.insights_detail = tk.Text(
            insights,
            height=9,
            wrap="word",
            state="disabled",
            bg=INPUT_BG,
            fg=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            padx=8,
            pady=6,
        )
        self.insights_detail.pack(fill="x")
        ToolTip(
            self.insights_detail,
            "Timing estimates and top patterns from your log.",
        )

        # Charts
        charts = ttk.LabelFrame(
            root, text="Your mood", style="Card.TLabelframe"
        )
        charts.pack(fill="x", **pad)
        self.chart_canvas = tk.Canvas(
            charts,
            height=220,
            bg=INPUT_BG,
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
        )
        self.chart_canvas.pack(fill="x")
        ToolTip(
            self.chart_canvas,
            "One line for your mood. Dots mark low days, triggers, and what helps. "
            "The coach line under it says what to watch for.",
        )
        self.coach_var = tk.StringVar(value="")
        ttk.Label(
            charts,
            textvariable=self.coach_var,
            style="Panel.TLabel",
            wraplength=700,
            justify="left",
            font=FONT,
            foreground=TEXT,
        ).pack(anchor="w", pady=(6, 0))

        # Depression correlation log
        corr = ttk.LabelFrame(
            root,
            text="Depression correlation log  ·  low mood (≤4) with probabilities",
            style="Card.TLabelframe",
        )
        corr.pack(fill="x", **pad)
        corr_inner = ttk.Frame(corr, style="Panel.TFrame")
        corr_inner.pack(fill="both", expand=True)
        self.corr_list = tk.Listbox(
            corr_inner,
            height=6,
            bg=INPUT_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=TEXT,
            activestyle="none",
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
        )
        cs = ttk.Scrollbar(corr_inner, orient="vertical", command=self.corr_list.yview)
        self.corr_list.configure(yscrollcommand=cs.set)
        self.corr_list.pack(side="left", fill="both", expand=True)
        cs.pack(side="right", fill="y", padx=(6, 0))
        self.corr_list.bind("<<ListboxSelect>>", self._on_corr_selected)
        ToolTip(
            self.corr_list,
            "Each low-mood day with linked factors and how often those factors "
            "appear on low days. Click to load and see full explanation.",
        )

        # Full log
        logf = ttk.LabelFrame(
            root, text="Full check-in log  ·  ★ = low mood", style="Card.TLabelframe"
        )
        logf.pack(fill="both", expand=True, **pad)
        fr = ttk.Frame(logf, style="Panel.TFrame")
        fr.pack(fill="x", pady=(0, 6))
        self.low_only_var = tk.BooleanVar(
            value=bool(self.settings.get("low_only_filter", False))
        )
        ttk.Checkbutton(
            fr,
            text="Show low-mood only",
            variable=self.low_only_var,
            style="Panel.TCheckbutton",
            command=self._on_filter_changed,
        ).pack(side="left")

        li = ttk.Frame(logf, style="Panel.TFrame")
        li.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            li,
            height=7,
            bg=INPUT_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=TEXT,
            activestyle="none",
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
        )
        ls = ttk.Scrollbar(li, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=ls.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        ls.pack(side="right", fill="y", padx=(6, 0))
        self.listbox.bind("<<ListboxSelect>>", self._on_event_selected)

        btn_row = ttk.Frame(root, style="TFrame")
        btn_row.pack(fill="x", padx=14, pady=(4, 0))
        for text, cmd, tip in (
            ("Remove selected", self.remove_selected, "Delete selected check-in"),
            ("Clear all", self.clear_all, "Erase the journal"),
            ("Save PDF", self.save_pdf, "Save PDF report, then optionally print"),
            ("Export text", self.export_text, "Export as .txt"),
            ("Backup JSON", self.backup_json, "Full JSON backup"),
        ):
            b = ttk.Button(btn_row, text=text, style="Ghost.TButton", command=cmd)
            b.pack(side="left", padx=(0, 6))
            ToolTip(b, tip)
        ttk.Button(btn_row, text="Save", style="Ghost.TButton", command=self.save_log).pack(
            side="right"
        )

        notes = ttk.LabelFrame(root, text="Notes for selected check-in", style="Card.TLabelframe")
        notes.pack(fill="x", **pad)
        self.selected_label_var = tk.StringVar(
            value="Select a check-in to view or edit notes."
        )
        ttk.Label(
            notes, textvariable=self.selected_label_var, style="PanelMuted.TLabel", wraplength=720
        ).pack(anchor="w")
        self.selected_notes_text = tk.Text(
            notes,
            height=3,
            wrap="word",
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=ACCENT,
            borderwidth=0,
            font=FONT_SMALL,
            padx=8,
            pady=6,
        )
        self.selected_notes_text.pack(fill="x", pady=(6, 6))
        ttk.Button(
            notes, text="Save notes", style="Primary.TButton", command=self.save_selected_notes
        ).pack(anchor="e")

        ttk.Label(
            root,
            text="Personal pattern journal · not a medical diagnosis",
            style="Muted.TLabel",
        ).pack(anchor="e", padx=14, pady=(0, 12))

    # --- form helpers ---
    def _use_now(self):
        d, t = now_defaults()
        self.date_var.set(d)
        self.time_var.set(t)
        self._sync_day_label()

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

    def _selected_emotions(self) -> list[str]:
        return [name for name, var in self.emotion_vars.items() if var.get()]

    def _set_emotions(self, emotions: list[str]):
        wanted = {str(e).strip().lower() for e in emotions}
        for name, var in self.emotion_vars.items():
            var.set(name in wanted)

    def clear_form(self):
        self._selected_index = None
        self.mood_var.set(5)
        self.sleep_hours_var.set(7.0)
        self.sleep_quality_var.set("fair")
        for var in (
            self.food_var,
            self.ate_with_var,
            self.talked_to_var,
            self.talked_about_var,
            self.events_var,
            self.location_var,
        ):
            var.set("")
        self._set_emotions([])
        self.thoughts_text.delete("1.0", tk.END)
        self._use_now()
        self.listbox.selection_clear(0, tk.END)
        self.corr_list.selection_clear(0, tk.END)
        self.selected_label_var.set("Select a check-in to view or edit notes.")
        self.selected_notes_text.delete("1.0", tk.END)
        self._set_text(self.why_text, "Save or select a check-in to see an explanation.")

    def _collect_entry(self) -> dict:
        started = self._parse_started_at()
        mood = int(self.mood_var.get())
        if mood < 1 or mood > 10:
            raise ValueError("Mood must be between 1 and 10.")
        sleep_hours = float(self.sleep_hours_var.get())
        return {
            "started_at": started.isoformat(timespec="minutes"),
            "mood": mood,
            "emotions": self._selected_emotions(),
            "sleep_hours": sleep_hours,
            "sleep_quality": self.sleep_quality_var.get().strip().lower(),
            "food": self.food_var.get().strip(),
            "ate_with": self.ate_with_var.get().strip(),
            "talked_to": self.talked_to_var.get().strip(),
            "talked_about": self.talked_about_var.get().strip(),
            "events": self.events_var.get().strip(),
            "location": self.location_var.get().strip(),
            "thoughts": self.thoughts_text.get("1.0", tk.END).strip(),
            "notes": self.selected_notes_text.get("1.0", tk.END).strip()
            if self._selected_index is not None
            else "",
        }

    def add_checkin(self):
        try:
            entry = self._collect_entry()
            entry["notes"] = ""
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid input", str(exc) or "Check the form.")
            return
        self.entries.append(entry)
        self.entries.sort(key=lambda e: e.get("started_at") or "")
        self._refresh_lists()
        self._autosave()
        self.refresh_insights(show_reminder_popup=False)
        self._select_matching(entry)
        self._update_why_for(entry)

    def update_selected(self):
        if self._selected_index is None:
            messagebox.showinfo("No selection", "Select a check-in in the log first.")
            return
        try:
            entry = self._collect_entry()
            entry["notes"] = self.selected_notes_text.get("1.0", tk.END).strip()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid input", str(exc) or "Check the form.")
            return
        self.entries[self._selected_index] = entry
        self.entries.sort(key=lambda e: e.get("started_at") or "")
        self._refresh_lists()
        self._autosave()
        self.refresh_insights(show_reminder_popup=False)
        self._select_matching(entry)
        self._update_why_for(entry)
        messagebox.showinfo("Updated", "Check-in updated.")

    def _load_entry_into_form(self, index: int):
        self._selected_index = index
        entry = self.entries[index]
        self.mood_var.set(int(entry.get("mood", 5)))
        self._set_emotions(entry.get("emotions") or [])
        if entry.get("sleep_hours") is not None:
            self.sleep_hours_var.set(float(entry["sleep_hours"]))
        self.sleep_quality_var.set(entry.get("sleep_quality") or "fair")
        self.food_var.set(entry.get("food") or "")
        self.ate_with_var.set(entry.get("ate_with") or "")
        self.talked_to_var.set(entry.get("talked_to") or "")
        self.talked_about_var.set(entry.get("talked_about") or "")
        self.events_var.set(entry.get("events") or "")
        self.location_var.set(entry.get("location") or "")
        started = entry.get("started_at")
        if started:
            try:
                dt = datetime.fromisoformat(started)
                self.date_var.set(dt.strftime("%Y-%m-%d"))
                self.time_var.set(dt.strftime("%H:%M"))
            except ValueError:
                pass
        self._sync_day_label()
        self.thoughts_text.delete("1.0", tk.END)
        self.thoughts_text.insert("1.0", entry.get("thoughts") or "")
        self.selected_label_var.set(format_entry_line(index + 1, entry))
        self.selected_notes_text.delete("1.0", tk.END)
        self.selected_notes_text.insert("1.0", entry.get("notes") or "")
        self._update_why_for(entry)

    def _on_event_selected(self, _e=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        view_i = sel[0]
        if view_i >= len(self._view_indices):
            return
        self._load_entry_into_form(self._view_indices[view_i])

    def _on_corr_selected(self, _e=None):
        sel = self.corr_list.curselection()
        if not sel:
            return
        view_i = sel[0]
        if view_i >= len(self._corr_indices):
            return
        self._load_entry_into_form(self._corr_indices[view_i])

    def _on_filter_changed(self):
        self._save_settings()
        selected = self._selected_index
        self._refresh_lists()
        if selected is not None and selected in self._view_indices:
            self.listbox.selection_set(self._view_indices.index(selected))

    def _select_matching(self, entry: dict):
        for i, item in enumerate(self.entries):
            if item.get("started_at") == entry.get("started_at") and item.get("mood") == entry.get(
                "mood"
            ):
                self._selected_index = i
                if i in self._view_indices:
                    vi = self._view_indices.index(i)
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(vi)
                    self.listbox.see(vi)
                self._load_entry_into_form(i)
                break

    def save_selected_notes(self):
        if self._selected_index is None:
            messagebox.showinfo("No selection", "Select a check-in first.")
            return
        self.entries[self._selected_index]["notes"] = self.selected_notes_text.get(
            "1.0", tk.END
        ).strip()
        self._refresh_lists()
        self._autosave()

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        index = self._view_indices[sel[0]]
        del self.entries[index]
        self.clear_form()
        self._refresh_lists()
        self._autosave()
        self.refresh_insights(show_reminder_popup=False)

    def clear_all(self):
        if not self.entries:
            return
        if messagebox.askyesno("Clear all", "Remove all check-ins?"):
            self.entries.clear()
            self.clear_form()
            self._refresh_lists()
            self._autosave()
            self.refresh_insights(show_reminder_popup=False)

    def _refresh_lists(self):
        self.listbox.delete(0, tk.END)
        self._view_indices = []
        low_only = bool(self.low_only_var.get())
        n = 0
        for i, entry in enumerate(self.entries):
            try:
                is_low = float(entry.get("mood", 99)) <= LOW_MOOD_THRESHOLD
            except (TypeError, ValueError):
                is_low = False
            if low_only and not is_low:
                continue
            n += 1
            self._view_indices.append(i)
            self.listbox.insert(tk.END, format_entry_line(n, entry))

        # Correlation list from latest analysis
        report = self.analyzer.analyze(self.entries)
        self.corr_list.delete(0, tk.END)
        self._corr_indices = []
        for ev in report["depression_events"]:
            # find index of entry
            idx = None
            for i, entry in enumerate(self.entries):
                if entry.get("started_at") == ev.get("started_at"):
                    idx = i
                    break
            if idx is None:
                continue
            self._corr_indices.append(idx)
            emos = ",".join(ev.get("emotions") or [])
            line = (
                f"{ev['date']}  ·  mood {ev['mood']:.0f}/10"
                f"{('  ·  ' + emos) if emos else ''}"
                f"  ·  {ev['summary']}"
            )
            self.corr_list.insert(tk.END, line)

    def _update_why_for(self, entry: dict):
        text = self.analyzer.explain_mood(entry, self.entries)
        self._set_text(self.why_text, text)

    def _set_text(self, widget: tk.Text, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.configure(state="disabled")

    # --- insights / charts ---
    def refresh_insights(self, show_reminder_popup: bool = False):
        report = self.analyzer.analyze(self.entries)
        self.result_var.set(report["message"])
        self.coach_var.set(report.get("coach_message") or "")
        self.confidence_var.set(
            f"Confidence: {report['confidence_label']} — {report['confidence_detail']}"
        )
        style = {
            "stronger": "Ok.TLabel",
            "fair": "Warn.TLabel",
            "weak": "Urgent.TLabel",
            "none": "PanelMuted.TLabel",
        }.get(report.get("confidence"), "PanelMuted.TLabel")
        self.confidence_label.configure(style=style)

        reminder = report.get("reminder")
        if reminder and self.reminders_var.get():
            self.reminder_var.set(f"{reminder['title']}: {reminder['text']}")
            self.reminder_label.configure(
                style="Urgent.TLabel" if reminder["level"] == "urgent" else "Warn.TLabel"
            )
            if show_reminder_popup:
                self._maybe_popup_reminder(reminder)
        else:
            self.reminder_var.set("")

        lines = [
            f"Check-ins: {report['count']}  ·  Low days: {report['low_count']}  ·  "
            f"High days: {report['high_count']}",
        ]
        person = self.person_var.get().strip()
        if person:
            lines.append(f"Journal for: {person}")

        lines.append("")
        lines.append("")
        lines.append("Timing (from your log):")
        if report.get("days_until_mood_change") is not None:
            pred = report.get("predicted_next_change")
            pred_s = pred.strftime("%Y-%m-%d") if pred else "—"
            band = report.get("current_mood_band") or "?"
            into = report.get("days_in_current_band")
            d = report["days_until_mood_change"]
            med = report.get("median_change_gap_days")
            if d < 0:
                into_bit = (
                    f" — it has been {band} for {into} day{'s' if into != 1 else ''}"
                    if into is not None
                    else ""
                )
                lines.append(f"  · Your mood is due for a change{into_bit}.")
            elif d == 0:
                lines.append("  · Your mood may change today.")
            elif med:
                lines.append(
                    f"  · Your mood usually changes about every {med:.0f} days "
                    f"(next change around {pred_s})."
                )
            else:
                lines.append(f"  · Your mood may change in about {d} days.")
        else:
            lines.append("  · Need more mood changes in the log to estimate timing.")
        if report.get("next_low_text"):
            lines.append(f"  · {report['next_low_text']}")
            gaps = report.get("low_gaps_days") or []
            gap_txt = ", ".join(str(g) for g in gaps[-6:])
            if gap_txt:
                lines.append(f"  · Your low days were {gap_txt} days apart.")
            if report.get("typical_low_weekday"):
                lines.append(f"  · Low days often fall on: {report['typical_low_weekday']}")
        elif report.get("low_count", 0) < 2:
            lines.append("  · Log 2+ low days to estimate when the next low may come.")
        if report.get("median_recovery_days") is not None:
            rec = report.get("days_until_typical_recovery")
            med = report["median_recovery_days"]
            day_word = "day" if round(med) == 1 else "days"
            bit = (
                f"  · After a low day, your mood usually lifts "
                f"within about {med:.0f} {day_word}."
            )
            if rec is not None:
                if rec > 0:
                    bit += f" About {rec} day{'s' if rec != 1 else ''} left in this low spell."
                else:
                    bit += " That time has passed."
            lines.append(bit)
        if report.get("next_mood_band"):
            lines.append(
                f"  · Your next check-in will most likely be {report['next_mood_band']} "
                f"(about {report['next_mood_band_prob']:.0%} likely)."
            )

        correlates = [
            s
            for s in report["factor_stats"]
            if s["low_count"] >= 1 and s["count"] >= 2
        ][:8]
        if correlates:
            lines.append("")
            lines.append("Top low-mood correlates (need 2+ days with factor):")
            for s in correlates:
                lines.append(
                    f"  · {s['category']}:{s['value']} → low on {s['p_low']:.0%} "
                    f"({s['low_count']}/{s['count']} days)"
                )
        elif report["factor_stats"]:
            lines.append("")
            lines.append("Early correlates (still thin — keep logging):")
            for s in report["factor_stats"][:6]:
                if s["low_count"] < 1:
                    continue
                lines.append(
                    f"  · {s['category']}:{s['value']} → low on {s['p_low']:.0%} "
                    f"({s['low_count']}/{s['count']} days)"
                )

        lagged = [
            s for s in (report.get("lagged_factor_stats") or []) if s["low_count"] >= 1
        ][:5]
        if lagged:
            lines.append("Delayed patterns (1-3 days earlier):")
            for s in lagged:
                lines.append(
                    f"  \u00b7 {s['lag']}d earlier \u2014 {s['category']}:{s['value']} \u2192 low on {s['p_low']:.0%} "
                    f"({s['low_count']}/{s['count']} days)"
                )
        if report["sleep_buckets"]:
            bits = ", ".join(f"{k} avg {v:.1f}" for k, v in report["sleep_buckets"].items())
            lines.append(f"Sleep vs mood: {bits}")
        self._set_text(self.insights_detail, "\n".join(lines))
        self._draw_charts(report)
        self._refresh_lists()
        if self._selected_index is not None and self._selected_index < len(self.entries):
            self._update_why_for(self.entries[self._selected_index])

    def _maybe_popup_reminder(self, reminder: dict):
        key = f"{reminder['level']}|{reminder['title']}|{datetime.now().strftime('%Y-%m-%d')}"
        if self.settings.get("last_reminder_key") == key:
            return
        self.settings["last_reminder_key"] = key
        self._save_settings()
        messagebox.showwarning(reminder["title"], reminder["text"])

    def _schedule_reminder_check(self):
        if self._reminder_job is not None:
            self.after_cancel(self._reminder_job)
        self._reminder_job = self.after(6 * 60 * 60 * 1000, self._timed_reminder)

    def _timed_reminder(self):
        self.refresh_insights(show_reminder_popup=True)
        self._schedule_reminder_check()

    def _draw_charts(self, report: dict):
        c = self.chart_canvas
        c.delete("all")
        w = max(c.winfo_width(), 720)
        h = 220
        c.create_rectangle(0, 0, w, h, fill=INPUT_BG, outline="")

        # Legend at top
        legend = [(URGENT, "low day"), (WARN, "trigger"), (OK_GREEN, "what helps")]
        lx = 46
        ly = 14
        for color, label in legend:
            c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill=color, outline="")
            c.create_text(lx + 6, ly, anchor="w", fill=MUTED, font=FONT_SMALL, text=label)
            lx += 6 + len(label) * 7 + 18

        plot_l, plot_r, plot_t, plot_b = 46, w - 10, 30, 188

        chart = report.get("chart_data") or {}
        points = chart.get("points") or []
        markers = chart.get("markers") or []

        if not points:
            c.create_text(
                w / 2, h / 2, anchor="center", fill=MUTED, font=FONT_SMALL,
                text="Log a check-in to see your line.",
            )
            return

        def y_for(mood):
            return plot_b - (float(mood) - 1) / 9 * (plot_b - plot_t)

        def x_for(i):
            if len(points) == 1:
                return (plot_l + plot_r) / 2
            return plot_l + i * (plot_r - plot_l) / (len(points) - 1)

        # Y axis guide lines and labels
        for mood_val, word in ((10, "Great"), (5, "Okay"), (1, "Low")):
            y = y_for(mood_val)
            c.create_line(plot_l, y, plot_r, y, fill=SURFACE)
            c.create_text(plot_l - 4, y, anchor="e", fill=MUTED, font=FONT_SMALL, text=word)

        # X axis date labels for up to 6 evenly spaced points
        n = len(points)
        if n <= 6:
            label_indices = list(range(n))
        else:
            label_indices = sorted({round(i * (n - 1) / 5) for i in range(6)})
        for i in label_indices:
            try:
                dt = datetime.strptime(points[i]["date"], "%Y-%m-%d")
                label = f"{dt.strftime('%b')} {dt.day}"
            except (ValueError, TypeError):
                label = points[i]["date"]
            c.create_text(x_for(i), 196, anchor="center", fill=MUTED, font=FONT_SMALL, text=label)

        coords = []
        for i, p in enumerate(points):
            coords.extend([x_for(i), y_for(p["mood"])])

        if len(points) > 1:
            c.create_line(*coords, fill=ACCENT, width=2, smooth=False)

        point_by_date = {}
        for i, p in enumerate(points):
            x, y = x_for(i), y_for(p["mood"])
            point_by_date[p["date"]] = (x, y, p)
            if p.get("low"):
                c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=URGENT, outline="")
            else:
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=ACCENT, outline="")

        # Markers
        sorted_markers = sorted(markers, key=lambda m: m.get("date", ""))
        for order, m in enumerate(sorted_markers):
            date_str = m.get("date")
            if date_str not in point_by_date:
                continue
            x, y, _p = point_by_date[date_str]
            kind = m.get("kind")
            label = (m.get("label") or "")[:18]
            if kind == "trigger":
                c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=WARN, outline="")
                offset = 12 if order % 2 == 0 else 26
                c.create_text(x, y - offset, anchor="s", fill=MUTED, font=FONT_SMALL, text=label)
            elif kind == "helps":
                c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=OK_GREEN, outline="")
                offset = 12 if order % 2 == 0 else 26
                c.create_text(x, y - offset, anchor="s", fill=MUTED, font=FONT_SMALL, text=label)
            elif kind == "low":
                c.create_text(x, y + 12, anchor="n", fill=MUTED, font=FONT_SMALL, text=label)

    # --- export ---
    def build_report(self) -> str:
        report = self.analyzer.analyze(self.entries)
        lines = [
            "Mood Minder — Personal Mood Journal",
            f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Person: {self.person_var.get().strip() or '—'}",
            "=" * 56,
            "",
            "INSIGHTS / TIMING",
            "-" * 56,
            report["message"],
            f"Confidence: {report['confidence_label']} — {report['confidence_detail']}",
        ]
        lines.extend(
            [
                "",
                "CHECK-INS",
                "-" * 56,
            ]
        )
        if not self.entries:
            lines.append("(No check-ins.)")
        else:
            for i, entry in enumerate(self.entries, start=1):
                lines.append(format_entry_line(i, entry))
                if entry.get("thoughts"):
                    lines.append(f"    Thoughts: {entry['thoughts']}")
                if entry.get("notes"):
                    lines.append(f"    Notes: {entry['notes']}")
                lines.append("")
        lines.extend(["", "LOW-MOOD / DEPRESSION CORRELATION LOG", "-" * 56])
        if not report["depression_events"]:
            lines.append("(No low-mood days ≤4 yet.)")
        else:
            for ev in report["depression_events"]:
                lines.append(f"{ev['date']}  mood {ev['mood']:.0f}/10")
                lines.append(f"    {ev['summary']}")
                lines.append("")
        if self._selected_index is not None and self._selected_index < len(self.entries):
            lines.extend(
                [
                    "",
                    "WHY THIS MOOD (selected)",
                    "-" * 56,
                    self.analyzer.explain_mood(
                        self.entries[self._selected_index], self.entries
                    ),
                ]
            )
        lines.extend(
            [
                "",
                "=" * 56,
                "Personal patterns only — not a medical diagnosis.",
            ]
        )
        return "\n".join(lines)

    def save_pdf(self):
        if not self.entries:
            messagebox.showinfo("Nothing to save", "Log a check-in first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Mood Minder PDF",
            defaultextension=".pdf",
            initialfile=f"MoodMinder_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            initialdir=str(app_dir()),
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            write_text_pdf(path, self.build_report(), title="Mood Minder Report")
        except OSError as exc:
            messagebox.showerror("PDF failed", str(exc))
            return
        messagebox.showinfo("PDF saved", f"Report saved:\n{path}")
        if messagebox.askyesno(
            "Print PDF?",
            "Do you want to print this PDF now?\n\n"
            "Yes opens the Windows print dialog.\nNo keeps the file only.",
        ):
            try:
                os.startfile(path, "print")
            except OSError:
                try:
                    os.startfile(path)
                    messagebox.showinfo(
                        "Opened PDF",
                        "Could not send to printer directly. Use Print in your PDF viewer.",
                    )
                except OSError as exc:
                    messagebox.showerror("Print failed", str(exc))

    def export_text(self):
        if not self.entries:
            messagebox.showinfo("Nothing to export", "Log a check-in first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export text",
            defaultextension=".txt",
            initialfile=f"MoodMinder_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(self.build_report(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported", path)

    def backup_json(self):
        path = filedialog.asksaveasfilename(
            title="Backup JSON",
            defaultextension=".json",
            initialfile=f"MoodMinder_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "settings": {"person": self.person_var.get().strip()},
            "entries": self.entries,
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        messagebox.showinfo("Backup saved", path)

    def show_help(self):
        messagebox.showinfo(
            "Mood Minder help",
            f"Mood Minder is a personal mood journal (version {VERSION}).\n\n"
            "1. Log mood (1–10), emotions, sleep, food, people, events, location, thoughts.\n"
            "2. Insights estimates when your mood may change and when the next low day "
            "may come, from the patterns in your log.\n"
            "3. The chart shows your mood as one line, with triggers and what helps marked on it in plain words. The coach line under it says what to watch for.\n"
            "4. Why this mood explains the selected check-in in plain language.\n"
            "5. Save PDF creates a report, then asks if you want to print.\n\n"
            "Not a medical device or diagnosis. If you are in crisis, seek professional help.",
        )

    def save_log(self):
        self._autosave()
        messagebox.showinfo("Saved", f"Log:\n{LOG_PATH}\n\nSettings:\n{SETTINGS_PATH}")

    def _autosave(self):
        self._save_settings()
        LOG_PATH.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")

    def _load_log(self):
        if not LOG_PATH.exists():
            self._set_text(self.why_text, "Save or select a check-in to see an explanation.")
            return
        try:
            data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
            self.entries = []
            for raw in data:
                entry = normalize_entry(raw)
                if entry:
                    self.entries.append(entry)
            self.entries.sort(key=lambda e: e.get("started_at") or "")
            self._refresh_lists()
        except (json.JSONDecodeError, OSError):
            pass
        self._set_text(self.why_text, "Save or select a check-in to see an explanation.")


if __name__ == "__main__":
    app = MoodMinderApp()
    app.mainloop()
