"""Tests for lagged (1-3 day) factor correlation in MoodMinder."""

import unittest
from datetime import datetime

from mood_engine import MoodPatternAnalyzer


def entry(day, mood, **fields):
    e = {"started_at": "2026-08-%02dT10:00:00" % day, "mood": mood, "emotions": []}
    e.update(fields)
    return e


AS_OF = datetime(2026, 8, 15)


class LaggedCorrelationTests(unittest.TestCase):
    def test_lag3_talked_to_mom_precedes_low_days(self):
        entries = [
            entry(1, 6, talked_to="mom"),
            entry(2, 6, talked_to="mom"),
            entry(3, 6, talked_to="mom"),
            entry(4, 3, talked_to="mom"),
            entry(5, 3, talked_to="dad"),
            entry(6, 3, talked_to="dad"),
            entry(7, 3, talked_to="dad"),
            entry(8, 8, talked_to="dad"),
            entry(9, 8, talked_to="dad"),
            entry(10, 8, talked_to="dad"),
        ]
        report = MoodPatternAnalyzer().analyze(entries, as_of=AS_OF)
        lagged = report["lagged_factor_stats"]
        mom = [
            s for s in lagged
            if s["lag"] == 3 and s["category"] == "talked_to" and s["value"] == "mom"
        ]
        self.assertEqual(len(mom), 1)
        self.assertEqual(mom[0]["low_count"], 4)
        self.assertEqual(mom[0]["count"], 4)
        self.assertAlmostEqual(mom[0]["p_low"], 1.0)

    def test_same_day_factor_not_a_lag3_hit(self):
        entries = [
            entry(1, 6, food="salad"),
            entry(2, 6, food="salad"),
            entry(3, 6, food="salad"),
            entry(4, 3, food="pizza"),
            entry(5, 3, food="pizza"),
            entry(6, 3, food="pizza"),
        ]
        analyzer = MoodPatternAnalyzer()
        report = analyzer.analyze(entries, as_of=AS_OF)
        # sanity: pizza IS a same-day correlate of low mood
        same = [
            s for s in report["factor_stats"]
            if s["category"] == "food" and s["value"] == "pizza"
        ]
        self.assertTrue(same and same[0]["p_low"] == 1.0)
        # but pizza never appears 3 days before a low day
        lagged_pizza = [
            s for s in report["lagged_factor_stats"]
            if s["lag"] == 3 and s["category"] == "food" and s["value"] == "pizza"
        ]
        self.assertEqual(lagged_pizza, [])

    def test_empty_and_single_entry_logs(self):
        analyzer = MoodPatternAnalyzer()
        self.assertEqual(
            analyzer.analyze([], as_of=AS_OF)["lagged_factor_stats"], []
        )
        single = analyzer.analyze(
            [entry(1, 5, talked_to="mom")], as_of=AS_OF
        )
        self.assertEqual(single["lagged_factor_stats"], [])

    def test_explain_mood_mentions_lagged_factors(self):
        entries = [
            entry(1, 6, talked_to="mom"),
            entry(2, 6, talked_to="mom"),
            entry(3, 6, talked_to="mom"),
            entry(4, 3, talked_to="mom"),
            entry(5, 3, talked_to="dad"),
            entry(6, 3, talked_to="dad"),
            entry(7, 3, talked_to="dad"),
            entry(8, 8, talked_to="dad"),
        ]
        analyzer = MoodPatternAnalyzer()
        text = analyzer.explain_mood(entries[3], entries)
        self.assertIn("1-3 days earlier", text)
        self.assertIn("mom", text)
        # a log with no lagged pattern says so plainly
        lone = entry(1, 3, talked_to="mom")
        plain = analyzer.explain_mood(lone, [lone])
        self.assertIn("No delayed patterns found yet", plain)


if __name__ == "__main__":
    unittest.main()
