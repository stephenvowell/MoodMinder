"""Tests for the plain-language report message in MoodMinder."""

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


def daily_entries(start, end, low_days, low_mood=3, mid_mood=7):
    """One entry per day from start to end; low mood on low_days."""
    entries = []
    day = start
    while day <= end:
        entries.append(entry(day, low_mood if day in low_days else mid_mood))
        day += timedelta(days=1)
    return entries


AS_OF = datetime(2026, 11, 15, 22, 0)

BANNED_JARGON = ("median gap", "mood-band", "sequence guess", "streak")


class ReportMessageTests(unittest.TestCase):
    def test_stephens_case_long_stretch_not_overdue(self):
        # Mirrors Stephen's real log: last low Aug 5, median gap 5 days,
        # last check-in today (Nov 15), predicted next low 95 days past.
        low_days = {
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 26),
            date(2026, 8, 4),
            date(2026, 8, 5),
        }
        entries = daily_entries(date(2026, 7, 12), date(2026, 8, 10), low_days)
        entries.append(entry(date(2026, 11, 15), 10))
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        self.assertEqual(report["days_since_last_low"], 102)
        self.assertEqual(report["median_low_gap_days"], 5)
        self.assertEqual(report["days_until_next_low"], -95)
        msg = report["message"]
        self.assertNotIn("overdue", msg.lower())
        self.assertIn("No low day in 102 days", msg)
        self.assertIn("about 5 days", msg)

    def test_genuinely_overdue_current_log_warns_plainly(self):
        low_days = {date(2026, 10, 28), date(2026, 11, 2), date(2026, 11, 7)}
        entries = daily_entries(date(2026, 10, 28), date(2026, 11, 15), low_days)
        entries[-1]["mood"] = 8  # today's check-in is good
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        self.assertLess(report["days_until_next_low"], 0)
        msg = report["message"]
        self.assertIn("was expected", msg)
        self.assertNotIn("long good stretch", msg)

    def test_averages_state_their_count(self):
        entries = [entry(date(2026, 11, 15), 8)]
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        msg = report["message"]
        self.assertIn("Last 7 days: 8.0 out of 10 (from 1 check-in)", msg)
        self.assertIn("Last 30 days: 8.0 out of 10 (from 1 check-in)", msg)

    def test_message_has_no_jargon(self):
        low_days = {
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 26),
            date(2026, 8, 4),
            date(2026, 8, 5),
        }
        entries = daily_entries(date(2026, 7, 12), date(2026, 8, 10), low_days)
        entries.append(entry(date(2026, 11, 15), 10))
        msg1 = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)["message"]
        low_days2 = {date(2026, 10, 28), date(2026, 11, 2), date(2026, 11, 7)}
        entries2 = daily_entries(date(2026, 10, 28), date(2026, 11, 15), low_days2)
        entries2[-1]["mood"] = 8
        msg2 = MoodPatternAnalyzer().analyze(entries2, as_of=AS_OF)["message"]
        for msg in (msg1, msg2):
            for banned in BANNED_JARGON:
                self.assertNotIn(banned, msg)


    def test_next_low_text_field(self):
        low_days = {
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 26),
            date(2026, 8, 4),
            date(2026, 8, 5),
        }
        entries = daily_entries(date(2026, 7, 12), date(2026, 8, 10), low_days)
        entries.append(entry(date(2026, 11, 15), 10))
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        self.assertIn("No low day in 102 days", report["next_low_text"])
        self.assertNotIn("overdue", report["next_low_text"].lower())
        low_days2 = {date(2026, 10, 28), date(2026, 11, 2), date(2026, 11, 7)}
        entries2 = daily_entries(date(2026, 10, 28), date(2026, 11, 15), low_days2)
        entries2[-1]["mood"] = 8
        report2 = MoodPatternAnalyzer().analyze(entries2, as_of=AS_OF)
        self.assertIn("was expected", report2["next_low_text"])


if __name__ == "__main__":
    unittest.main()
