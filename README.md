# RP2350Touch3.49

![Waveshare RP2350 Touch LCD 3.49](docs/images/waveshare-rp2350-touch-3.49.jpg)

A desk display for your Claude usage, built on the
[Waveshare RP2350 Touch LCD 3.49](https://www.waveshare.com/wiki/RP2350-Touch-LCD-3.49).
The repo holds two parts:

- **Firmware** for the board, which draws the screen and plays audio.
- **A host script** for the Mac, `tools/claude_usage_host.py`, which works out
  the numbers and sends them over the USB cable.

The board has no Wi-Fi or Bluetooth radio, so everything goes over the same USB
cable that powers it. No drivers are needed.

For how it works inside (serial protocol, LVGL port, drivers, pin map, the
libraries it builds on), see the [developer guide](docs/README.md).

## What it does

**Claude usage display.** The 3.49" screen is used in landscape (640×172):

- **Left:** the current 5-hour window as an arc (green < 60%, orange < 85%,
  red above), with the time until it resets.
- **Middle:** weekly limit bars (all models, plus a per-model limit if your plan
  has one), and today's messages, tokens and API-equivalent cost.
- **Right:** tokens per hour over the last 12 hours, the model you used last,
  the recent burn rate, and the Mac's clock. The dot beside the clock is green
  while updates are arriving, amber once they stop for 2 minutes.

**Music from the Mac.** The host script can play a folder of music through the
board's speaker. The files stay on the Mac. The right-hand card shows the track
title, elapsed and total time and a progress bar.

**Auto-rotation.** Turn the board over and the picture flips 180° to stay
upright.

**Touch.** Drag up or down along the left edge for backlight brightness, and
along the right edge for speaker volume; a level meter shows on that edge while
you drag. Swipe left or right in the middle to switch between the dashboard and
the usage stats page (still a placeholder). Tap the now-playing row to skip to
the next track.

## What you need

| For | You need |
|---|---|
| The display | A Waveshare RP2350 Touch LCD 3.49 and a USB **data** cable |
| Running the host script | macOS with Python 3. Only the standard library is used |
| Usage numbers | [Claude Code](https://code.claude.com/docs/en/overview) installed and logged in on this Mac |
| Music (optional) | `ffmpeg` for any format (`brew install ffmpeg`). Without it, macOS's built-in `afconvert` handles MP3, AAC/M4A, ALAC, WAV, AIFF, CAF and FLAC |
| Building the firmware | [Pico SDK](https://github.com/raspberrypi/pico-sdk) 2.0.0 or newer, the ARM GNU Toolchain, CMake 3.13 or newer, Ninja and [`picotool`](https://github.com/raspberrypi/picotool) |

The host script also runs on Linux. There it looks for the board at
`/dev/ttyACM*` and for the Claude Code login in `~/.claude/.credentials.json`.

## Install

There is no prebuilt firmware, so you build it and flash it to the board once.
The host script needs no installation.

### 1. Install the Pico SDK

RP2350 support requires Pico SDK 2.0.0 or newer. Clone it with submodules:

```sh
git clone --depth 1 --branch 2.1.1 https://github.com/raspberrypi/pico-sdk.git ~/pico-sdk
cd ~/pico-sdk
git submodule update --init --depth 1
```

### 2. Install the ARM cross-compiler

Do **not** use Homebrew's `arm-none-eabi-gcc` formula — it ships without newlib
(missing `nosys.specs`), which breaks linking. Use the official ARM GNU Toolchain
instead. On Apple Silicon:

```sh
curl -L -o /tmp/arm-toolchain.tar.xz \
  "https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/arm-gnu-toolchain-14.2.rel1-darwin-arm64-arm-none-eabi.tar.xz"
mkdir -p ~/.local
tar -xf /tmp/arm-toolchain.tar.xz -C ~/.local
```

(For Intel Macs, swap `arm64` for `x86_64` in the URL. For Linux, use the
`x86_64-linux` tarball, or `brew install --cask gcc-arm-embedded` on macOS if
you're able to enter a sudo password interactively.)

Also install `picotool`, used by the SDK's post-build steps:

```sh
brew install picotool
```

### 3. Set environment variables

```sh
export PICO_SDK_PATH=~/pico-sdk
export PATH="$HOME/.local/arm-gnu-toolchain-14.2.rel1-darwin-arm64-arm-none-eabi/bin:$PATH"
```

Add these to your `~/.zshrc` (or equivalent) to avoid re-exporting them every session.

The project includes its own copy of `pico_sdk_import.cmake`, so instead of the
environment variable you can also pass `-DPICO_SDK_PATH=~/pico-sdk` to `cmake`, or set
`PICO_SDK_FETCH_FROM_GIT=1` to have CMake download the SDK.

### 4. Configure and build

```sh
mkdir -p build && cd build
cmake -G Ninja ..
ninja
```

The resulting firmware is at `build/src/LVGL.uf2`.

### 5. Flash

Put the board in BOOTSEL mode, then do one of these:

```sh
ninja install                               # from build/, uses picotool
# or
picotool load build/src/LVGL.uf2 -v
picotool reboot
```

You can also copy `build/src/LVGL.uf2` onto the drive the board shows up as in
BOOTSEL mode. If the board is already running this firmware, `picotool` can
reboot it into BOOTSEL and flash it in one go:

```sh
picotool load -f -x build/src/LVGL.uf2
```

## Run

Plug the board in and start the host script:

```sh
python3 tools/claude_usage_host.py            # finds the board and updates it every 15 s
python3 tools/claude_usage_host.py --print    # dry run: print what it would send
python3 tools/claude_usage_host.py --demo     # random numbers, to test the screen
python3 tools/claude_usage_host.py --check    # show what it finds, then exit
```

`--check` lists the log folders and how many records they hold, where the token
came from and whether the limits request works, and whether the board answers
and acknowledges a test update. While running, the script also logs a one-line
summary whenever the values it sends change.

### Options

| Option | What it does |
|---|---|
| `--port PORT` | Serial port to use. Default: auto-detect `/dev/cu.usbmodem*` |
| `--interval SECONDS` | Time between updates. Default 15 |
| `--limits-interval SECONDS` | Time between plan-limit requests. Default 120 |
| `--no-limits` | Don't ask for plan limits; use the local logs only |
| `--no-renew` | Don't run `claude -p` to renew an expired Claude Code login |
| `--token-file FILE` | File holding an OAuth token. Default `~/.config/claude-usage-display/token` |
| `--block-limit USD` | For the local estimate: the API-equivalent cost that counts as 100% of a 5-hour window |
| `--print` | Print the lines instead of sending them |
| `--once` | Send one update and exit |
| `--demo` | Send random data |
| `--check` | Report the logs, token and board it finds, then exit |
| `--music PATH ...` | Audio files or folders to play through the board's speaker |
| `--shuffle`, `--loop` | Shuffle the playlist; start it again when it ends |
| `--volume 0-100` | Speaker volume |
| `--imu` | Print the board's accelerometer readings (see the [developer guide](docs/README.md#auto-rotation)) |

### Start it at login

Save this as `~/Library/LaunchAgents/com.claude-usage.display.plist` (fix the
path), then run
`launchctl load ~/Library/LaunchAgents/com.claude-usage.display.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.claude-usage.display</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>/path/to/RP2350Touch3.49/tools/claude_usage_host.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

### Music from the Mac

```sh
python3 tools/claude_usage_host.py --music ~/Music/Desk
python3 tools/claude_usage_host.py --music ~/Music/Desk --shuffle --loop --volume 60
python3 tools/claude_usage_host.py --music song1.mp3 song2.m4a
```

Usage updates carry on as normal while music plays. Tap the now-playing row to
skip to the next track.

For decoding, the script uses `ffmpeg` if it is installed. Otherwise it uses
`afconvert`, which decodes the whole track to a temporary file first; that takes
a second or two before playback starts. Without either, only WAV files already
in 24 kHz 16-bit mono play.

## Where the numbers come from

The host script reads two things:

1. **Claude Code's local logs**, `~/.claude/projects/**/*.jsonl` (also
   `~/.config/claude/projects` and `$CLAUDE_CONFIG_DIR`). Each assistant message
   there records its token usage, which gives the totals, the hourly history and
   the burn rate. Cost is estimated from list API prices. It isn't what a Pro or
   Max subscription charges you.
2. **Your plan limits**: the same 5-hour and weekly percentages that Claude
   Code's `/usage` shows. These come from an unofficial endpoint
   (`api.anthropic.com/api/oauth/usage`) and need an OAuth token. The script
   looks for one in this order:
   - `$CLAUDE_CODE_OAUTH_TOKEN`
   - the file `~/.config/claude-usage-display/token` (or `--token-file`), for a
     token you got some other way
   - the token Claude Code keeps in the macOS keychain (`Claude Code-credentials`)
     once you've logged in. The first time, macOS asks whether `security` may
     read it.

   The script tries every token it finds, in that order, and uses the first
   that works. Without a working token, or with `--no-limits`, the arc shows an
   estimate instead, labelled `5-HOUR est.`. The estimate compares the current
   window's cost with your busiest earlier window, or with `--block-limit USD`.

Only Claude Code **running on this Mac** writes the logs. Usage in the Claude
app, on claude.ai or in Claude Code on the web leaves nothing in `~/.claude`, so
if that's where you use Claude, every local number stays at 0. Those sessions
do count towards the plan limits, so for them you need a working token.

### The token

The token that can read usage is the one Claude Code keeps in the keychain after
you log in on this Mac (`claude auth login`). Tokens from `claude setup-token`
are refused (403, or 429 "rate limited"): they can run Claude but not read
account usage.

The keychain token expires within hours, and only Claude Code can renew it. When
the script finds it expired, it runs `claude -p` with a one-word prompt on Haiku
so that Claude Code renews it, then reads the new token. That costs a few Haiku
tokens of your plan a few times a day. It looks for `claude` on your `PATH` and
then in the usual install folders (`~/.local/bin`, Homebrew, nvm, ...), so it
also works from launchd, which starts the script with a bare `PATH`. Pass
`--no-renew` to turn it off; then, while the token is expired, the arc shows
the local estimate until you run `claude` yourself. If the login has lapsed
completely, run `claude auth login`.

### Notes on the screen

When numbers are estimated or missing, the board shows a short reason in amber
under the arc:

| Note | Meaning |
|---|---|
| `no usage data on Mac` | No Claude Code logs were found on this Mac |
| `limits: no token` | No OAuth token was found. Log in with `claude auth login` |
| `limits: token expired` | The token has expired and wasn't renewed. Run `claude` |
| `limits: rate limited` | The usage endpoint answered 429. The script waits and asks again |
| `limits: no access` | The token isn't allowed to read usage (a `claude setup-token` token) |
| `limits: offline` | The request couldn't reach `api.anthropic.com` |
| `limits: HTTP <code>` | The usage endpoint answered with another error |

Run `python3 tools/claude_usage_host.py --check` for the full reason.

## Privacy

Everything runs on your Mac and the board. There is no server, account or
telemetry of this project's own.

- **What it reads.** From Claude Code's logs, the script takes each message's
  timestamp, model name, token counts and cost. It doesn't use the text of your
  prompts or Claude's replies, and it doesn't write to the logs.
- **What goes over the network.** One kind of request: a `GET` to
  `https://api.anthropic.com/api/oauth/usage`, every 2 minutes by default,
  carrying your OAuth token. It goes to Anthropic and nowhere else.
  `--no-limits` turns it off, and the script then makes no network requests.
- **Your token.** The script reads the token and keeps it in memory. It doesn't
  save, print or refresh it, and it never uses the refresh token, so it can't
  log Claude Code out. The first time it reads the keychain, macOS asks for
  your permission.
- **Renewing the login.** When the keychain token has expired, the script runs
  `claude -p "Reply with the single word: ok"` on Haiku, so Claude Code itself
  sends that one request to Anthropic. The session isn't saved. `--no-renew`
  turns it off.
- **What the board gets.** Over USB only: the percentages, token counts, cost,
  model name and clock listed in the
  [serial protocol](docs/README.md#serial-protocol), and with `--music` the
  audio and the track title. The board has no radio and the firmware stores
  nothing; the numbers are gone when it loses power.
- **Music.** Files are decoded on the Mac. With `afconvert`, the decoded copy is
  a temporary file that is deleted when the track ends.

The usage endpoint is unofficial and undocumented. It may change or stop working
without notice; the display then falls back to the local estimate.

## Credits

This project builds on the work of [Dr Jon Durrant](https://github.com/jondurrant),
whose LVGL port and widget code for this board form its foundation, and on the
demos and hardware drivers supplied by [Waveshare](https://www.waveshare.com).
The UI is built with [LVGL](https://lvgl.io). The full list of integrated
libraries and sources is in the
[developer guide](docs/README.md#integrated-libraries).

## License

Released under the [MIT License](LICENSE). Vendored libraries in `lib/` keep their
own licenses.
