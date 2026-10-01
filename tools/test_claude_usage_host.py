#!/usr/bin/env python3
"""Tests for the history stats in claude_usage_host.py.

    python3 tools/test_claude_usage_host.py
"""

import builtins
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
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

    def test_bare_file_name(self):
        # --history-file history.json: no directory part
        cwd = os.getcwd()
        os.chdir(self.dir.name)
        try:
            h = host.History("history.json")
            h.add(at(1, 12), 5, "a")
            self.assertTrue(h.save())
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.exists(self.path))

    def test_corrupt_file_is_ignored(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        h = host.History(self.path)
        self.assertEqual(h.daily(), {})
        h.add(at(1, 12), 5, "a")
        self.assertTrue(h.save())
        with open(self.path) as f:
            self.assertEqual(json.load(f)["version"], 1)


class FakeBoard:
    def __init__(self):
        self.sent = []

    def send(self, line):
        self.sent.append(line)


class PlayerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        # A hang would be the bug; fail instead of blocking the test run
        signal.signal(signal.SIGALRM, lambda *_: self.fail("timed out"))
        signal.alarm(5)

    def tearDown(self):
        signal.alarm(0)
        self.dir.cleanup()

    def track(self, name, data):
        with open(os.path.join(self.dir.name, name), "wb") as f:
            f.write(data)

    def test_looping_playlist_with_no_playable_track_stops(self):
        self.track("a.wav", b"not a wav file")
        self.track("b.wav", b"")            # wave.open raises EOFError on this one
        with mock.patch.object(host.shutil, "which", return_value=None):
            player = host.Player([self.dir.name], loop=True)
            board = FakeBoard()
            player.next(board)
        self.assertEqual(player.state, "finished")
        self.assertEqual(board.sent, [])

    def test_looping_playlist_whose_folder_empties_stops(self):
        self.track("a.wav", b"not a wav file")
        with mock.patch.object(host.shutil, "which", return_value=None):
            player = host.Player([self.dir.name], loop=True)
            os.unlink(os.path.join(self.dir.name, "a.wav"))
            player.queue = []
            player.next(FakeBoard())
        self.assertEqual(player.state, "finished")

    def silent_wav(self, name, frames=0):
        import wave
        with wave.open(os.path.join(self.dir.name, name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(host.AUDIO_RATE)
            w.writeframes(b"\0\0" * frames)

    def run_board(self, player, board, steps=200):
        """Answer like the firmware until the player stops or steps run out."""
        for _ in range(steps):
            if player.state == "finished":
                return
            last = board.sent[-1] if board.sent else ""
            if isinstance(last, str) and last.startswith("@PLAY"):
                player.handle(board, "@AOK 60000")
            elif last == "@AEND":
                player.handle(board, "@ADONE")
            elif isinstance(last, bytes) or last == "@AQ":
                player.handle(board, "@AF 60000")
            player.pump(board)

    def test_looping_playlist_of_tracks_with_no_audio_stops(self):
        # Opens fine (like a corrupt file under ffmpeg) but decodes to nothing
        self.silent_wav("a.wav")
        self.silent_wav("b.wav")
        with mock.patch.object(host.shutil, "which", return_value=None):
            player = host.Player([self.dir.name], loop=True)
            board = FakeBoard()
            player.connected(board)
            self.run_board(player, board)
        self.assertEqual(player.state, "finished")
        self.assertEqual(sum(1 for l in board.sent if isinstance(l, str) and l.startswith("@PLAY")), 2)

    def test_looping_playlist_with_audio_keeps_going(self):
        self.silent_wav("a.wav", frames=100)
        self.silent_wav("b.wav")
        with mock.patch.object(host.shutil, "which", return_value=None):
            player = host.Player([self.dir.name], loop=True)
            board = FakeBoard()
            player.connected(board)
            self.run_board(player, board)
            self.assertNotEqual(player.state, "finished")
            player._close()

    def test_unanswered_play_closes_the_decoder(self):
        self.silent_wav("a.wav", frames=100)
        with mock.patch.object(host.shutil, "which", return_value=None):
            player = host.Player([self.dir.name])
            player.connected(FakeBoard())
            self.assertIsNotNone(player.dec)
            player.waiting_since -= 10      # no @AOK for 10 s
            player.pump(FakeBoard())
        self.assertEqual(player.state, "finished")
        self.assertIsNone(player.dec)

    def test_looping_playlist_skips_bad_tracks(self):
        import wave
        self.track("a.wav", b"not a wav file")
        with wave.open(os.path.join(self.dir.name, "b.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(host.AUDIO_RATE)
            w.writeframes(b"\0\0" * 100)
        with mock.patch.object(host.shutil, "which", return_value=None):
            player = host.Player([self.dir.name], loop=True)
            board = FakeBoard()
            player.next(board)
            self.assertEqual(player.state, "starting")
            self.assertTrue(board.sent[-1].startswith("@PLAY dur=0;title=b"))
            player._close()


class DecoderTest(unittest.TestCase):
    def test_failed_afconvert_leaves_no_temp_file(self):
        made = []
        real_mkstemp = tempfile.mkstemp

        def mkstemp(*a, **k):
            fd, path = real_mkstemp(*a, **k)
            made.append(path)
            return fd, path

        fail = subprocess.CalledProcessError(1, ["afconvert"])
        with mock.patch.object(host.shutil, "which", side_effect=lambda c: "/usr/bin/afconvert" if c == "afconvert" else None), \
             mock.patch.object(host.tempfile, "mkstemp", side_effect=mkstemp), \
             mock.patch.object(host.subprocess, "run", side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                host.Decoder("/nonexistent/song.mp3")
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))

    def test_unreadable_afconvert_output_leaves_no_temp_file(self):
        made = []
        real_mkstemp = tempfile.mkstemp

        def mkstemp(*a, **k):
            fd, path = real_mkstemp(*a, **k)
            made.append(path)
            return fd, path

        # afconvert "succeeds" but leaves the output empty
        with mock.patch.object(host.shutil, "which", side_effect=lambda c: "/usr/bin/afconvert" if c == "afconvert" else None), \
             mock.patch.object(host.tempfile, "mkstemp", side_effect=mkstemp), \
             mock.patch.object(host.subprocess, "run"):
            with self.assertRaises(EOFError):
                host.Decoder("/nonexistent/song.mp3")
        self.assertFalse(os.path.exists(made[0]))


class LimitsTest(unittest.TestCase):
    """Plan-limit failures must become LimitsError, so the display falls back
    to the local estimate instead of crashing or showing stale limits."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.token = os.path.join(self.dir.name, "token")
        with open(self.token, "w") as f:
            f.write("tok")
        # Only the token file: no env token, keychain or ~/.claude credentials
        self.patches = [
            mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": ""}),
            mock.patch.object(host.platform, "system", return_value="Linux"),
            mock.patch.object(host.os.path, "exists", return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.dir.cleanup()

    def reply(self, body):
        return mock.patch.object(host.urllib.request, "urlopen", return_value=io.BytesIO(body))

    def test_unreadable_token_file(self):
        real_open = builtins.open

        def deny(path, *a, **k):
            if path == self.token:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", deny):
            self.assertEqual(host.oauth_tokens(self.token), [])
            with self.assertRaises(host.LimitsError):
                host.fetch_limits(self.token)

    def test_token_file_not_utf8(self):
        with open(self.token, "wb") as f:
            f.write(b"\xff\xfe bad")
        self.assertEqual(host.oauth_tokens(self.token), [])

    def test_malformed_replies(self):
        for body in (b"<html>proxy login</html>", b"[]", b'"text"', b"null"):
            with self.subTest(body=body), self.reply(body):
                with self.assertRaises(host.LimitsError) as cm:
                    host.fetch_limits(self.token)
                self.assertEqual(cm.exception.short, "limits: bad reply")

    def test_odd_fields_read_as_unknown(self):
        body = json.dumps({"five_hour": {"utilization": "abc", "resets_at": 123},
                           "seven_day": {"utilization": 7, "resets_at": "not a time"}}).encode()
        with self.reply(body):
            out = host.fetch_limits(self.token)
        self.assertEqual((out["sp"], out["sr"], out["wp"], out["wr"]), (-1, -1, 7, -1))

    def test_bad_reply_replaces_stale_limits(self):
        args = types.SimpleNamespace(token_file=self.token, no_renew=True)
        lim = {"data": {"src": "o", "sp": 40}, "at": 0.0, "err": None, "thread": "t"}
        with self.reply(b"[]"):
            host._fetch_limits_into(args, lim)
        self.assertIsNone(lim["data"])
        self.assertIsInstance(lim["err"], host.LimitsError)
        self.assertIsNone(lim["thread"])

    def test_check_reports_a_bad_reply_and_goes_on(self):
        args = types.SimpleNamespace(no_limits=False, token_file=self.token, no_renew=True,
                                     port=os.path.join(self.dir.name, "no-port"), block_limit=None)
        reader = host.LogReader(host.History(None))
        out = io.StringIO()
        with self.reply(b"<html>"), mock.patch.object(host, "claude_dirs", return_value=[]), \
                mock.patch("sys.stdout", out):
            host.check(args, reader)
        self.assertIn("failed: usage request returned something that isn't JSON", out.getvalue())
        self.assertIn("Board:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
