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
   The keychain token expires after a few hours unless Claude Code runs and
   renews it. `claude setup-token` makes a long-lived one to save in the file.
   Tokens are only read, never refreshed, so this can't log Claude Code out.
   Without a working token, the display falls back to an estimate from the
   local logs (shown as "5-HOUR est.").
   Pass --no-limits to skip this entirely.

Only the Python 3 standard library is needed.

    python3 tools/claude_usage_host.py             # auto-detect the board
    python3 tools/claude_usage_host.py --print     # dry run, print the lines
    python3 tools/claude_usage_host.py --demo      # fake data, to test the screen
    python3 tools/claude_usage_host.py --check     # show what it finds, then exit
    python3 tools/claude_usage_host.py --imu       # live accelerometer readings
"""

import argparse
import glob
import json
import fcntl
import os
import platform
import random
import select
import struct
import subprocess
import sys
import termios
import time
import tty
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BLOCK = timedelta(hours=5)
HOURS = 12
KEEP = timedelta(days=8)

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
    """Incrementally reads new lines from the JSONL logs."""

    def __init__(self):
        self.offsets = {}   # path -> bytes already read
        self.seen = set()   # (message id, request id), streaming writes duplicates
        self.entries = []   # (time, model, tokens, cost), sorted by time

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
                        new.append(e)
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
        return (ts, model, inp + out + cw + cr, float(cost))


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
# Plan limits (optional)
# --------------------------------------------------------------------------

TOKEN_FILE = "~/.config/claude-usage-display/token"


def oauth_token(token_file=TOKEN_FILE):
    """Returns (token, where it came from), or (None, None)."""
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if tok:
        return tok, "$CLAUDE_CODE_OAUTH_TOKEN"
    path = os.path.expanduser(token_file)
    if os.path.isfile(path):
        with open(path) as f:
            tok = f.read().strip()
        if tok:
            return tok, path
    blob = None
    where = None
    if platform.system() == "Darwin":
        try:
            blob = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=10).stdout
            where = "macOS keychain (Claude Code login)"
        except (OSError, subprocess.SubprocessError):
            blob = None
    if not blob:
        path = os.path.expanduser("~/.claude/.credentials.json")
        if os.path.exists(path):
            with open(path) as f:
                blob = f.read()
            where = path
    if not blob:
        return None, None
    try:
        return json.loads(blob)["claudeAiOauth"]["accessToken"], where
    except (ValueError, KeyError, TypeError):
        return None, None


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


def fetch_limits(token_file=TOKEN_FILE):
    tok, where = oauth_token(token_file)
    if not tok:
        raise LimitsError(
            "no OAuth token: log in to Claude Code on this Mac (run `claude`), or run "
            f"`claude setup-token` and save the token in {TOKEN_FILE}", "limits: no token")
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + tok,
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
        "User-Agent": "claude-usage-display/1",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise LimitsError(
                f"the token from {where} was rejected (401), probably expired. Running `claude` "
                f"renews the keychain one; `claude setup-token` makes a long-lived one for {TOKEN_FILE}",
                "limits: token expired")
        if e.code == 403:
            raise LimitsError(f"the token from {where} isn't allowed to read usage (403)",
                              "limits: no access")
        raise LimitsError(f"usage request failed: HTTP {e.code}", f"limits: HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise LimitsError(f"usage request failed: {e}", "limits: offline")

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
        data = (line + "\n").encode()
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

def encode(fields):
    def clean(v):
        return str(v).replace(";", ",").replace("=", "-").replace("\n", " ")
    return "@CU " + ";".join(f"{k}={clean(v)}" for k, v in fields.items())


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

    print("Plan limits:")
    if args.no_limits:
        print("  skipped (--no-limits)")
    else:
        tok, where = oauth_token(args.token_file)
        print(f"  token: {where or 'none found'}")
        try:
            lim = fetch_limits(args.token_file)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (default: auto-detect /dev/cu.usbmodem*)")
    ap.add_argument("--interval", type=float, default=15, help="seconds between updates (default 15)")
    ap.add_argument("--limits-interval", type=float, default=120,
                    help="seconds between plan-limit requests (default 120)")
    ap.add_argument("--no-limits", action="store_true", help="don't query plan limits, local logs only")
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
    args = ap.parse_args()

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

    reader = LogReader()
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

    limits, limits_at, limits_err = None, 0.0, None
    board = None
    last_summary = None
    warned_ack = False

    while True:
        if args.demo:
            fields = demo_fields()
        else:
            reader.scan()
            fields = local_stats(reader.entries, args.block_limit)
            fields["src"] = "l"
            if args.no_limits:
                limits_err = LimitsError("disabled", "")
            elif time.time() - limits_at >= args.limits_interval:
                limits_at = time.time()
                try:
                    limits = fetch_limits(args.token_file)
                    if limits_err is not None:
                        log("plan limits OK")
                    limits_err = None
                except (LimitsError, ValueError) as e:
                    if limits_err is None or str(e) != str(limits_err):
                        log(f"plan limits unavailable, using the local estimate: {e}")
                    limits_err, limits = e, None
            if limits:
                fields.update(limits)
            st = status_text(reader.entries, limits_err)
            if st:
                fields["st"] = st
            fields["t"] = datetime.now().strftime("%H:%M")

        line = encode(fields)

        if args.print:
            print(line, flush=True)
        else:
            if board is None:
                board = find_board(args.port)
                if board:
                    log(f"connected to {board.port}")
                    last_summary = None
                else:
                    log("board not found, retrying in 5s (is it plugged in and running the firmware?)")
                    time.sleep(5)
                    continue
            try:
                board.send(line)
                replies = board.read_lines(0.5)
            except OSError as e:
                log(f"lost the board: {e}")
                board.close()
                board = None
                continue
            if "@OK" not in replies and not warned_ack:
                log("warning: the board didn't acknowledge the update (@OK). Is its firmware up to date?")
                warned_ack = True
            s = summary(fields)
            if s != last_summary:
                log("sending " + s)
                last_summary = s

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
