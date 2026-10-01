#!/usr/bin/env python3
"""
Send Claude usage to the RP2350 Touch LCD 3.49 over USB serial.

Two data sources, both on your Mac:

1. Claude Code's local logs (always used)
   ~/.claude/projects/**/*.jsonl (and ~/.config/claude/projects, or
   $CLAUDE_CONFIG_DIR). Every assistant message there carries its token usage,
   which gives today's tokens, API-equivalent cost, the hourly history, the
   current 5-hour window and the burn rate.

   Only Claude Code running on this Mac writes these logs. Usage in the Claude
   app, on claude.ai or in Claude Code on the web isn't recorded here.

2. Your plan limits (optional, on by default)
   The same "5-hour" and "weekly" percentages that Claude Code's /usage shows.
   They cover all your usage, wherever it happened. They come from an
   unofficial endpoint and need an OAuth token, looked up in this order:
     - $CLAUDE_CODE_OAUTH_TOKEN
     - the file ~/.config/claude-usage-display/token (or --token-file)
     - the token Claude Code keeps in the macOS keychain after you log in
   The first one that works is used. Tokens from `claude setup-token` can't
   read usage (403 or 429).
   The keychain token expires after a few hours, and only Claude Code can renew
   it. When it has expired, this script runs `claude -p` with a one-word prompt
   on Haiku so that Claude Code renews it (--no-renew turns that off). The
   script itself only reads tokens, so it can't log Claude Code out.
   Without a working token, the display falls back to an estimate from the
   local logs (shown as "5-HOUR est.").
   Pass --no-limits to skip this entirely.

All-time daily totals, the longest task and streaks for the board's stats
page are worked out from the same logs. Claude Code deletes old logs (after 30
days by default), so the daily totals are also kept in
~/.config/claude-usage-display/history.json (--history-file).

It can also play music from a folder on the Mac through the board's speaker
(--music). The audio is decoded on the Mac to 24 kHz 16-bit mono and streamed
over the same USB serial link. Decoding uses ffmpeg if it is installed,
otherwise macOS's built-in afconvert (MP3, AAC/M4A, WAV, AIFF, FLAC, ...).
Tap the now-playing row on the screen to skip to the next track.

Only the Python 3 standard library is needed.

    python3 tools/claude_usage_host.py             # auto-detect the board
    python3 tools/claude_usage_host.py --print     # dry run, print the lines
    python3 tools/claude_usage_host.py --demo      # fake data, to test the screen
    python3 tools/claude_usage_host.py --check     # show what it finds, then exit
    python3 tools/claude_usage_host.py --imu       # live accelerometer readings
    python3 tools/claude_usage_host.py --music ~/Music/Desk --shuffle --volume 60
"""

import argparse
import glob
import json
import fcntl
import os
import platform
import random
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tty
import urllib.error
import urllib.request
import wave
from datetime import datetime, timedelta, timezone

BLOCK = timedelta(hours=5)
HOURS = 12
KEEP = timedelta(days=8)
STATS_INTERVAL = 300                # seconds between @CS (history stats) updates
HEATMAP_WEEKS = 16
TASK_GAP = timedelta(minutes=30)    # a pause this long ends a task
HISTORY_FILE = "~/.config/claude-usage-display/history.json"

# USD per million tokens: (input, output, cache read). Cache writes are
# billed at 1.25x input. First match wins, so more specific names go first.
PRICES = [
    ("fable-5-1", (10.0, 50.0, 0.25)),
    ("mythos-5-1", (10.0, 50.0, 0.25)),
    ("fable", (10.0, 50.0, 1.00)),
    ("mythos", (10.0, 50.0, 1.00)),
    ("opus-5-5", (4.0, 20.0, 0.20)),
    ("opus-5", (5.0, 25.0, 0.50)),
    ("opus-4-8", (5.0, 25.0, 0.50)),
    ("opus-4-7", (5.0, 25.0, 0.50)),
    ("opus-4-6", (5.0, 25.0, 0.50)),
    ("opus-4-5", (5.0, 25.0, 0.50)),
    ("opus", (15.0, 75.0, 1.50)),       # Opus 4 / 4.1 / 3
    ("sonnet-5", (2.0, 10.0, 0.20)),
    ("sonnet", (3.0, 15.0, 0.30)),
    ("haiku-4-5", (1.0, 5.0, 0.10)),
    ("haiku-3-5", (0.8, 4.0, 0.08)),
    ("haiku", (0.25, 1.25, 0.03)),
]

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Local Claude Code logs
# --------------------------------------------------------------------------

def claude_dirs():
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = env.split(",") if env else ["~/.config/claude", "~/.claude"]
    out = []
    for r in roots:
        p = os.path.join(os.path.expanduser(r.strip()), "projects")
        if os.path.isdir(p):
            out.append(p)
    return out


def price_for(model):
    m = (model or "").lower()
    for key, p in PRICES:
        if key in m:
            return p
    return (3.0, 15.0, 0.30)    # unknown model: assume Sonnet-class pricing


def pretty_model(model):
    """claude-opus-5-5 -> Opus 5.5, claude-3-5-sonnet-20241022 -> Sonnet 3.5"""
    parts = (model or "").replace("claude-", "").split("-")
    family = next((p for p in parts if not p.isdigit()), "")
    nums = [p for p in parts if p.isdigit() and len(p) < 8]
    return (family.capitalize() + " " + ".".join(nums)).strip()


def parse_ts(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


class LogReader:
    """Incrementally reads new lines from the JSONL logs.

    Only the last 8 days are kept in entries; every record is also passed to
    history (if given), which keeps the all-time stats."""

    def __init__(self, history=None):
        self.offsets = {}   # path -> bytes already read
        self.seen = set()   # (message id, request id), streaming writes duplicates
        self.entries = []   # (time, model, tokens, cost), sorted by time
        self.history = history

    def scan(self):
        new = []
        for root in claude_dirs():
            for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                off = self.offsets.get(path, 0)
                if size < off:          # file was rewritten
                    off = 0
                if size == off:
                    continue
                try:
                    with open(path, "rb") as f:
                        f.seek(off)
                        data = f.read()
                except OSError:
                    continue
                # Only consume complete lines; a partial last line is re-read next time
                end = data.rfind(b"\n") + 1
                self.offsets[path] = off + end
                for raw in data[:end].splitlines():
                    e = self.parse_line(raw)
                    if e:
                        new.append(e[:4])
                        if self.history is not None:
                            self.history.add(e[0], e[2], e[4] or path)
        if new:
            cutoff = datetime.now(timezone.utc) - KEEP
            self.entries = sorted(
                [e for e in self.entries + new if e[0] >= cutoff], key=lambda e: e[0])
        return len(new)

    def parse_line(self, raw):
        if b'"usage"' not in raw:
            return None
        try:
            obj = json.loads(raw)
        except ValueError:
            return None
        msg = obj.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
            return None
        model = msg.get("model") or ""
        if model.startswith("<"):       # "<synthetic>" placeholder messages
            return None
        key = (msg.get("id"), obj.get("requestId"))
        if key != (None, None):
            if key in self.seen:
                return None
            self.seen.add(key)
        try:
            ts = parse_ts(obj["timestamp"])
        except (KeyError, ValueError, TypeError):
            return None
        u = msg["usage"]
        inp = int(u.get("input_tokens") or 0)
        out = int(u.get("output_tokens") or 0)
        cw = int(u.get("cache_creation_input_tokens") or 0)
        cr = int(u.get("cache_read_input_tokens") or 0)
        cost = obj.get("costUSD")
        if cost is None:
            pi, po, pr = price_for(model)
            cost = (inp * pi + out * po + cw * pi * 1.25 + cr * pr) / 1e6
        return (ts, model, inp + out + cw + cr, float(cost), obj.get("sessionId"))


def blocks(entries):
    """Group entries into 5-hour windows the way ccusage does."""
    out = []
    cur = None
    for ts, _, tok, cost in entries:
        if cur is None or ts >= cur["start"] + BLOCK or ts - cur["last"] >= BLOCK:
            start = ts.replace(minute=0, second=0, microsecond=0)
            cur = {"start": start, "last": ts, "tokens": 0, "cost": 0.0}
            out.append(cur)
        cur["last"] = ts
        cur["tokens"] += tok
        cur["cost"] += cost
    return out


def local_stats(entries, block_limit_usd=None):
    now = datetime.now(timezone.utc)
    local_now = datetime.now().astimezone()
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

    s = {}
    today = [e for e in entries if e[0] >= midnight]
    s["tt"] = sum(e[2] for e in today)
    s["tc"] = int(round(sum(e[3] for e in today) * 100))
    s["tm"] = len(today)

    recent = [e for e in entries if e[0] >= now - timedelta(minutes=15)]
    s["br"] = sum(e[2] for e in recent) // 15

    hour0 = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=HOURS - 1)
    hourly = [0] * HOURS
    for ts, _, tok, _ in entries:
        i = int((ts - hour0).total_seconds() // 3600)
        if 0 <= i < HOURS:
            hourly[i] += tok
    s["h"] = ",".join(str(v) for v in hourly)

    s["m"] = pretty_model(entries[-1][1]) if entries else ""

    bl = blocks(entries)
    active = bl[-1] if bl and now < bl[-1]["start"] + BLOCK and now - bl[-1]["last"] < BLOCK else None
    if active:
        s["bt"] = active["tokens"]
        s["sr"] = int((active["start"] + BLOCK - now).total_seconds() // 60)
        # Estimate: this window's cost against the busiest earlier window
        limit = block_limit_usd or max((b["cost"] for b in bl[:-1]), default=0.0)
        s["sp"] = min(100, int(round(100 * active["cost"] / limit))) if limit > 0 else -1
    else:
        s["bt"] = 0
        s["sr"] = -1
        s["sp"] = 0
    return s


# --------------------------------------------------------------------------
# All-time history, for the stats page
# --------------------------------------------------------------------------

class History:
    """Daily token totals and the longest task, kept beyond the logs' lifetime.

    Claude Code deletes old logs (after 30 days by default), so the totals are
    also saved to a small JSON file and merged back on start: per day, the
    larger of the saved and freshly read totals wins. Logs only lose days, never
    tokens within a day, so that never double counts.

    A task is a stretch of one session's messages with no pause longer than
    TASK_GAP, so a session left open overnight doesn't count as one long task."""

    def __init__(self, path=HISTORY_FILE):
        # Absolute, so a bare file name has a directory to create and save into
        self.path = os.path.abspath(os.path.expanduser(path)) if path else None
        self.saved = {}         # "YYYY-MM-DD" -> tokens, from the file
        self.days = {}          # "YYYY-MM-DD" -> tokens, read from the logs this run
        self.sessions = {}      # session -> [task start, last message]
        self.best_task = (0, "")    # (seconds, "YYYY-MM-DD") of finished tasks
        self.load()

    def load(self):
        if not self.path:
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.saved = {d: int(t) for d, t in data.get("days", {}).items()}
            lt = data.get("longest_task") or {}
            self.best_task = (int(lt.get("seconds", 0)), str(lt.get("date", "")))
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def save(self):
        """Writes the merged totals back. Returns True if the file changed."""
        if not self.path:
            return False
        data = {"version": 1, "days": dict(sorted(self.daily().items())),
                "longest_task": dict(zip(("seconds", "date"), self.longest_task()))}
        try:
            with open(self.path) as f:
                if json.load(f) == data:
                    return False
        except (OSError, ValueError):
            pass
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            log(f"can't save {self.path}: {e}")
            return False

    def add(self, ts, tokens, session):
        local = ts.astimezone()
        day = local.date().isoformat()
        self.days[day] = self.days.get(day, 0) + tokens

        s = self.sessions.get(session)
        if s is None:
            self.sessions[session] = [ts, ts]
            return
        start, last = s
        if ts < last:           # out of order; keep the task going
            return
        if ts - last > TASK_GAP:
            self._finish(start, last)
            s[0] = ts
        s[1] = ts

    def _finish(self, start, last):
        secs = int((last - start).total_seconds())
        if secs > self.best_task[0]:
            self.best_task = (secs, start.astimezone().date().isoformat())

    def daily(self):
        out = dict(self.saved)
        for d, t in self.days.items():
            out[d] = max(out.get(d, 0), t)
        return out

    def longest_task(self):
        """(seconds, date), counting tasks still going on."""
        best = self.best_task
        for start, last in self.sessions.values():
            secs = int((last - start).total_seconds())
            if secs > best[0]:
                best = (secs, start.astimezone().date().isoformat())
        return best


def streaks(active, today):
    """(current, longest) runs of consecutive days in the set of dates active.

    The current streak still counts if today has no usage yet but yesterday did."""
    longest = run = 0
    prev = None
    for d in sorted(active):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        longest = max(longest, run)
        prev = d
    current = 0
    d = today if today in active else today - timedelta(days=1)
    while d in active:
        current += 1
        d -= timedelta(days=1)
    return current, longest


def heatmap(daily, today, weeks=HEATMAP_WEEKS):
    """Recent days as a string of levels 0-4, for a grid of weeks columns by
    7 rows (Monday at the top). It starts on the Monday weeks-1 weeks before
    this week's and ends today, so its length is 7*(weeks-1) + 1..7 and the
    board fills it column by column. Returns (levels, tokens for level 4)."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    vals = []
    d = start
    while d <= today:
        vals.append(daily.get(d.isoformat(), 0))
        d += timedelta(days=1)
    top = max(vals, default=0)
    if top <= 0:
        return "0" * len(vals), 0
    # 1-4 by quarters of the busiest day; any usage at all shows as at least 1
    return "".join("0" if v <= 0 else str(min(4, 1 + 4 * v // (top + 1))) for v in vals), top


def history_stats(history, today=None):
    """The @CS fields for the stats page."""
    today = today or datetime.now().date()
    daily = {d: t for d, t in history.daily().items() if t > 0}
    s = {"tot": sum(daily.values())}
    if daily:
        best = max(daily, key=lambda d: (daily[d], d))
        s["hd"], s["hdt"] = best, daily[best]
        s["fd"] = min(daily)
    else:
        s["hd"], s["hdt"], s["fd"] = "", 0, ""
    active = set()
    for d in daily:
        try:
            active.add(datetime.strptime(d, "%Y-%m-%d").date())
        except ValueError:
            pass
    s["cs"], s["ls"] = streaks(active, today)
    secs, day = history.longest_task()
    s["lt"], s["ltd"] = secs // 60, day
    s["hm"], s["hmax"] = heatmap(daily, today)
    return s


# --------------------------------------------------------------------------
# Plan limits (optional)
# --------------------------------------------------------------------------

TOKEN_FILE = "~/.config/claude-usage-display/token"


def oauth_tokens(token_file=TOKEN_FILE):
    """Every token we can find, best first, as (token, where it came from,
    whether it is Claude Code's own login, which Claude Code can renew)."""
    out = []
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if tok:
        out.append((tok, "$CLAUDE_CODE_OAUTH_TOKEN", False))
    path = os.path.expanduser(token_file)
    if os.path.isfile(path):
        with open(path) as f:
            tok = f.read().strip()
        if tok:
            out.append((tok, path, False))
    blobs = []
    if platform.system() == "Darwin":
        try:
            blob = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=10).stdout
            if blob:
                blobs.append((blob, "macOS keychain (Claude Code login)"))
        except (OSError, subprocess.SubprocessError):
            pass
    path = os.path.expanduser("~/.claude/.credentials.json")
    if os.path.exists(path):
        with open(path) as f:
            blobs.append((f.read(), path))
    for blob, where in blobs:
        try:
            out.append((json.loads(blob)["claudeAiOauth"]["accessToken"], where, True))
        except (ValueError, KeyError, TypeError):
            pass
    return out


class LimitsError(RuntimeError):
    def __init__(self, message, short):
        super().__init__(message)
        self.short = short      # fits on the board's screen


def minutes_until(iso):
    if not iso:
        return -1
    try:
        return max(0, int((parse_ts(iso) - datetime.now(timezone.utc)).total_seconds() // 60))
    except ValueError:
        return -1


def _request_usage(tok):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + tok,
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
        "User-Agent": "claude-usage-display/1",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


_REJECTED = {401: "expired", 403: "not allowed to read usage", 429: "rate limited"}
_retry_at = {}      # token -> when a 429 lets us ask again


def _retry_after(err, default=300):
    try:
        return max(0, int(err.headers.get("Retry-After", default)))
    except (TypeError, ValueError):
        return default


def _first_working(tokens):
    """Usage from the first token that works (or None), and what the rest answered."""
    # A token that is expired (401), can't read usage (403) or is rate limited
    # (429) falls through to the next source, e.g. a `claude setup-token` token
    # to the keychain login. The limit is per token, so the next one may work.
    rejected = []
    for tok, where, login in tokens:
        if _retry_at.get(tok, 0) > time.time():
            rejected.append((429, where, login))
            continue
        try:
            return _request_usage(tok), rejected
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _retry_at[tok] = time.time() + _retry_after(e)
            if e.code in _REJECTED:
                rejected.append((e.code, where, login))
                continue
            raise LimitsError(f"usage request failed: HTTP {e.code}", f"limits: HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise LimitsError(f"usage request failed: {e}", "limits: offline")
    return None, rejected


RENEW_EVERY = 600   # seconds between attempts, so a dead login doesn't cost a request every poll
_renewed_at = 0.0


_claude_missing = False     # so the "can't find it" line is logged once, not every poll


def find_claude():
    """The `claude` executable: on PATH, or else where its installers put it.
    launchd and GUI launchers start us with a bare PATH that has none of these."""
    exe = shutil.which("claude")
    if exe:
        return exe
    home = os.path.expanduser("~")
    nvm = os.environ.get("NVM_DIR") or home + "/.nvm"
    found = [p for pat in (home + "/.local/bin/claude", home + "/.claude/local/claude",
                           "/opt/homebrew/bin/claude", "/usr/local/bin/claude",
                           nvm + "/versions/node/*/bin/claude", home + "/.volta/bin/claude",
                           home + "/.bun/bin/claude", home + "/.npm-global/bin/claude")
             for p in glob.glob(pat) if os.access(p, os.X_OK)]
    return max(found, key=os.path.getmtime) if found else None


def renew_login():
    """Get Claude Code to renew its expired login by running one tiny request
    through it. We never use the refresh token ourselves. True if it worked."""
    global _renewed_at, _claude_missing
    if time.time() - _renewed_at < RENEW_EVERY:
        return False
    exe = find_claude()
    if not exe:
        # Not counted as an attempt: `claude` vanishes for a while each time it
        # updates itself, so look again at the next poll.
        if not _claude_missing:
            log("can't renew the Claude Code login: can't find `claude` (not on PATH or in "
                "the usual install folders); will keep looking")
        _claude_missing = True
        return False
    _claude_missing = False
    _renewed_at = time.time()
    # With one of these set, Claude Code would use it and leave its login alone.
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    # An npm install of `claude` may be a node script: let it find the node beside it.
    env["PATH"] = os.path.dirname(exe) + os.pathsep + env.get("PATH", os.defpath)
    try:
        r = subprocess.run(
            [exe, "-p", "Reply with the single word: ok", "--model", "haiku", "--no-session-persistence"],
            capture_output=True, text=True, timeout=60, env=env,
            cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"can't renew the Claude Code login: {e}")
        return False
    if r.returncode != 0:
        why = (r.stdout + r.stderr).strip().splitlines()
        log(f"can't renew the Claude Code login: {why[-1] if why else 'claude failed'}")
        return False
    log("Claude Code login had expired; renewed it by running `claude -p`")
    return True


def fetch_limits(token_file=TOKEN_FILE, renew=False):
    tokens = oauth_tokens(token_file)
    if not tokens:
        raise LimitsError(
            "no OAuth token: log in to Claude Code on this Mac (`claude auth login`)",
            "limits: no token")
    data, rejected = _first_working(tokens)
    if (data is None and renew and any(code == 401 and login for code, _, login in rejected)
            and renew_login()):
        data, rejected = _first_working(oauth_tokens(token_file))
    if data is None:
        why = "; ".join(f"{where}: {_REJECTED[code]} ({code})" for code, where, _ in rejected)
        hint = ("Log in to Claude Code on this Mac (`claude auth login`): its keychain token is "
                "the one that can read usage, and it expires within hours unless Claude Code "
                "renews it. Tokens from `claude setup-token` can't read usage.")
        codes = {c for c, _, _ in rejected}
        short = ("limits: token expired" if 401 in codes
                 else "limits: rate limited" if 429 in codes else "limits: no access")
        raise LimitsError(f"no token worked ({why}). {hint}", short)

    def pct(w):
        return int(round(float(w.get("utilization") or 0))) if isinstance(w, dict) else -1

    out = {"src": "o"}
    five = data.get("five_hour")
    week = data.get("seven_day")
    out["sp"] = pct(five)
    out["sr"] = minutes_until(five.get("resets_at")) if isinstance(five, dict) else -1
    out["wp"] = pct(week)
    out["wr"] = minutes_until(week.get("resets_at")) if isinstance(week, dict) else -1
    # Per-model weekly limit, if the plan has one
    fam = [(pct(data.get(k)), label) for k, label in
           (("seven_day_opus", "OPUS"), ("seven_day_sonnet", "SONNET"))
           if isinstance(data.get(k), dict)]
    if fam:
        p, label = max(fam)
        out["w2p"], out["w2l"] = p, label
    return out


# --------------------------------------------------------------------------
# Serial link
# --------------------------------------------------------------------------

def candidate_ports():
    pats = ["/dev/cu.usbmodem*"] if platform.system() == "Darwin" else ["/dev/ttyACM*"]
    return sorted(p for pat in pats for p in glob.glob(pat))


class Board:
    def __init__(self, port):
        self.port = port
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(self.fd)
        attrs = termios.tcgetattr(self.fd)
        attrs[2] |= termios.CLOCAL      # USB CDC: no modem control lines
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        # The Pico's USB serial ignores input until the host raises DTR. Most
        # systems do on open, but set it explicitly rather than rely on that.
        try:
            bis = getattr(termios, "TIOCMBIS", 0x8004746c if platform.system() == "Darwin" else 0x5416)
            lines = getattr(termios, "TIOCM_DTR", 0x002) | getattr(termios, "TIOCM_RTS", 0x004)
            fcntl.ioctl(self.fd, bis, struct.pack("I", lines))
        except OSError:
            pass
        self.rx = b""

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def send(self, line):
        data = line if isinstance(line, bytes) else (line + "\n").encode()
        while data:
            _, w, _ = select.select([], [self.fd], [], 2)
            if not w:
                raise OSError("write timeout")
            n = os.write(self.fd, data)
            data = data[n:]

    def read_lines(self, timeout=0.0):
        """Drain what the board has sent; returns complete lines."""
        end = time.time() + timeout
        while True:
            r, _, _ = select.select([self.fd], [], [], max(0.0, end - time.time()))
            if r:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    raise OSError("port closed")
                self.rx += chunk
            if not r or time.time() >= end:
                break
        *lines, self.rx = self.rx.split(b"\n")
        return [l.decode(errors="replace").strip() for l in lines]

    def ping(self):
        self.read_lines()
        self.send("@PING")
        deadline = time.time() + 2
        while time.time() < deadline:
            if any(l.startswith("@PONG claude-usage") for l in self.read_lines(0.2)):
                return True
        return False


def find_board(port=None):
    for p in [port] if port else candidate_ports():
        try:
            b = Board(p)
        except OSError:
            continue
        if b.ping():
            return b
        b.close()
    return None


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Music
# --------------------------------------------------------------------------

AUDIO_RATE = 24000          # what the board's ES8311 codec is clocked for
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".alac", ".wav", ".aif", ".aiff", ".aifc",
              ".caf", ".flac", ".ogg", ".opus"}
CHUNK = 4096                # bytes of PCM per "@A" message


class Decoder:
    """Turns an audio file into 24 kHz, 16-bit little-endian mono PCM."""

    def __init__(self, path):
        self.path = path
        self.proc = None
        self.wav = None
        self.tmp = None
        self.duration = 0
        if shutil.which("ffmpeg"):
            self._open_ffmpeg()
        elif shutil.which("afconvert"):
            self._open_afconvert()
        else:
            self._open_wav(path)

    def _open_ffmpeg(self):
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-nostdin", "-i", self.path,
             "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(AUDIO_RATE), "-"],
            stdout=subprocess.PIPE)
        if shutil.which("ffprobe"):
            try:
                out = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", self.path],
                    capture_output=True, text=True, timeout=10).stdout
                self.duration = int(float(out.strip() or 0))
            except (ValueError, OSError, subprocess.SubprocessError):
                pass

    def _open_afconvert(self):
        # afconvert can't write to a pipe, so decode into a temporary WAV first
        fd, self.tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{AUDIO_RATE}", "-c", "1",
                        self.path, self.tmp], check=True, capture_output=True)
        self._open_wav(self.tmp)

    def _open_wav(self, path):
        w = wave.open(path, "rb")
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (AUDIO_RATE, 1, 2):
            w.close()
            raise RuntimeError("needs ffmpeg or afconvert to convert it "
                               f"(only {AUDIO_RATE} Hz 16-bit mono WAV plays as is)")
        self.wav = w
        self.duration = w.getnframes() // AUDIO_RATE

    def read(self, n):
        if self.proc:
            return self.proc.stdout.read(n)
        return self.wav.readframes(n // 2)

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
        if self.wav:
            self.wav.close()
        if self.tmp:
            try:
                os.unlink(self.tmp)
            except OSError:
                pass


def collect_tracks(paths):
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                out += [os.path.join(root, f) for f in files
                        if os.path.splitext(f)[1].lower() in AUDIO_EXTS and not f.startswith(".")]
        elif os.path.isfile(p):
            out.append(p)
    return sorted(out)


class Player:
    """Streams a playlist to the board, sending only as much as it has room for."""

    def __init__(self, paths, shuffle=False, loop=False, volume=None):
        self.paths = paths
        self.shuffle = shuffle
        self.loop = loop
        self.volume = volume
        self.queue = []
        self.dec = None
        self.state = "idle"         # idle, starting, streaming, ended, finished
        self.credit = 0
        self.waiting = False        # sent something, waiting for the board's @AF
        self.waiting_since = 0.0
        self._refill()
        if not self.queue:
            log(f"no audio files found in {', '.join(paths)}")
            self.state = "finished"

    def _refill(self):
        tracks = collect_tracks(self.paths)
        if self.shuffle:
            random.shuffle(tracks)
        self.queue = tracks

    def _close(self):
        if self.dec:
            self.dec.close()
            self.dec = None

    def _expect(self, board, line):
        board.send(line)
        self.waiting = True
        self.waiting_since = time.time()

    def connected(self, board):
        """(Re)start the current playlist position on a fresh connection."""
        if self.state == "finished":
            return
        if self.volume is not None:
            board.send(f"@VOL {self.volume}")
        self.next(board)

    def next(self, board):
        self._close()
        while True:
            if not self.queue:
                if not self.loop:
                    log("playlist finished")
                    self.state = "finished"
                    return
                self._refill()
            path = self.queue.pop(0)
            try:
                self.dec = Decoder(path)
                break
            except (OSError, RuntimeError, wave.Error, subprocess.SubprocessError) as e:
                log(f"skipping {os.path.basename(path)}: {e}")
        title = os.path.splitext(os.path.basename(path))[0]
        clean = title.replace(";", ",").replace("\n", " ")[:46]
        dur = self.dec.duration
        log(f"playing {title}" + (f" ({dur // 60}:{dur % 60:02d})" if dur else ""))
        self.state = "starting"
        self.credit = 0
        self._expect(board, f"@PLAY dur={dur};title={clean}")

    def handle(self, board, line):
        if line.startswith(("@AOK ", "@AF ")):
            try:
                self.credit = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self.waiting = False
            if self.state == "starting":
                self.state = "streaming"
        elif line == "@ADONE" and self.state == "ended":
            self.next(board)
        elif line == "@ANEXT" and self.state in ("starting", "streaming", "ended"):
            board.send("@STOP")
            self.next(board)

    def pump(self, board):
        """Send the next chunk if the board has room. True while there is more to send."""
        if self.state not in ("starting", "streaming"):
            return False
        if self.waiting:
            if time.time() - self.waiting_since > 3:
                if self.state == "starting":
                    log("the board didn't answer @PLAY; is its firmware up to date?")
                    self.state = "finished"
                    return False
                self._expect(board, "@AQ")     # a reply got lost, ask again
            return True
        if self.credit >= 1024:
            n = min(CHUNK, self.credit) & ~1
            data = self.dec.read(n)
            if data:
                self.credit -= len(data)
                self._expect(board, f"@A {len(data)}\n".encode() + data)
            else:
                board.send("@AEND")
                self.state = "ended"
                self._close()
        else:
            # Buffer full: ask again in a moment
            if time.time() - self.waiting_since > 0.05:
                self._expect(board, "@AQ")
        return True


def encode(fields, tag="@CU"):
    def clean(v):
        return str(v).replace(";", ",").replace("=", "-").replace("\n", " ")
    return tag + " " + ";".join(f"{k}={clean(v)}" for k, v in fields.items())


def demo_stats():
    today = datetime.now().date()
    daily = {(today - timedelta(days=i)).isoformat(): random.choice([0, 0, 1, 5, 20, 60]) * 1_000_000
             for i in range(200)}
    hm, top = heatmap(daily, today)
    return {"tot": sum(daily.values()), "hd": max(daily, key=daily.get), "hdt": max(daily.values()),
            "fd": min(daily), "cs": random.randint(0, 20), "ls": random.randint(20, 60),
            "lt": random.randint(30, 400), "ltd": today.isoformat(), "hm": hm, "hmax": top}


def stats_fields(args, history):
    if args.demo:
        return demo_stats()
    s = history_stats(history)
    if not args.print:
        history.save()
    return s


def stats_summary(s):
    return (f"stats: {s['tot']:,} tokens since {s['fd'] or '--'}, best day {s['hd'] or '--'} "
            f"({s['hdt']:,}), streak {s['cs']} (longest {s['ls']}), longest task {s['lt']} min")


def demo_fields():
    now = datetime.now()
    return {
        "src": "o", "sp": random.randint(5, 98), "sr": random.randint(1, 299),
        "wp": random.randint(5, 90), "wr": random.randint(60, 7 * 1440),
        "w2p": random.randint(0, 80), "w2l": "SONNET",
        "tt": random.randint(1, 90) * 1_000_000, "tc": random.randint(100, 9000),
        "tm": random.randint(10, 400), "bt": random.randint(1, 30) * 1_000_000,
        "br": random.randint(0, 200_000),
        "h": ",".join(str(random.randint(0, 5_000_000)) for _ in range(HOURS)),
        "m": "Opus 5.5", "t": now.strftime("%H:%M"),
    }


def status_text(entries, limits_err):
    """A short note for the screen explaining zeros or estimates ("" when all is well)."""
    if limits_err is None:
        return ""
    if not entries:
        return "no usage data on Mac"
    return limits_err.short if isinstance(limits_err, LimitsError) else "limits: unavailable"


def summary(fields):
    def pct(k):
        v = fields.get(k, -1)
        return f"{v}%" if isinstance(v, int) and v >= 0 else "--"
    src = "plan limits" if fields.get("src") == "o" else "estimate"
    s = (f"5h {pct('sp')} ({src}), week {pct('wp')}, today {fields.get('tt', 0):,} tokens / "
         f"{fields.get('tm', 0)} msgs / ${fields.get('tc', 0) / 100:.2f}")
    if fields.get("st"):
        s += f"  [screen note: {fields['st']}]"
    return s


def check(args, reader):
    """--check: report what the script can see, without starting the update loop."""
    print("Claude Code logs:")
    dirs = claude_dirs()
    for d in dirs:
        print(f"  {d}")
    if not dirs:
        print("  none found (~/.claude/projects, ~/.config/claude/projects)")
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [e for e in reader.entries if e[0] >= midnight]
    print(f"  {len(reader.entries)} usage records in the last 8 days, {len(today)} today")
    if reader.entries:
        print(f"  latest: {reader.entries[-1][0].astimezone():%Y-%m-%d %H:%M} ({pretty_model(reader.entries[-1][1])})")
    else:
        print("  Only Claude Code running on this Mac writes these; the Claude app, claude.ai")
        print("  and Claude Code on the web don't.")

    print("History (stats page):")
    st = history_stats(reader.history)
    print(f"  {len(reader.history.daily())} days, {reader.history.path or 'not saved'}")
    print("  " + stats_summary(st))

    print("Plan limits:")
    if args.no_limits:
        print("  skipped (--no-limits)")
    else:
        tokens = oauth_tokens(args.token_file)
        print("  tokens: " + (", ".join(w for _, w, _ in tokens) or "none found"))
        try:
            lim = fetch_limits(args.token_file, renew=not args.no_renew)
            print(f"  OK: 5-hour {lim['sp']}%, weekly {lim['wp']}%")
        except LimitsError as e:
            print(f"  failed: {e}")

    print("Board:")
    ports = [args.port] if args.port else candidate_ports()
    if not ports:
        print("  no /dev/cu.usbmodem* port. Is it plugged in with a data cable and running the firmware?")
    for p in ports:
        try:
            b = Board(p)
        except OSError as e:
            print(f"  {p}: can't open ({e}); is another program (serial monitor) using it?")
            continue
        ok = b.ping()
        if ok:
            b.send(encode(dict(local_stats(reader.entries, args.block_limit), src="l", t="--:--")))
            acked = any(l == "@OK" for l in b.read_lines(1.0))
            print(f"  {p}: answers @PING; test update {'acknowledged' if acked else 'NOT acknowledged'}")
        else:
            print(f"  {p}: no answer to @PING (different device, or older firmware)")
        b.close()


def _fetch_limits_into(args, lim):
    try:
        data = fetch_limits(args.token_file, renew=not args.no_renew)
        if lim["err"] is not None:
            log("plan limits OK")
        lim["data"], lim["err"] = data, None
    except (LimitsError, ValueError) as e:
        if lim["err"] is None or str(e) != str(lim["err"]):
            log(f"plan limits unavailable, using the local estimate: {e}")
        lim["err"], lim["data"] = e, None
    finally:
        lim["thread"] = None


def usage_fields(args, reader, lim):
    """One usage snapshot. lim holds the plan-limit cache between calls.

    The plan limits are fetched on a background thread: the request, and
    especially renewing the login with `claude -p`, can take many seconds, and
    the main loop must keep feeding audio to the board meanwhile. Only the first
    fetch is waited for, so the first update already has the limits."""
    if args.demo:
        return demo_fields()
    reader.scan()
    fields = local_stats(reader.entries, args.block_limit)
    fields["src"] = "l"
    if args.no_limits:
        lim["err"] = LimitsError("disabled", "")
    elif lim["thread"] is None and time.time() - lim["at"] >= args.limits_interval:
        first = lim["at"] == 0.0
        lim["at"] = time.time()
        t = threading.Thread(target=_fetch_limits_into, args=(args, lim), daemon=True)
        lim["thread"] = t
        t.start()
        if first:
            t.join(20)
    if lim["data"]:
        fields.update(lim["data"])
    st = status_text(reader.entries, lim["err"])
    if st:
        fields["st"] = st
    fields["t"] = datetime.now().strftime("%H:%M")
    return fields


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (default: auto-detect /dev/cu.usbmodem*)")
    ap.add_argument("--interval", type=float, default=15, help="seconds between updates (default 15)")
    ap.add_argument("--limits-interval", type=float, default=120,
                    help="seconds between plan-limit requests (default 120)")
    ap.add_argument("--no-limits", action="store_true", help="don't query plan limits, local logs only")
    ap.add_argument("--no-renew", action="store_true",
                    help="don't run `claude -p` to renew an expired Claude Code login")
    ap.add_argument("--token-file", default=TOKEN_FILE,
                    help=f"file holding an OAuth token for the plan limits (default {TOKEN_FILE})")
    ap.add_argument("--block-limit", type=float, metavar="USD",
                    help="for the local estimate: API-equivalent USD that counts as 100%% of a 5-hour window "
                         "(default: your busiest earlier window)")
    ap.add_argument("--print", action="store_true", help="print the lines instead of sending them")
    ap.add_argument("--once", action="store_true", help="send one update and exit")
    ap.add_argument("--demo", action="store_true", help="send random data")
    ap.add_argument("--check", action="store_true", help="report the logs, token and board it finds, then exit")
    ap.add_argument("--imu", action="store_true",
                    help="print the board's accelerometer readings, to set IMU_SHORT_AXIS / IMU_FLIP")
    ap.add_argument("--music", nargs="+", metavar="PATH",
                    help="audio files or folders to play through the board's speaker")
    ap.add_argument("--shuffle", action="store_true", help="shuffle the --music playlist")
    ap.add_argument("--loop", action="store_true", help="start the playlist again when it ends")
    ap.add_argument("--volume", type=int, metavar="0-100", help="speaker volume")
    ap.add_argument("--history-file", default=HISTORY_FILE,
                    help=f"where all-time daily totals are kept for the stats page (default {HISTORY_FILE})")
    args = ap.parse_args()
    if args.print and args.music:
        ap.error("--music needs the board, it can't be combined with --print")

    if args.imu:
        board = find_board(args.port)
        if not board:
            sys.exit("board not found")
        log(f"connected to {board.port}; turn the board around, Ctrl-C to stop")
        while True:
            board.send("@IMU")
            for l in board.read_lines(0.5):
                if l.startswith(("@IMU", "@ROT")):
                    print(l, flush=True)

    reader = LogReader(History(args.history_file))
    if not args.demo:
        dirs = claude_dirs()
        n = reader.scan()
        if args.check:
            check(args, reader)
            return
        if not dirs:
            log("warning: no Claude Code logs found in ~/.claude/projects or ~/.config/claude/projects")
        log(f"read {n} usage records from {', '.join(dirs) or 'nowhere'}")
        if n == 0:
            log("note: only Claude Code running on this Mac writes these logs. Usage in the Claude app, "
                "on claude.ai or in Claude Code on the web shows up only through the plan limits.")

    lim = {"data": None, "at": 0.0, "err": None, "thread": None}

    if args.print:
        next_stats = 0.0
        while True:
            print(encode(usage_fields(args, reader, lim)), flush=True)
            if time.time() >= next_stats:
                print(encode(stats_fields(args, reader.history), "@CS"), flush=True)
                next_stats = time.time() + STATS_INTERVAL
            if args.once:
                return
            time.sleep(args.interval)

    player = Player(args.music, args.shuffle, args.loop, args.volume) if args.music else None
    board = None
    next_usage = 0.0
    next_stats = 0.0
    last_summary = None
    last_stats = None
    ok_due = None           # when an @OK for the last update should have arrived
    start_player = False
    warned_ack = False

    while True:
        if board is None:
            board = find_board(args.port)
            if not board:
                log("board not found, retrying in 5s (is it plugged in and running the firmware?)")
                time.sleep(5)
                continue
            log(f"connected to {board.port}")
            next_usage = 0.0
            next_stats = 0.0
            last_summary = None
            last_stats = None
            start_player = player is not None
        try:
            if time.time() >= next_usage:
                fields = usage_fields(args, reader, lim)
                board.send(encode(fields))
                next_usage = time.time() + args.interval
                ok_due = time.time() + 2
                s = summary(fields)
                if s != last_summary:
                    log("sending " + s)
                    last_summary = s
                if time.time() >= next_stats:
                    # Slow-moving, so much less often than the usage
                    stats = stats_fields(args, reader.history)
                    board.send(encode(stats, "@CS"))
                    next_stats = time.time() + STATS_INTERVAL
                    s = stats_summary(stats)
                    if s != last_stats:
                        log("sending " + s)
                        last_stats = s
                if args.once:
                    board.read_lines(0.5)
                    return
            if start_player:
                # After the first update, which may wait for the plan limits
                player.connected(board)
                start_player = False
            streaming = player.pump(board) if player else False
            # Wait for the board's replies; briefly while audio is flowing
            wait = 0.005 if streaming else min(1.0, max(0.0, next_usage - time.time()))
            for line in board.read_lines(wait):
                if line == "@OK":
                    ok_due = None
                elif player:
                    player.handle(board, line)
            if ok_due and time.time() > ok_due:
                ok_due = None
                if not warned_ack:
                    log("warning: the board didn't acknowledge the update (@OK). Is its firmware up to date?")
                    warned_ack = True
        except OSError as e:
            log(f"lost the board: {e}")
            board.close()
            board = None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
