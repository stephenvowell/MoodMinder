"""Mood Minder analysis engine — patterns, correlates, explanations."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean
import random

LOW_MOOD_THRESHOLD = 4
HIGH_MOOD_THRESHOLD = 7
POOR_SLEEP_HOURS = 6.0

EMOTION_PRESETS = [
    "anxious",
    "sad",
    "numb",
    "irritable",
    "calm",
    "hopeful",
    "lonely",
    "overwhelmed",
    "content",
    "angry",
]

SLEEP_QUALITIES = ["poor", "fair", "good", "great"]


def time_of_day_bucket(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def day_of_week_label(dt: datetime) -> str:
    return dt.strftime("%a")


def parse_entry_datetime(entry: dict) -> datetime | None:
    started_at = entry.get("started_at")
    if not started_at:
        return None
    try:
        return datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return None


def mood_band(mood: int | float | None) -> str:
    if mood is None:
        return "unknown"
    try:
        m = float(mood)
    except (TypeError, ValueError):
        return "unknown"
    if m <= LOW_MOOD_THRESHOLD:
        return "low"
    if m >= HIGH_MOOD_THRESHOLD:
        return "high"
    return "mid"


def _split_tokens(text: str) -> list[str]:
    if not text:
        return []
    parts = []
    for chunk in str(text).replace(";", ",").split(","):
        t = chunk.strip().lower()
        if t:
            parts.append(t)
    return parts


def extract_factors(entry: dict) -> list[tuple[str, str]]:
    """Return (category, value) pairs for correlation analysis."""
    factors: list[tuple[str, str]] = []
    for emo in entry.get("emotions") or []:
        e = str(emo).strip().lower()
        if e:
            factors.append(("emotion", e))

    loc = str(entry.get("location") or "").strip().lower()
    if loc:
        factors.append(("location", loc))

    ate = str(entry.get("ate_with") or "").strip().lower()
    if ate:
        factors.append(("ate_with", ate))

    talked = str(entry.get("talked_to") or "").strip().lower()
    if talked:
        factors.append(("talked_to", talked))

    sq = str(entry.get("sleep_quality") or "").strip().lower()
    if sq:
        factors.append(("sleep_quality", sq))

    try:
        hours = float(entry.get("sleep_hours"))
        if hours < POOR_SLEEP_HOURS:
            factors.append(("sleep", f"under_{int(POOR_SLEEP_HOURS)}h"))
        elif hours >= 8:
            factors.append(("sleep", "8h_plus"))
        else:
            factors.append(("sleep", "6_to_8h"))
    except (TypeError, ValueError):
        pass

    for topic in _split_tokens(entry.get("talked_about") or ""):
        factors.append(("talked_about", topic))
    for ev in _split_tokens(entry.get("events") or ""):
        factors.append(("event", ev))
    for food in _split_tokens(entry.get("food") or ""):
        if len(food) >= 3:
            factors.append(("food", food[:40]))

    return factors


def entry_to_mood_state(entry: dict) -> str:
    band = mood_band(entry.get("mood"))
    sleep = "unknown_sleep"
    try:
        hours = float(entry.get("sleep_hours"))
        sleep = "poor_sleep" if hours < POOR_SLEEP_HOURS else "ok_sleep"
    except (TypeError, ValueError):
        sq = str(entry.get("sleep_quality") or "").lower()
        if sq == "poor":
            sleep = "poor_sleep"
        elif sq:
            sleep = "ok_sleep"
    loc = str(entry.get("location") or "unknown").strip().lower() or "unknown"
    return f"{band}|{sleep}|{loc}"


class MoodPatternAnalyzer:
    """Find correlates of low mood and explain them in plain language."""

    def __init__(
        self,
        low_threshold: int = LOW_MOOD_THRESHOLD,
        high_threshold: int = HIGH_MOOD_THRESHOLD,
    ):
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    def dated_entries(self, entries: list[dict]) -> list[tuple[dict, datetime]]:
        out = []
        for entry in entries:
            dt = parse_entry_datetime(entry)
            if dt is None:
                continue
            try:
                float(entry.get("mood"))
            except (TypeError, ValueError):
                continue
            out.append((entry, dt))
        out.sort(key=lambda item: item[1])
        return out

    def analyze(self, entries: list[dict], as_of: datetime | None = None) -> dict:
        as_of = as_of or datetime.now()
        dated = self.dated_entries(entries)
        report = {
            "count": len(dated),
            "avg_7": None,
            "avg_30": None,
            "avg_all": None,
            "low_count": 0,
            "high_count": 0,
            "confidence": "none",
            "confidence_label": "No data",
            "confidence_detail": "Log check-ins with a mood score to begin.",
            "factor_stats": [],
            "sleep_buckets": {},
            "emotion_low": Counter(),
            "emotion_high": Counter(),
            "mood_series": [],
            "depression_events": [],
            "reminder": None,
            "message": "",
            "baseline_low_rate": 0.0,
        }

        if not dated:
            report["message"] = "Add a check-in with mood, sleep, and daily context to start."
            return report

        moods = [float(e["mood"]) for e, _ in dated]
        report["avg_all"] = mean(moods)
        report["low_count"] = sum(1 for m in moods if m <= self.low_threshold)
        report["high_count"] = sum(1 for m in moods if m >= self.high_threshold)
        report["baseline_low_rate"] = report["low_count"] / len(moods)

        def avg_since(days: int) -> float | None:
            cutoff = as_of - timedelta(days=days)
            vals = [float(e["mood"]) for e, dt in dated if dt >= cutoff]
            return mean(vals) if vals else None

        report["avg_7"] = avg_since(7)
        report["avg_30"] = avg_since(30)

        by_day: dict[str, list[float]] = defaultdict(list)
        for entry, dt in dated:
            by_day[dt.strftime("%Y-%m-%d")].append(float(entry["mood"]))
        report["mood_series"] = [
            {"date": day, "mood": mean(vals), "low": mean(vals) <= self.low_threshold}
            for day, vals in sorted(by_day.items())
        ]

        sleep_map: dict[str, list[float]] = defaultdict(list)
        for entry, _ in dated:
            try:
                hours = float(entry.get("sleep_hours"))
            except (TypeError, ValueError):
                continue
            if hours < 6:
                key = "<6h"
            elif hours < 8:
                key = "6-8h"
            else:
                key = "8h+"
            sleep_map[key].append(float(entry["mood"]))
        report["sleep_buckets"] = {k: mean(v) for k, v in sleep_map.items() if v}

        factor_total: Counter = Counter()
        factor_low: Counter = Counter()
        factor_dates: dict[tuple[str, str], list[str]] = defaultdict(list)

        for entry, dt in dated:
            mood = float(entry["mood"])
            is_low = mood <= self.low_threshold
            day = dt.strftime("%Y-%m-%d")
            for cat, val in extract_factors(entry):
                key = (cat, val)
                factor_total[key] += 1
                if is_low:
                    factor_low[key] += 1
                    factor_dates[key].append(day)
            for emo in entry.get("emotions") or []:
                e = str(emo).strip().lower()
                if not e:
                    continue
                if is_low:
                    report["emotion_low"][e] += 1
                elif mood >= self.high_threshold:
                    report["emotion_high"][e] += 1

        baseline = report["baseline_low_rate"] or 0.0
        stats = []
        for key, total in factor_total.items():
            if total < 1:
                continue
            low_n = factor_low[key]
            p_low = low_n / total
            lift = (p_low / baseline) if baseline > 0 else 0.0
            cat, val = key
            stats.append(
                {
                    "category": cat,
                    "value": val,
                    "count": total,
                    "low_count": low_n,
                    "p_low": p_low,
                    "lift": lift,
                    "dates": sorted(set(factor_dates[key])),
                }
            )
        stats.sort(key=lambda s: (s["p_low"], s["low_count"], s["lift"]), reverse=True)
        report["factor_stats"] = stats

        events = []
        for entry, dt in dated:
            mood = float(entry["mood"])
            if mood > self.low_threshold:
                continue
            day_factors = extract_factors(entry)
            linked = []
            for cat, val in day_factors:
                match = next(
                    (s for s in stats if s["category"] == cat and s["value"] == val),
                    None,
                )
                if match and match["low_count"] >= 1:
                    linked.append(match)
            linked.sort(key=lambda s: s["p_low"], reverse=True)
            top = linked[:5]
            why_bits = [
                f"{s['category']}:{s['value']} ({s['p_low']:.0%} of days with this were low)"
                for s in top[:3]
            ]
            events.append(
                {
                    "started_at": entry.get("started_at"),
                    "date": dt.strftime("%Y-%m-%d"),
                    "mood": mood,
                    "emotions": list(entry.get("emotions") or []),
                    "factors": top,
                    "summary": "; ".join(why_bits)
                    if why_bits
                    else "Few repeating patterns yet for this day.",
                    "entry": entry,
                }
            )
        events.sort(key=lambda e: e["date"], reverse=True)
        report["depression_events"] = events

        report.update(self._confidence(len(dated)))
        report["reminder"] = self._reminder(dated, as_of)
        if report["avg_7"] is not None:
            report["message"] = (
                f"7-day avg mood {report['avg_7']:.1f}/10 · "
                f"30-day {report['avg_30']:.1f}/10 · "
                f"{report['low_count']} low-mood day(s) logged"
            )
        else:
            report["message"] = f"{len(dated)} check-in(s) logged."

        return report

    def explain_mood(self, entry: dict, entries: list[dict]) -> str:
        report = self.analyze(entries)
        try:
            mood = float(entry.get("mood"))
        except (TypeError, ValueError):
            return "Add a mood score (1–10) to get an explanation."

        lines = [f"Your score is {mood:.0f}/10 for this check-in."]
        dt = parse_entry_datetime(entry)
        if dt:
            lines.append(
                f"When: {day_of_week_label(dt)} {dt.strftime('%Y-%m-%d %H:%M')} "
                f"({time_of_day_bucket(dt.hour)})"
            )

        emos = [str(e) for e in (entry.get("emotions") or []) if str(e).strip()]
        if emos:
            lines.append("Emotions tagged: " + ", ".join(emos))

        if mood > self.low_threshold:
            highs = [
                s
                for s in report["factor_stats"]
                if s["p_low"] < 0.35 and s["count"] >= 2
            ][:5]
            lines.append("")
            lines.append("This is not in the low-mood range (≤4).")
            if highs:
                lines.append("Factors that less often appear on low days in your log:")
                for s in highs[:3]:
                    lines.append(
                        f"  · {s['category']}: {s['value']} "
                        f"(low on {s['p_low']:.0%} of days with this)"
                    )
            lines.append("")
            lines.append(
                "Patterns are personal correlations from your journal — "
                "not a medical diagnosis."
            )
            return "\n".join(lines)

        lines.append("")
        lines.append("Why this may fit a depressed / low-mood pattern for you:")
        day_factors = extract_factors(entry)
        if not day_factors:
            lines.append("  · Not enough context fields filled to compare yet.")
        else:
            ranked = []
            for cat, val in day_factors:
                match = next(
                    (
                        s
                        for s in report["factor_stats"]
                        if s["category"] == cat and s["value"] == val
                    ),
                    None,
                )
                if match:
                    ranked.append(match)
            ranked.sort(key=lambda s: (s["p_low"], s["low_count"]), reverse=True)
            if not ranked:
                lines.append("  · Need more history before strong links appear.")
            for s in ranked[:5]:
                dates = ", ".join(s["dates"][-3:]) if s["dates"] else "—"
                lines.append(
                    f"  · {s['category']}: {s['value']} — "
                    f"showed up on {s['p_low']:.0%} of your days with this factor "
                    f"when mood was low (seen on {dates})"
                )

        try:
            hours = float(entry.get("sleep_hours"))
            if hours < POOR_SLEEP_HOURS:
                bucket_avg = report["sleep_buckets"].get("<6h")
                extra = (
                    f" (your avg mood when <6h sleep: {bucket_avg:.1f})"
                    if bucket_avg
                    else ""
                )
                lines.append(f"  · Sleep was short ({hours:g}h){extra}.")
        except (TypeError, ValueError):
            pass

        if report["avg_7"] is not None:
            lines.append(
                f"\nRecent trend: 7-day average {report['avg_7']:.1f}/10 "
                f"(30-day {report['avg_30']:.1f}/10)."
            )

        lines.append("")
        lines.append(
            "These are patterns from your own entries — not a diagnosis or medical advice. "
            "If you are in crisis, please seek professional help."
        )
        return "\n".join(lines)

    @staticmethod
    def _confidence(count: int) -> dict:
        if count < 7:
            return {
                "confidence": "weak",
                "confidence_label": "Weak",
                "confidence_detail": f"Only {count} check-in(s) — treat links as early guesses.",
            }
        if count < 21:
            return {
                "confidence": "fair",
                "confidence_label": "Fair",
                "confidence_detail": f"{count} check-ins — patterns usable; keep logging toward 30 days.",
            }
        return {
            "confidence": "stronger",
            "confidence_label": "Stronger",
            "confidence_detail": f"{count} check-ins — richer history for correlations.",
        }

    def _reminder(
        self, dated: list[tuple[dict, datetime]], as_of: datetime
    ) -> dict | None:
        if not dated:
            return {
                "level": "soon",
                "title": "Start today",
                "text": "Log today’s mood, sleep, and what happened — patterns need a few weeks.",
            }
        _last_entry, last_dt = dated[-1]
        days_since = (as_of.date() - last_dt.date()).days
        if days_since >= 1 and as_of.hour >= 18:
            return {
                "level": "soon",
                "title": "Check-in reminder",
                "text": (
                    f"Last check-in was {days_since} day(s) ago. "
                    "A short evening log helps the 30-day view."
                ),
            }
        streak = 0
        for entry, _ in reversed(dated):
            if float(entry["mood"]) <= self.low_threshold:
                streak += 1
            else:
                break
        if streak >= 3:
            return {
                "level": "urgent",
                "title": "Low-mood streak",
                "text": (
                    f"{streak} low scores in a row. Review the correlation log and "
                    "consider support from someone you trust or a professional."
                ),
            }
        return None


class MarkovChainPredictor:
    """N-th order Markov chain for coarse mood-context sequences."""

    def __init__(self, order: int = 1):
        if order < 1:
            raise ValueError("Order must be >= 1")
        self.order = order
        self.transition_counts = defaultdict(Counter)
        self.transition_matrix = defaultdict(dict)
        self.states = set()

    def fit(self, sequence):
        if len(sequence) <= self.order:
            return
        self.states.update(sequence)
        self.transition_counts.clear()
        self.transition_matrix.clear()
        for i in range(len(sequence) - self.order):
            history = tuple(sequence[i : i + self.order])
            nxt = sequence[i + self.order]
            self.transition_counts[history][nxt] += 1
        for history, counts in self.transition_counts.items():
            total = sum(counts.values())
            for state, count in counts.items():
                self.transition_matrix[history][state] = count / total

    def predict_distribution(self, current_history):
        history_tuple = tuple(current_history[-self.order :])
        if len(history_tuple) < self.order:
            raise ValueError(f"Need history length >= {self.order}")
        return dict(self.transition_matrix.get(history_tuple, {}))

    def predict_next(self, current_history):
        dist = self.predict_distribution(current_history)
        if not dist:
            return None, 0.0
        best = max(dist, key=dist.get)
        return best, dist[best]

    def simulate_future(self, starting_history, steps=5):
        history = list(starting_history[-self.order :])
        chain = []
        for _ in range(steps):
            dist = self.predict_distribution(history)
            if not dist:
                break
            states, weights = zip(*dist.items())
            nxt = random.choices(states, weights=weights, k=1)[0]
            chain.append(nxt)
            history.append(nxt)
            history = history[-self.order :]
        return chain
