"""Tests for chart data, coach message, and what-helps helpers."""

import re
import unittest
from datetime import date, datetime, timedelta

from mood_engine import MoodPatternAnalyzer


def entry(d, mood, **fields):
    e = {
        "started_at": datetime(d.year, d.month, d.day, 10, 0, 0).strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        "mood": mood,
        "emotions": [],
    }
    e.update(fields)
    return e


BANNED = ("median", "correlation", "p_low", "sequence", "mood-band")


def make_test1_entries():
    # Sparse lows (Nov 5, Nov 15) so exercise days never fall a fixed
    # lag before a low day: exercise must not read as a trigger.
    low_days = {date(2026, 11, 5), date(2026, 11, 15)}
    mom_days = {date(2026, 11, 2), date(2026, 11, 12)}
    exercise_days = {
        date(2026, 11, 7),
        date(2026, 11, 9),
        date(2026, 11, 17),
        date(2026, 11, 19),
    }
    entries = []
    day = date(2026, 11, 1)
    while day <= date(2026, 11, 20):
        if day in low_days:
            mood = 3
        elif day in exercise_days:
            mood = 8
        else:
            mood = 7
        kw = {}
        if day in mom_days:
            kw["talked_to"] = "mom"
        if day in exercise_days:
            kw["events"] = "exercise"
        entries.append(entry(day, mood, **kw))
        day += timedelta(days=1)
    return entries


def make_test2_entries():
    low_days = {date(2026, 11, 5), date(2026, 11, 8)}
    mom_days = {date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 8)}
    entries = []
    day = date(2026, 11, 1)
    while day <= date(2026, 11, 10):
        mood = 3 if day in low_days else 7
        kw = {"talked_to": "mom"} if day in mom_days else {}
        entries.append(entry(day, mood, **kw))
        day += timedelta(days=1)
    return entries


def make_test3_entries():
    entries = []
    # low Nov 1 and Nov 6, good otherwise Nov 2-5 and Nov 7 - Dec 20
    day = date(2026, 11, 1)
    end = date(2026, 12, 20)
    low_days = {date(2026, 11, 1), date(2026, 11, 6)}
    while day <= end:
        if day in low_days:
            mood = 3
        elif day.day % 2 == 0:
            mood = 8
        else:
            mood = 7
        entries.append(entry(day, mood))
        day += timedelta(days=1)
    return entries


class CoachChartTests(unittest.TestCase):
    def test_chart_data(self):
        entries = make_test1_entries()
        as_of = datetime(2026, 11, 21, 22, 0)
        analyzer = MoodPatternAnalyzer()
        chart = analyzer.chart_data(entries, as_of=as_of)
        points = chart["points"]
        self.assertEqual(len(points), 20)
        # date order
        dates = [p["date"] for p in points]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates[0], "2026-11-01")
        self.assertEqual(dates[-1], "2026-11-20")
        mood_by_date = {p["date"]: p["mood"] for p in points}
        self.assertEqual(mood_by_date["2026-11-05"], 3.0)
        self.assertEqual(mood_by_date["2026-11-15"], 3.0)
        self.assertEqual(mood_by_date["2026-11-07"], 8.0)
        self.assertEqual(mood_by_date["2026-11-01"], 7.0)
        markers = chart["markers"]
        self.assertTrue(
            any(m["date"] == "2026-11-02" and m["label"] == "Talking with mom" and m["kind"] == "trigger" for m in markers),
            f"trigger marker missing: {markers}",
        )
        self.assertTrue(
            any(m["date"] == "2026-11-05" and m["label"] == "low day" and m["kind"] == "low" for m in markers),
            f"low marker missing: {markers}",
        )
        self.assertTrue(
            any(m["date"] == "2026-11-07" and m["label"] == "Exercise" and m["kind"] == "helps" for m in markers),
            f"helps marker missing: {markers}",
        )
        # also via report
        report = analyzer.analyze(entries, as_of=as_of)
        self.assertEqual(report["chart_data"], chart)

    def test_coach_heads_up(self):
        entries = make_test2_entries()
        as_of = datetime(2026, 11, 10, 22, 0)
        report = MoodPatternAnalyzer().analyze(entries, as_of=as_of)
        coach = report["coach_message"]
        self.assertIn("Talking with mom", coach)
        self.assertIn("tomorrow", coach)
        for banned in BANNED:
            self.assertNotIn(banned, coach)
        self.assertIsNone(re.search(r"\blift\b", coach))

    def test_coach_encouragement(self):
        entries = make_test3_entries()
        as_of = datetime(2026, 12, 20, 22, 0)
        report = MoodPatternAnalyzer().analyze(entries, as_of=as_of)
        coach = report["coach_message"]
        self.assertIn("longest stretch", coach)
        self.assertIn("No low day in 44 days", coach)
        self.assertNotIn("overdue", coach.lower())

    def test_no_jargon(self):
        scenarios = [
            (make_test1_entries(), datetime(2026, 11, 21, 22, 0)),
            (make_test2_entries(), datetime(2026, 11, 10, 22, 0)),
            (make_test3_entries(), datetime(2026, 12, 20, 22, 0)),
        ]
        for entries, as_of in scenarios:
            report = MoodPatternAnalyzer().analyze(entries, as_of=as_of)
            coach = report["coach_message"]
            for banned in ("median", "correlation", "p_low", "sequence", "mood-band"):
                self.assertNotIn(banned, coach, f"banned {banned} in {coach!r}")
            self.assertIsNone(re.search(r"\blift\b", coach), f"lift in {coach!r}")

    def test_what_helps(self):
        # (a) Test 1 log - exercise helps
        entries1 = make_test1_entries()
        report1 = MoodPatternAnalyzer().analyze(entries1, as_of=datetime(2026, 11, 21, 22, 0))
        coach1 = report1["coach_message"]
        self.assertIn("What helps", coach1)
        self.assertIn("exercise", coach1.lower())
        # (b) Test 2 log - no events
        entries2 = make_test2_entries()
        report2 = MoodPatternAnalyzer().analyze(entries2, as_of=datetime(2026, 11, 10, 22, 0))
        coach2 = report2["coach_message"]
        self.assertNotIn("What helps", coach2)
        self.assertNotIn("Exercise", coach2)


if __name__ == "__main__":
    unittest.main()
