"""Mood Minder analysis engine — patterns, correlates, explanations."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
import random

LOW_MOOD_THRESHOLD = 4
HIGH_MOOD_THRESHOLD = 7
POOR_SLEEP_HOURS = 6.0
# A log with no check-in for longer than this is treated as stale:
# timing estimates (e.g. "low-mood window overdue") are not trustworthy.
STALE_LOG_DAYS = 7

# Single source of truth for the app version (semantic versioning).
# Bump this one constant for a new release; app.py reads it from here.
VERSION = "1.0.2"

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
            "count_7": 0,
            "count_30": 0,
            "avg_all": None,
            "low_count": 0,
            "high_count": 0,
            "confidence": "none",
            "confidence_label": "No data",
            "confidence_detail": "Log check-ins with a mood score to begin.",
            "factor_stats": [],
            "lagged_factor_stats": [],
            "sleep_buckets": {},
            "emotion_low": Counter(),
            "emotion_high": Counter(),
            "mood_series": [],
            "depression_events": [],
            "reminder": None,
            "message": "",
            "baseline_low_rate": 0.0,
            # Gap / timing estimates (like HumanPredict days-until)
            "low_gaps_days": [],
            "avg_low_gap_days": None,
            "median_low_gap_days": None,
            "min_low_gap_days": None,
            "max_low_gap_days": None,
            "last_low": None,
            "days_since_last_low": None,
            "days_since_last_checkin": None,
            "predicted_next_low": None,
            "days_until_next_low": None,
            "overdue_low_days": None,
            "next_low_text": None,
            "top_triggers": [],
            "recovery_gaps_days": [],
            "median_recovery_days": None,
            "avg_recovery_days": None,
            "days_until_typical_recovery": None,
            "change_gaps_days": [],
            "median_change_gap_days": None,
            "days_until_mood_change": None,
            "predicted_next_change": None,
            "current_mood_band": None,
            "days_in_current_band": None,
            "next_mood_band": None,
            "next_mood_band_prob": None,
            "typical_low_weekday": None,
        }

        if not dated:
            report["message"] = "Add a check-in with mood, sleep, and daily context to start."
            return report

        moods = [float(e["mood"]) for e, _ in dated]
        report["avg_all"] = mean(moods)
        report["low_count"] = sum(1 for m in moods if m <= self.low_threshold)
        report["high_count"] = sum(1 for m in moods if m >= self.high_threshold)
        report["baseline_low_rate"] = report["low_count"] / len(moods)

        def avg_since(days: int) -> tuple[float | None, int]:
            cutoff = as_of - timedelta(days=days)
            vals = [float(e["mood"]) for e, dt in dated if dt >= cutoff]
            return (mean(vals), len(vals)) if vals else (None, 0)

        report["avg_7"], report["count_7"] = avg_since(7)
        report["avg_30"], report["count_30"] = avg_since(30)
        report["days_since_last_checkin"] = (as_of.date() - dated[-1][1].date()).days

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

        # Lagged (delayed) correlation: factors from 1-3 days earlier
        # that often precede low days (e.g. a conversation whose effect
        # shows up a few days later).
        by_date = defaultdict(list)
        for _entry, _dt in dated:
            by_date[_dt.date()].append(_entry)
        low_dates = {
            _dt.date()
            for _entry, _dt in dated
            if float(_entry["mood"]) <= self.low_threshold
        }
        lagged_stats = []
        for lag in (1, 2, 3):
            lag_total = Counter()
            lag_low = Counter()
            lag_dates = defaultdict(list)
            for day in sorted(by_date):
                prev = day - timedelta(days=lag)
                if prev not in by_date:
                    continue
                day_factors = set()
                for prev_entry in by_date[prev]:
                    day_factors.update(extract_factors(prev_entry))
                is_low = day in low_dates
                for cat, val in day_factors:
                    key = (cat, val)
                    lag_total[key] += 1
                    if is_low:
                        lag_low[key] += 1
                        lag_dates[key].append(day.strftime("%Y-%m-%d"))
            for key, total in lag_total.items():
                if total < 2:
                    continue
                low_n = lag_low[key]
                p_low = low_n / total
                lift = (p_low / baseline) if baseline > 0 else 0.0
                cat, val = key
                lagged_stats.append(
                    {
                        "lag": lag,
                        "category": cat,
                        "value": val,
                        "count": total,
                        "low_count": low_n,
                        "p_low": p_low,
                        "lift": lift,
                        "dates": sorted(set(lag_dates[key])),
                    }
                )
        lagged_stats.sort(
            key=lambda s: (s["p_low"], s["low_count"], s["lift"]), reverse=True
        )
        report["lagged_factor_stats"] = lagged_stats

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

        self._fill_timing_estimates(report, dated, as_of)
        report["next_low_text"] = self._next_low_sentence(report)
        report["top_triggers"] = self._top_triggers(report)
        report.update(self._confidence(len(dated), report))
        report["reminder"] = self._reminder(dated, as_of, report)
        report["message"] = self._build_message(report)

        return report

    def _fill_timing_estimates(
        self,
        report: dict,
        dated: list[tuple[dict, datetime]],
        as_of: datetime,
    ) -> None:
        """Gaps between low days, recovery time, and days until mood band changes."""
        low_dates: list[datetime] = []
        seen_low_days: set[str] = set()
        for entry, dt in dated:
            if float(entry["mood"]) > self.low_threshold:
                continue
            key = dt.strftime("%Y-%m-%d")
            if key in seen_low_days:
                continue
            seen_low_days.add(key)
            low_dates.append(dt)

        if low_dates:
            report["last_low"] = low_dates[-1]
            report["days_since_last_low"] = (as_of.date() - low_dates[-1].date()).days
            dow = Counter(day_of_week_label(dt) for dt in low_dates)
            report["typical_low_weekday"] = dow.most_common(1)[0][0]

        gaps = [
            (later.date() - earlier.date()).days
            for earlier, later in zip(low_dates, low_dates[1:])
            if (later.date() - earlier.date()).days > 0
        ]
        report["low_gaps_days"] = gaps
        if gaps:
            report["avg_low_gap_days"] = mean(gaps)
            report["median_low_gap_days"] = median(gaps)
            report["min_low_gap_days"] = min(gaps)
            report["max_low_gap_days"] = max(gaps)
            gap = report["median_low_gap_days"]
            predicted = low_dates[-1].date() + timedelta(days=int(round(gap)))
            if report["typical_low_weekday"]:
                predicted = self._nudge_to_weekday(
                    predicted, report["typical_low_weekday"], within_days=2
                )
            report["predicted_next_low"] = datetime.combine(
                predicted, datetime.min.time()
            )
            delta = (predicted - as_of.date()).days
            report["days_until_next_low"] = delta
            if delta < 0:
                report["overdue_low_days"] = abs(delta)

        # Days from a low day until mood rises above the low threshold
        recovery = []
        for i, (entry, dt) in enumerate(dated):
            if float(entry["mood"]) > self.low_threshold:
                continue
            for later_entry, later_dt in dated[i + 1 :]:
                if float(later_entry["mood"]) > self.low_threshold:
                    days = (later_dt.date() - dt.date()).days
                    if days >= 0:
                        recovery.append(max(days, 1) if days == 0 else days)
                    break
        report["recovery_gaps_days"] = recovery
        if recovery:
            report["median_recovery_days"] = median(recovery)
            report["avg_recovery_days"] = mean(recovery)
            if report["days_since_last_low"] is not None:
                last_mood = float(dated[-1][0]["mood"])
                if last_mood <= self.low_threshold:
                    left = int(round(report["median_recovery_days"])) - int(
                        report["days_since_last_low"]
                    )
                    report["days_until_typical_recovery"] = left

        # How long each mood-band streak lasts → days until current band ends
        streaks: list[tuple[str, int, datetime, datetime]] = []
        # (band, length_days, start_dt, end_dt)
        cur_band = None
        streak_start = None
        streak_end = None
        for entry, dt in dated:
            band = mood_band(entry.get("mood"))
            if cur_band is None:
                cur_band, streak_start, streak_end = band, dt, dt
                continue
            if band == cur_band:
                streak_end = dt
                continue
            length = max(1, (streak_end.date() - streak_start.date()).days + 1)
            streaks.append((cur_band, length, streak_start, streak_end))
            cur_band, streak_start, streak_end = band, dt, dt
        if cur_band is not None and streak_start is not None:
            length = max(1, (streak_end.date() - streak_start.date()).days + 1)
            streaks.append((cur_band, length, streak_start, streak_end))

        completed = streaks[:-1] if len(streaks) > 1 else []
        report["change_gaps_days"] = [length for _, length, _, _ in completed]
        if streaks:
            current_band, current_len, cur_start, _cur_end = streaks[-1]
            same_band_lens = [length for band, length, _, _ in completed if band == current_band]
            # Fall back to all completed streak lengths if this band is rare
            pool = same_band_lens or report["change_gaps_days"]
            if pool:
                report["median_change_gap_days"] = median(pool)
                typical = int(round(report["median_change_gap_days"]))
                days_into = max(1, (as_of.date() - cur_start.date()).days + 1)
                # Prefer calendar days into the open streak vs check-in count
                days_into = max(days_into, current_len)
                left = typical - days_into
                predicted_change = as_of.date() + timedelta(days=max(left, 0))
                report["predicted_next_change"] = datetime.combine(
                    predicted_change, datetime.min.time()
                )
                report["days_until_mood_change"] = left
                report["current_mood_band"] = current_band
                report["days_in_current_band"] = days_into

        # Markov next mood band from recent history
        sequence = [mood_band(e.get("mood")) for e, _ in dated]
        if len(sequence) >= 3:
            model = MarkovChainPredictor(order=1)
            model.fit(sequence)
            nxt, prob = model.predict_next(sequence)
            if nxt:
                report["next_mood_band"] = nxt
                report["next_mood_band_prob"] = prob

    @staticmethod
    def _nudge_to_weekday(day, weekday_label: str, within_days: int = 2):
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        try:
            target = labels.index(weekday_label)
        except ValueError:
            return day
        best = day
        best_dist = abs(day.weekday() - target)
        for offset in range(-within_days, within_days + 1):
            candidate = day + timedelta(days=offset)
            dist = abs(candidate.weekday() - target)
            if dist < best_dist or (dist == best_dist and abs(offset) < abs((best - day).days)):
                best = candidate
                best_dist = dist
        return best

    def _next_low_sentence(self, report: dict) -> str | None:
        """Plain-language next-low-day sentence, or None if not estimable.

        A predicted date far in the past is not called "overdue" when the
        last low day was long ago (a long good stretch) or the log is stale.
        """
        d = report.get("days_until_next_low")
        if d is None:
            return None
        days_since_low = report.get("days_since_last_low")
        median_gap = report.get("median_low_gap_days")
        days_since_checkin = report.get("days_since_last_checkin")
        long_stretch = (
            days_since_low is not None
            and median_gap
            and days_since_low > 3 * median_gap
        )
        stale_log = (
            days_since_checkin is not None
            and days_since_checkin > STALE_LOG_DAYS
        )
        if d < 0 and (long_stretch or stale_log):
            gap_bit = (
                f", well past your usual gap of about {median_gap:.0f} days"
                if median_gap
                else ""
            )
            if days_since_low is not None:
                n = int(days_since_low)
                return (
                    f"No low day in {n} day{'s' if n != 1 else ''}{gap_bit} — "
                    "a long good stretch."
                )
            return "No low day for a long stretch."
        if d < 0:
            n = abs(int(d))
            return f"A low day was expected about {n} day{'s' if n != 1 else ''} ago."
        if d == 0:
            return "A low day may come today."
        n = int(d)
        return f"Your next low day is likely in about {n} day{'s' if n != 1 else ''}."

    @staticmethod
    def _factor_words(category: str, value: str) -> str:
        """Plain words for one (category, value) factor - no jargon."""
        value = str(value).strip()
        if category == "talked_to":
            return f"Talking with {value}"
        if category == "talked_about":
            return f"Talking about {value}"
        if category == "emotion":
            return f"Feeling {value}"
        if category == "location":
            return f"Being at {value}"
        if category == "ate_with":
            return f"Eating with {value}"
        if category == "sleep_quality":
            return f"Sleep rated {value}"
        if category == "sleep":
            return {
                "under_6h": "Sleep under 6 hours",
                "8h_plus": "Sleep 8 hours or more",
                "6_to_8h": "Sleep 6 to 8 hours",
            }.get(value, f"Sleep {value}")
        if category == "food":
            return f"Eating {value}"
        if category == "event":
            return value[:1].upper() + value[1:] if value else value
        return f"{category} {value}".strip()

    def _top_triggers(self, report: dict) -> list[dict]:
        """Top 3 triggers in plain words: lagged (1-3 days) first, then same-day.

        A factor counts only when it shows up at least twice and low days
        follow it at least half the time and more often than usual.
        Returns plain dicts with a ready-made sentence in "text".
        """
        picked: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def consider(stat: dict, lag: int | None) -> None:
            if stat["count"] < 2:
                return
            if stat["p_low"] < 0.5:
                return
            if stat["lift"] <= 1:
                return
            key = (stat["category"], stat["value"])
            if key in seen:
                return
            seen.add(key)
            words = self._factor_words(stat["category"], stat["value"])
            low_n = int(stat["low_count"])
            total = int(stat["count"])
            if lag is None:
                text = f"{words}: low {low_n} out of {total} times."
            else:
                day_word = "day" if lag == 1 else "days"
                text = (
                    f"{words} {lag} {day_word} before a low day: "
                    f"low {low_n} out of {total} times."
                )
            picked.append(
                {
                    "lag": lag,
                    "category": stat["category"],
                    "value": stat["value"],
                    "count": total,
                    "low_count": low_n,
                    "text": text,
                }
            )

        for stat in report.get("lagged_factor_stats") or []:
            consider(stat, stat["lag"])
            if len(picked) >= 3:
                break
        if len(picked) < 3:
            for stat in report.get("factor_stats") or []:
                consider(stat, None)
                if len(picked) >= 3:
                    break
        return picked

    def _build_message(self, report: dict) -> str:
        """Plain-language summary of the report — short sentences, no jargon."""

        def days(n: int) -> str:
            n = int(n)
            return f"{n} day" if n == 1 else f"{n} days"

        parts = []
        if report.get("days_until_mood_change") is not None:
            d = report["days_until_mood_change"]
            band = report.get("current_mood_band") or "current"
            into = report.get("days_in_current_band")
            gap = report.get("median_change_gap_days")
            if d < 0:
                if into is not None:
                    parts.append(
                        f"Your mood is due for a change — it has been {band} "
                        f"for {days(into)}."
                    )
                else:
                    parts.append("Your mood is due for a change.")
            elif d == 0:
                parts.append("Your mood may change today.")
            elif gap:
                parts.append(f"Your mood usually changes about every {gap:.0f} days.")
            else:
                parts.append(f"Your mood may change in about {days(d)}.")
        if report.get("next_low_text"):
            parts.append(report["next_low_text"])
        elif report.get("low_count", 0) == 1:
            parts.append(
                "Only one low-mood day so far — log another to estimate days until the next."
            )
        if report.get("days_until_typical_recovery") is not None:
            r = report["days_until_typical_recovery"]
            if r <= 0:
                parts.append(
                    "After a low day, your mood usually lifts within about a day — "
                    "that time has passed."
                )
            else:
                parts.append(
                    f"After a low day, your mood usually lifts in about {days(r)}."
                )
        elif report.get("median_recovery_days") is not None:
            med = report["median_recovery_days"]
            parts.append(
                f"After a low day, your mood usually lifts within about {med:.0f} "
                f"{'day' if round(med) == 1 else 'days'}."
            )
        if report.get("next_mood_band"):
            band = report["next_mood_band"]
            prob = report.get("next_mood_band_prob")
            if prob:
                parts.append(
                    f"Your next check-in will most likely be {band} "
                    f"(about {prob:.0%} likely)."
                )
            else:
                parts.append(f"Your next check-in will most likely be {band}.")
        if report.get("avg_7") is not None:
            n = report.get("count_7") or 0
            word = "check-in" if n == 1 else "check-ins"
            parts.append(
                f"Last 7 days: {report['avg_7']:.1f} out of 10 (from {n} {word})."
            )
        if report.get("avg_30") is not None:
            n = report.get("count_30") or 0
            word = "check-in" if n == 1 else "check-ins"
            parts.append(
                f"Last 30 days: {report['avg_30']:.1f} out of 10 (from {n} {word})."
            )
        if report.get("low_count", 0):
            n = report["low_count"]
            parts.append(f"{n} low {'day' if n == 1 else 'days'} in total.")
        if report.get("low_count", 0) >= 1:
            triggers = report.get("top_triggers") or []
            if triggers:
                trigger_text = " ".join(t["text"] for t in triggers)
                parts.append(f"What seems to trigger low days: {trigger_text}")
            else:
                parts.append(
                    "No clear triggers found yet - keep logging and the "
                    "picture will sharpen."
                )
        if not parts:
            return f"{report.get('count', 0)} check-in(s) logged."
        return " ".join(parts)

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


        lines.append("")
        lines.append("Factors from 1-3 days earlier that often precede low days:")
        lagged_matches = []
        if dt is not None:
            lagged_stats = report.get("lagged_factor_stats") or []
            by_lag_day = defaultdict(list)
            for other in entries:
                other_dt = parse_entry_datetime(other)
                if other_dt is not None:
                    by_lag_day[other_dt.date()].append(other)
            seen = set()
            for lag in (1, 2, 3):
                prev = dt.date() - timedelta(days=lag)
                for prev_entry in by_lag_day.get(prev, []):
                    for cat, val in extract_factors(prev_entry):
                        match = next(
                            (
                                s
                                for s in lagged_stats
                                if s["lag"] == lag
                                and s["category"] == cat
                                and s["value"] == val
                            ),
                            None,
                        )
                        if match and (lag, cat, val) not in seen:
                            seen.add((lag, cat, val))
                            lagged_matches.append(match)
            lagged_matches.sort(
                key=lambda s: (s["p_low"], s["low_count"]), reverse=True
            )
        if lagged_matches:
            for s in lagged_matches[:3]:
                lines.append(
                    f"  \u00b7 {s['lag']} day(s) earlier \u2014 {s['category']}: {s['value']} "
                    f"(low on {s['p_low']:.0%} of days with this)"
                )
        else:
            lines.append("  \u00b7 No delayed patterns found yet for this day.")

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
    def _confidence(count: int, report: dict | None = None) -> dict:
        report = report or {}
        gaps = report.get("low_gaps_days") or []
        if count < 7 or len(gaps) < 1:
            return {
                "confidence": "weak",
                "confidence_label": "Weak",
                "confidence_detail": (
                    f"Only {count} check-in(s) / {len(gaps)} low-day gap(s) — "
                    "treat timing and links as early guesses."
                ),
            }
        spread = (max(gaps) - min(gaps)) if gaps else 0
        if count < 21 or len(gaps) < 3:
            return {
                "confidence": "fair",
                "confidence_label": "Fair",
                "confidence_detail": (
                    f"{count} check-ins, {len(gaps)} low-day gap(s) "
                    f"(spread {spread}d) — usable; keep logging."
                ),
            }
        return {
            "confidence": "stronger",
            "confidence_label": "Stronger",
            "confidence_detail": (
                f"{count} check-ins, {len(gaps)} low-day gap(s) — "
                "richer history for correlations and timing."
            ),
        }

    def _reminder(
        self,
        dated: list[tuple[dict, datetime]],
        as_of: datetime,
        report: dict | None = None,
    ) -> dict | None:
        report = report or {}
        if not dated:
            return {
                "level": "soon",
                "title": "Start today",
                "text": "Log today’s mood, sleep, and what happened — patterns need a few weeks.",
            }
        days_until_low = report.get("days_until_next_low")
        if days_until_low is not None and days_until_low <= 2:
            if days_until_low < 0:
                days_since_checkin = (as_of.date() - dated[-1][1].date()).days
                if days_since_checkin > STALE_LOG_DAYS:
                    days_since_low = report.get("days_since_last_low")
                    median_gap = report.get("median_low_gap_days")
                    low_bit = (
                        f"No low day in {days_since_low} day(s)"
                        if days_since_low is not None
                        else "No recent low day"
                    )
                    gap_bit = (
                        f", well past the usual median gap of {median_gap:.0f} day(s)"
                        if median_gap is not None
                        else ""
                    )
                    return {
                        "level": "soon",
                        "title": "Log is stale \u2014 long good stretch",
                        "text": (
                            f"Last check-in was {days_since_checkin} day(s) ago. "
                            f"{low_bit}{gap_bit} \u2014 a long good stretch. "
                            "Log today to refresh the timing estimates."
                        ),
                    }
                days_since_low = report.get("days_since_last_low")
                median_gap = report.get("median_low_gap_days")
                if (
                    days_since_low is not None
                    and median_gap
                    and days_since_low > 3 * median_gap
                ):
                    return {
                        "level": "soon",
                        "title": "Long good stretch",
                        "text": (
                            f"No low day in {days_since_low} day(s), well past "
                            f"your usual gap of about {median_gap:.0f} days — "
                            "a long good stretch."
                        ),
                    }
                return {
                    "level": "urgent",
                    "title": "Low-mood window overdue",
                    "text": (
                        f"Past gaps suggest a low-mood window may already be overdue "
                        f"by ~{abs(days_until_low)} day(s). Review correlates and support options."
                    ),
                }
            return {
                "level": "soon",
                "title": "Low-mood window soon",
                "text": (
                    f"Based on your gaps, the next low-mood day is estimated in about "
                    f"{days_until_low} day(s). Sleep and alone time often show up in your log."
                ),
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
