#!/usr/bin/env python3
"""
Send Claude usage to the RP2350 Touch LCD 3.49 over USB serial.

Two data sources, both on your Mac:

1. Claude Code's local logs (always used)
   ~/.claude/projects/**/*.jsonl (and ~/.config/claude/projects, or
   $CLAUDE_CONFIG_DIR). Every assistant message there carries its token usage,
   which gives today's tokens, API-equivalent cost, the hourly history, the
   current 5-hour window and the burn rate.

2. Your plan limits (optional, on by default)
   The same "5-hour" and "weekly" percentages that Claude Code's /usage shows.
   They come from an unofficial endpoint, using the OAuth token Claude Code
   keeps in the macOS keychain. The token is only read, never refreshed, so it
   can't log Claude Code out. If it is missing or expired, the display falls
   back to an estimate from the local logs (shown as "5-HOUR est.").
   Pass --no-limits to skip this entirely.

It can also play music from a folder on the Mac through the board's speaker
(--music). The audio is decoded on the Mac to 24 kHz 16-bit mono and streamed
over the same USB serial link. Decoding uses ffmpeg if it is installed,
otherwise macOS's built-in afconvert (MP3, AAC/M4A, WAV, AIFF, FLAC, ...).
Tap the now-playing row on the screen to skip to the next track.

Only the Python 3 standard library is needed.

    python3 tools/claude_usage_host.py             # auto-detect the board
    python3 tools/claude_usage_host.py --print     # dry run, print the lines
    python3 tools/claude_usage_host.py --demo      # fake data, to test the screen
    python3 tools/claude_usage_host.py --music ~/Music/Desk --shuffle --volume 60
"""

import argparse
import glob
import json
import os
import platform
import random
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import tty
import urllib.error
import urllib.request
import wave
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

def oauth_token():
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if tok:
        return tok
    blob = None
    if platform.system() == "Darwin":
        try:
            blob = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            blob = None
    if not blob:
        path = os.path.expanduser("~/.claude/.credentials.json")
        if os.path.exists(path):
            with open(path) as f:
                blob = f.read()
    if not blob:
        return None
    try:
        return json.loads(blob)["claudeAiOauth"]["accessToken"]
    except (ValueError, KeyError, TypeError):
        return None


def minutes_until(iso):
    if not iso:
        return -1
    try:
        return max(0, int((parse_ts(iso) - datetime.now(timezone.utc)).total_seconds() // 60))
    except ValueError:
        return -1


def fetch_limits():
    tok = oauth_token()
    if not tok:
        raise RuntimeError("no Claude Code OAuth token found (log in to Claude Code first)")
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + tok,
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
        "User-Agent": "claude-usage-display/1",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)

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


def usage_fields(args, reader, lim):
    """lim is a dict holding the plan-limit cache between calls."""
    if args.demo:
        return demo_fields()
    reader.scan()
    fields = local_stats(reader.entries, args.block_limit)
    fields["src"] = "l"
    if not args.no_limits and time.time() - lim["at"] >= args.limits_interval:
        lim["at"] = time.time()
        try:
            lim["data"] = fetch_limits()
            lim["err"] = None
        except (urllib.error.URLError, RuntimeError, ValueError, OSError) as e:
            if str(e) != lim["err"]:
                log(f"plan limits unavailable, using the local estimate: {e}")
            lim["err"], lim["data"] = str(e), None
    if lim["data"]:
        fields.update(lim["data"])
    fields["t"] = datetime.now().strftime("%H:%M")
    return fields


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (default: auto-detect /dev/cu.usbmodem*)")
    ap.add_argument("--interval", type=float, default=15, help="seconds between updates (default 15)")
    ap.add_argument("--limits-interval", type=float, default=120,
                    help="seconds between plan-limit requests (default 120)")
    ap.add_argument("--no-limits", action="store_true", help="don't query plan limits, local logs only")
    ap.add_argument("--block-limit", type=float, metavar="USD",
                    help="for the local estimate: API-equivalent USD that counts as 100%% of a 5-hour window "
                         "(default: your busiest earlier window)")
    ap.add_argument("--print", action="store_true", help="print the lines instead of sending them")
    ap.add_argument("--once", action="store_true", help="send one update and exit")
    ap.add_argument("--demo", action="store_true", help="send random data")
    ap.add_argument("--music", nargs="+", metavar="PATH",
                    help="audio files or folders to play through the board's speaker")
    ap.add_argument("--shuffle", action="store_true", help="shuffle the --music playlist")
    ap.add_argument("--loop", action="store_true", help="start the playlist again when it ends")
    ap.add_argument("--volume", type=int, metavar="0-100", help="speaker volume")
    args = ap.parse_args()
    if args.print and args.music:
        ap.error("--music needs the board, it can't be combined with --print")

    reader = LogReader()
    if not args.demo:
        dirs = claude_dirs()
        if not dirs:
            log("warning: no Claude Code logs found in ~/.claude/projects or ~/.config/claude/projects")
        n = reader.scan()
        log(f"read {n} usage records from {', '.join(dirs) or 'nowhere'}")

    lim = {"data": None, "at": 0.0, "err": None}

    if args.print:
        while True:
            print(encode(usage_fields(args, reader, lim)), flush=True)
            if args.once:
                return
            time.sleep(args.interval)

    player = Player(args.music, args.shuffle, args.loop, args.volume) if args.music else None
    board = None
    next_usage = 0.0

    while True:
        if board is None:
            board = find_board(args.port)
            if not board:
                log("board not found, retrying in 5s (is it plugged in and running the firmware?)")
                time.sleep(5)
                continue
            log(f"connected to {board.port}")
            next_usage = 0.0
            if player:
                player.connected(board)
        try:
            if time.time() >= next_usage:
                board.send(encode(usage_fields(args, reader, lim)))
                next_usage = time.time() + args.interval
                if args.once:
                    board.read_lines(0.3)
                    return
            streaming = player.pump(board) if player else False
            # Wait for the board's replies; briefly while audio is flowing
            wait = 0.005 if streaming else min(1.0, max(0.0, next_usage - time.time()))
            for line in board.read_lines(wait):
                if player:
                    player.handle(board, line)
        except OSError as e:
            log(f"lost the board: {e}")
            board.close()
            board = None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
