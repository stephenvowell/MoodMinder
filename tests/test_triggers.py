"""Tests for the top-triggers section in the report message."""

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


AS_OF = datetime(2026, 11, 15, 22, 0)

BANNED = ("p_low", "correlation", "median gap", "mood-band", "streak")
BANNED_WORDS = (r"\blift\b",)


def assert_no_jargon(test, msg):
    for banned in BANNED:
        test.assertNotIn(banned, msg)
    for pattern in BANNED_WORDS:
        test.assertIsNone(re.search(pattern, msg), f"found {pattern!r} in message")


class TriggerTests(unittest.TestCase):
    def test_lag3_trigger_in_plain_words(self):
        # Low days every 3 days; "talked to mom" 3 days before each low day.
        low_days = {
            date(2026, 11, 5),
            date(2026, 11, 8),
            date(2026, 11, 11),
            date(2026, 11, 14),
        }
        mom_days = {
            date(2026, 11, 2),
            date(2026, 11, 5),
            date(2026, 11, 8),
            date(2026, 11, 11),
        }
        entries = []
        day = date(2026, 11, 1)
        while day <= date(2026, 11, 14):
            mood = 3 if day in low_days else 7
            kw = {"talked_to": "mom"} if day in mom_days else {}
            entries.append(entry(day, mood, **kw))
            day += timedelta(days=1)
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        msg = report["message"]
        self.assertIn("What seems to trigger low days:", msg)
        self.assertIn(
            "Talking with mom 3 days before a low day: low 4 out of 4 times.",
            msg,
        )
        # The same factor must not also appear as a same-day trigger.
        self.assertEqual(msg.count("Talking with mom"), 1)
        # The top_triggers field carries the plain dicts.
        self.assertEqual(len(report["top_triggers"]), 1)
        self.assertEqual(report["top_triggers"][0]["lag"], 3)
        self.assertEqual(report["top_triggers"][0]["low_count"], 4)
        self.assertEqual(report["top_triggers"][0]["count"], 4)
        assert_no_jargon(self, msg)

    def test_no_passing_factor_means_no_clear_triggers_line(self):
        # Low days exist, but "mom" shows up mostly on good days.
        low_days = {
            date(2026, 11, 5),
            date(2026, 11, 8),
            date(2026, 11, 11),
            date(2026, 11, 14),
        }
        mom_days = {
            date(2026, 11, 1),
            date(2026, 11, 2),
            date(2026, 11, 3),
            date(2026, 11, 4),
        }
        entries = []
        day = date(2026, 11, 1)
        while day <= date(2026, 11, 14):
            mood = 3 if day in low_days else 7
            kw = {"talked_to": "mom"} if day in mom_days else {}
            entries.append(entry(day, mood, **kw))
            day += timedelta(days=1)
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        msg = report["message"]
        self.assertEqual(report["top_triggers"], [])
        self.assertIn("No clear triggers found yet", msg)
        self.assertNotIn("Talking with mom", msg)
        assert_no_jargon(self, msg)

    def test_trigger_message_has_no_jargon(self):
        # Same-day trigger: feeling anxious on most low days.
        entries = []
        day = date(2026, 11, 1)
        # Irregular low days so the same-day factor does NOT also pass
        # as a lagged (1-3 day) factor.
        low_days = {
            date(2026, 11, 3),
            date(2026, 11, 5),
            date(2026, 11, 9),
            date(2026, 11, 13),
        }
        while day <= date(2026, 11, 14):
            mood = 3 if day in low_days else 7
            kw = {"emotions": ["anxious"]} if day in low_days else {}
            entries.append(entry(day, mood, **kw))
            day += timedelta(days=1)
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        msg = report["message"]
        self.assertIn("Feeling anxious: low 4 out of 4 times.", msg)
        assert_no_jargon(self, msg)


if __name__ == "__main__":
    unittest.main()
