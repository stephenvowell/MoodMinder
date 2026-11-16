"""Tests for the stale-log guard on the low-mood-window reminder.

When the log has gone stale, an overdue low-mood prediction is a false
alarm: the user has had a long good stretch, not a missed warning.
"""

import unittest
from datetime import datetime

from mood_engine import MoodPatternAnalyzer


def entry(date_str, mood, **fields):
    e = {"started_at": f"{date_str}T10:00:00", "mood": mood, "emotions": []}
    e.update(fields)
    return e


class StaleLogReminderTests(unittest.TestCase):
    def test_stale_log_overdue_becomes_good_stretch(self):
        # Mirrors the real stale log: last entry Aug 10, last low Aug 5,
        # median gap 5 days, predicted next low ~Aug 9-10, ~95+ days past.
        entries = [
            entry("2026-07-26", 3),
            entry("2026-07-31", 3),
            entry("2026-08-05", 3),
            entry("2026-08-10", 7),
        ]
        as_of = datetime(2026, 11, 15, 22, 22)
        report = MoodPatternAnalyzer().analyze(entries, as_of=as_of)
        self.assertLess(report["days_until_next_low"], 0)
        reminder = report["reminder"]
        self.assertIsNotNone(reminder)
        self.assertEqual(reminder["level"], "soon")
        self.assertEqual(reminder["title"], "Log is stale — long good stretch")
        self.assertIn("97 day(s) ago", reminder["text"])
        self.assertIn("102 day(s)", reminder["text"])
        self.assertIn("median gap of 5 day(s)", reminder["text"])
        self.assertIn("long good stretch", reminder["text"])

    def test_current_log_genuinely_overdue_still_warns(self):
        entries = [
            entry("2026-10-29", 3),
            entry("2026-11-05", 3),
            entry("2026-11-15", 7),
        ]
        as_of = datetime(2026, 11, 15, 12, 0)
        report = MoodPatternAnalyzer().analyze(entries, as_of=as_of)
        self.assertEqual(report["days_until_next_low"], -3)
        reminder = report["reminder"]
        self.assertIsNotNone(reminder)
        self.assertEqual(reminder["level"], "urgent")
        self.assertEqual(reminder["title"], "Low-mood window overdue")

    def test_soon_case_unchanged(self):
        entries = [
            entry("2026-11-02", 3),
            entry("2026-11-09", 3),
            entry("2026-11-15", 7),
        ]
        as_of = datetime(2026, 11, 15, 12, 0)
        report = MoodPatternAnalyzer().analyze(entries, as_of=as_of)
        self.assertEqual(report["days_until_next_low"], 1)
        reminder = report["reminder"]
        self.assertIsNotNone(reminder)
        self.assertEqual(reminder["level"], "soon")
        self.assertEqual(reminder["title"], "Low-mood window soon")


if __name__ == "__main__":
    unittest.main()
