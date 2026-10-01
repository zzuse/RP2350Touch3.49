#!/usr/bin/env python3
"""Tests for the history stats in claude_usage_host.py.

    python3 tools/test_claude_usage_host.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_usage_host as host  # noqa: E402

UTC = timezone.utc


def at(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


class StreakTest(unittest.TestCase):
    def test_current_and_longest(self):
        d = date(2026, 9, 30)
        active = {d - timedelta(days=i) for i in range(3)} | {date(2026, 9, 1) + timedelta(days=i) for i in range(5)}
        self.assertEqual(host.streaks(active, d), (3, 5))

    def test_today_without_usage_yet_keeps_streak(self):
        d = date(2026, 9, 30)
        active = {d - timedelta(days=i) for i in range(1, 4)}
        self.assertEqual(host.streaks(active, d), (3, 3))

    def test_broken_streak(self):
        d = date(2026, 9, 30)
        self.assertEqual(host.streaks({d - timedelta(days=2)}, d), (0, 1))
        self.assertEqual(host.streaks(set(), d), (0, 0))


class HeatmapTest(unittest.TestCase):
    def test_starts_on_monday_and_ends_today(self):
        today = date(2026, 10, 1)      # a Thursday
        levels, top = host.heatmap({}, today, weeks=16)
        self.assertEqual(len(levels), 7 * 15 + 4)
        self.assertEqual(top, 0)
        start = today - timedelta(days=len(levels) - 1)
        self.assertEqual(start.weekday(), 0)

    def test_levels(self):
        today = date(2026, 10, 1)
        daily = {today.isoformat(): 100, (today - timedelta(days=1)).isoformat(): 1,
                 (today - timedelta(days=2)).isoformat(): 60}
        levels, top = host.heatmap(daily, today, weeks=1)
        self.assertEqual(top, 100)
        self.assertEqual(levels, "0314")


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "history.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_longest_task_splits_on_pauses(self):
        h = host.History(None)
        # 09:00-10:00 in steps of 20 min, then a 2-hour pause, then 12:00-12:10
        for m in (0, 20, 40, 60):
            h.add(at(10, 9) + timedelta(minutes=m), 10, "a")
        h.add(at(10, 12), 10, "a")
        h.add(at(10, 12, 10), 10, "a")
        # Another session interleaved doesn't join the first
        h.add(at(10, 9, 30), 10, "b")
        self.assertEqual(h.longest_task()[0], 3600)

    def test_saved_days_survive_deleted_logs(self):
        h = host.History(self.path)
        h.add(at(1, 12), 500, "a")
        h.add(at(2, 12), 700, "a")
        self.assertTrue(h.save())
        self.assertFalse(h.save())      # unchanged

        # A later run where day 1's log is gone and day 2 has grown
        h2 = host.History(self.path)
        h2.add(at(2, 13), 900, "b")
        daily = h2.daily()
        self.assertEqual(daily[at(1, 12).astimezone().date().isoformat()], 500)
        self.assertEqual(daily[at(2, 13).astimezone().date().isoformat()], 900)

    def test_stats_fields(self):
        h = host.History(None)
        h.add(at(28, 12), 100, "a")
        h.add(at(29, 12), 300, "a")
        h.add(at(30, 12), 200, "a")
        s = host.history_stats(h, today=date(2026, 9, 30))
        self.assertEqual(s["tot"], 600)
        self.assertEqual(s["hdt"], 300)
        self.assertEqual(s["cs"], 3)
        line = host.encode(s, "@CS")
        self.assertTrue(line.startswith("@CS tot=600;"))
        self.assertLess(len(line), 511)     # the board's line buffer

    def test_corrupt_file_is_ignored(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        h = host.History(self.path)
        self.assertEqual(h.daily(), {})
        h.add(at(1, 12), 5, "a")
        self.assertTrue(h.save())
        with open(self.path) as f:
            self.assertEqual(json.load(f)["version"], 1)


if __name__ == "__main__":
    unittest.main()
