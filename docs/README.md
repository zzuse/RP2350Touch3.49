# Developer guide

How the Claude usage display works inside: the data path, the serial protocol,
the firmware, the LVGL port, the board drivers and the libraries it builds on.

To install and run it, see the [main README](../README.md).

- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Integrated libraries](#integrated-libraries)
- [Serial protocol](#serial-protocol)
- [Host script](#host-script)
- [Firmware](#firmware)
- [LVGL port](#lvgl-port)
- [Audio and SD card drivers](#audio-and-sd-card-drivers)
- [Pin and resource map](#pin-and-resource-map)
- [Build notes](#build-notes)
- [Online sources](#online-sources)
- [Credits](#credits)

## Architecture

```
Mac                                              Board (RP2350, two cores)
┌──────────────────────────────┐                ┌──────────────────────────────────┐
│ tools/claude_usage_host.py   │                │ core 0                           │
│                              │   USB CDC      │   SerialLink   parse lines       │
│  ~/.claude/projects/*.jsonl ─┼─► @CU ... ────►│   UsageScreen  LVGL widgets      │
│  api.anthropic.com usage ────┤   @A <pcm> ───►│   AutoRotate   QMI8658, 100 ms   │
│  music files ► ffmpeg ───────┘                │   AudioPlayer  ring buffer (in)  │
│                              │◄── @OK, @AF ───│ core 1                           │
└──────────────────────────────┘    @ANEXT      │   AudioPlayer  ring buffer ► I2S │
                                                │   power button                   │
                                                └──────────────────────────────────┘
```

The board has no radio, so the Mac does the work that needs files or the
network. The host script sends a usage snapshot as one text line every 15 s, and
audio as raw PCM in between, over the board's USB CDC serial port (the Pico
SDK's stdio).

On the board, core 0 runs the LVGL loop (`lv_timer_handler()` in
`src/main.cpp`). Everything on core 0 hangs off LVGL timers: `UsageScreen` polls
the serial link every 5 ms and refreshes its clock-driven parts every second,
and `AutoRotate` samples the accelerometer every 100 ms. Core 1 does nothing but
feed the I2S PIO and watch the power button.

## Repository layout

| Path | What is there |
|---|---|
| `src/main.cpp` | Start-up: board, LCD, RTC, IMU, audio, LVGL, then the main loop |
| `src/SerialLink.*` | Parser for the line protocol |
| `src/UsageData.h` | The usage snapshot struct the parser fills |
| `src/UsageScreen.*` | The UI: arc, bars, hourly chart, now-playing row |
| `src/AudioPlayer.*` | Ring buffer and playback of streamed PCM |
| `src/AutoRotate.*` | Flips the picture when the board is turned over |
| `src/Widgets.*` | Jon Durrant's original demo dashboard. Still compiled, no longer shown |
| `port/lvgl/` | `lv_conf.h` and the display, touch and tick glue (`lv_port.c`) |
| `port/fatfs/` | This board's SD card configuration (`hw_config.c`) |
| `lib/lvgl/` | LVGL v8.1.0, vendored |
| `lib/touch349/` | Waveshare's board drivers: LCD, touch, QSPI PIO, RTC, IMU, PSRAM, ES8311, I2S PIO |
| `lib/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico/` | FatFs and the SD card driver, vendored |
| `boards/` | Board header for the Pico SDK |
| `tools/claude_usage_host.py` | The host script |
| `tools/wav2data.py` | Converts a WAV into a C array |
| `CMakeLists.txt`, `touch349.cmake`, `lvgl.cmake`, `fatfs.cmake`, `src/CMakeLists.txt` | The build |

## Integrated libraries

| Library | Version | Where | License | Used for |
|---|---|---|---|---|
| [Pico SDK](https://github.com/raspberrypi/pico-sdk) | 2.0.0 or newer (built with 2.1.1) | outside the repo, `PICO_SDK_PATH` | BSD-3-Clause | HAL, PIO, DMA, multicore, USB CDC stdio (via [TinyUSB](https://github.com/hathach/tinyusb)) |
| [LVGL](https://github.com/lvgl/lvgl/tree/v8.1.0) | 8.1.0 | `lib/lvgl` | MIT (`LICENCE.txt`) | UI |
| Waveshare board drivers | from Waveshare's demos for this board | `lib/touch349` | MIT-style permission notice in the file headers | LCD, touch, QSPI PIO, PCF85063A RTC, QMI8658 IMU, PSRAM, ES8311 codec, I2S PIO |
| TLSF allocator | by Matthew Conte, as shipped by Waveshare | `lib/touch349/PSRAM/tlsf` | BSD-3-Clause | PSRAM heap |
| [no-OS-FatFS-SD-SDIO-SPI-RPi-Pico](https://github.com/carlk3/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico) | 3.3.1 (upstream commit `aca1922`) | `lib/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico` | Apache-2.0 (`LICENSE`) | SD card over SPI |
| [FatFs](http://elm-chan.org/fsw/ff/00index_e.html) | bundled with the library above | same | FatFs license | FAT file system |

The firmware links the Pico SDK libraries `pico_stdlib`, `pico_multicore`,
`hardware_spi`, `hardware_i2c`, `hardware_pwm`, `hardware_adc`, `hardware_dma`,
`hardware_pio`, `hardware_irq` and `hardware_flash`.

The host script uses only the Python 3 standard library. It calls these
programs when they are present: `security` (macOS keychain), `claude` (to renew
the login), `ffmpeg` / `ffprobe` or `afconvert` (to decode music).

## Serial protocol

One line per message, newline terminated:

| Direction | Line | Reply |
|---|---|---|
| Mac → board | `@PING` | `@PONG claude-usage 1` (used to find the port) |
| Mac → board | `@CU key=value;key=value;...` | `@OK` |

| Key | Meaning |
|---|---|
| `sp`, `sr` | 5-hour window: percent used, minutes until reset (`-1` = unknown) |
| `wp`, `wr` | Weekly limit: percent used, minutes until reset |
| `w2p`, `w2l` | Per-model weekly limit: percent, label (e.g. `SONNET`) |
| `tt`, `tc`, `tm` | Today: tokens, cost in US cents, messages |
| `bt`, `br` | Tokens in the current 5-hour window, tokens per minute recently |
| `h` | 12 comma-separated hourly token counts, oldest first |
| `m`, `t`, `src` | Model name, Mac clock `HH:MM`, `o` = limits from the API / `l` = local estimate |
| `st` | Short note shown under the arc when numbers are estimated or zero (empty when all is well) |

Unknown keys are ignored, so the host and the firmware can be updated
separately.

Audio (see [Audio streaming](#audio-streaming)) uses the same link. It is
credit based: the Mac sends only as many bytes as the board last said it had
free.

| Direction | Line | Reply |
|---|---|---|
| Mac → board | `@PLAY dur=<seconds>;title=<text>` | `@AOK <free bytes>` |
| Mac → board | `@A <n>`, then `n` bytes of raw PCM | `@AF <free bytes>` |
| Mac → board | `@AQ` (ask for the free space again) | `@AF <free bytes>` |
| Mac → board | `@AEND` (no more data for this track) | `@ADONE` once it has played out |
| Mac → board | `@STOP`, `@VOL <0-100>` | none |
| board → Mac | `@ANEXT` (the now-playing row was tapped) | |

Two more lines exist for setting up [auto-rotation](#auto-rotation):

| Direction | Line | Reply |
|---|---|---|
| Mac → board | `@IMU` | `@IMU x=<n> y=<n> z=<n> rot=<90 or 270>` (accelerometer readings) |
| board → Mac | `@ROT 90` or `@ROT 270` (the picture flipped) | |

The firmware side is `src/SerialLink.cpp` (parser), `src/UsageScreen.cpp` (UI) and
`src/AudioPlayer.cpp` (playback).

## Host script

`tools/claude_usage_host.py` is one file, in this order:

- **Local logs.** `LogReader` reads the JSONL files incrementally: it remembers
  a byte offset per file and only parses complete new lines. Streaming writes
  the same message more than once, so entries are deduplicated on (message id,
  request id). It keeps 8 days of entries. `local_stats()` turns them into
  today's totals, the 12 hourly buckets and the burn rate over the last 15
  minutes. `blocks()` groups entries into 5-hour windows the way
  [ccusage](https://github.com/ryoppippi/ccusage) does. Cost comes from the
  log's `costUSD` when present, otherwise from the `PRICES` table.
- **Plan limits.** `oauth_tokens()` collects every token it can find, and
  `fetch_limits()` asks `api.anthropic.com/api/oauth/usage` with each until one
  works. A 429 is remembered per token for its `Retry-After` time. When the
  Claude Code login has expired (401), `renew_login()` runs `claude -p` so that
  Claude Code renews it, at most once every 10 minutes. `find_claude()` looks on
  `PATH` and then in the usual install folders, because launchd starts the
  script with a bare `PATH`.
- **Serial link.** `Board` opens the port raw and non-blocking and raises DTR,
  which the Pico's USB serial needs before it accepts input. `find_board()`
  sends `@PING` to each candidate port.
- **Audio.** A track is decoded to 24 kHz 16-bit mono by `ffmpeg` (piped) or
  `afconvert` (to a temporary WAV), then sent in `@A` chunks as the board
  reports free space.
- **Main loop.** The plan limits are fetched on a background thread, because
  the request and especially the renewal can take many seconds and the loop has
  to keep feeding audio meanwhile. Only the first fetch is waited for.

## Firmware

### Audio streaming

The host decodes each file to 24 kHz, 16-bit mono (the rate the ES8311 codec is
clocked for) and streams it over the USB serial link, at 48 KB/s.

- Core 0 reads USB in bulk into a 32768-sample (1.4 s) ring buffer. The USB
  receive buffer is raised from 64 bytes to 4 KB (`src/CMakeLists.txt`) so it
  keeps up while LVGL is busy redrawing.
- Core 1 feeds the I2S PIO, and `pio_sm_put_blocking()` paces it at the codec's
  sample rate. Between chunks of 5 ms it still does the power-button check it
  did before.
- Playback starts once 0.5 s is buffered. If the buffer runs dry, it plays
  silence until data arrives. The speaker amplifier (`PA_CTRL`) is switched off
  between tracks to avoid hiss.
- Every shared field has a single writer: core 0 owns the write index and the
  stream mode, core 1 owns the read index and the started/done flags. Emptying
  the buffer is a request that core 1 carries out.

### Landscape mode

LVGL renders a 640×172 frame, and the flush callback in `port/lvgl/lv_port.c`
rotates it into the panel's native 172×640 scan order. It fills two small
32-row buffers in turn, rotating into one while DMA sends the other, so it
doesn't need a second 220 KB frame buffer. Touch coordinates are rotated to
match. `DISP_ROTATION` in `port/lvgl/lv_port.h` sets the rotation at boot, 90°
or 270°. `DISP_LANDSCAPE 0` restores the original portrait behaviour.

### Auto-rotation

`src/AutoRotate.cpp` reads the QMI8658 accelerometer every 100 ms. When you turn
the board over, the picture flips 180° to stay upright. The new orientation has
to hold for 0.6 s first, so knocking or carrying the board doesn't flip it. The
layout is landscape only, so standing the board up in portrait, or laying it
flat, keeps whatever orientation it had. At boot the board starts in whichever
landscape orientation it is held in.

Where the IMU chip's axes point relative to the panel depends on how it sits on
the board, so two settings in `src/AutoRotate.h` may need changing:

- `IMU_SHORT_AXIS`: the accelerometer axis along the panel's short side (0 = X,
  1 = Y). If the screen never flips, or flips when you stand the board up in
  portrait, change it.
- `IMU_FLIP`: set to 1 if the picture is upside down in both orientations.

`python3 tools/claude_usage_host.py --imu` prints the live readings. The axis
that swings between about +g and −g as you turn the board over is the short
axis. The board also prints `@ROT 90` or `@ROT 270` each time it flips.
`AUTO_ROTATE 0` turns the feature off.

## LVGL port

LVGL v8.1.0 is vendored in `lib/lvgl` and is essentially upstream. The
board-specific code lives outside it, in `port/lvgl/` and `lvgl.cmake`.

### Changes to LVGL itself

- `lib/lvgl/src/core/lv_refr.c` is the only source file that differs from upstream.
  The perf/memory monitor overlays get zero padding, a fixed 120px width on the
  perf label and a 1px offset on the memory label, to suit the narrow 172px
  screen. Both monitors are disabled by default.
- `lib/lvgl/CMakeLists.txt` is replaced with a minimal Pico-style file. It is not
  used; the build goes through the top-level `lvgl.cmake`.

### The port

- **`lvgl.cmake`** builds LVGL as a static library from `lib/lvgl/src` plus
  `port/lvgl`, and links it against `touch349` (the board drivers). `lv_conf.h`
  lives in `port/lvgl`, outside the vendored library.
- **`port/lvgl/lv_conf.h`** differs from LVGL's `lv_conf_template.h` as follows:
  - `LV_COLOR_16_SWAP 1`, because the QSPI panel expects byte-swapped RGB565.
  - `LV_DISP_DEF_REFR_PERIOD` 30 ms → 10 ms.
  - Montserrat 16/24/26/28/30 enabled, and `LV_FONT_DEFAULT` 14 → 24.
  - Monitor positions moved to `LV_ALIGN_LEFT_MID` / `LV_ALIGN_RIGHT_MID`.
- **`port/lvgl/lv_port.c`** (`LVGL_Init()`) connects LVGL to the hardware. The
  panel is 172×640 (portrait). LVGL sees it as 640×172 landscape by default
  (see [Landscape mode](#landscape-mode)):
  - **Display:** one full-screen draw buffer with `full_refresh`. In portrait
    mode the flush callback sets the LCD window, sends `0x2C` (RAMWR) over QSPI
    and starts a DMA transfer into the PIO TX FIFO. The DMA IRQ deselects the
    chip and calls `lv_disp_flush_ready()`, so flushing is asynchronous. In
    landscape mode the flush rotates and sends the frame in chunks and waits
    for them to finish, so it is synchronous.
  - **Touch:** a GPIO falling-edge IRQ reads the touch controller and latches
    x/y. The LVGL pointer read callback reports one `PRESSED` and then `RELEASED`.
  - **Tick:** a 5 ms repeating timer calls `lv_tick_inc(5)`. This is the only
    tick source; don't add another.

### Fixes to the Waveshare-derived code

- The draw buffer is now allocated as `DISP_HOR_RES * DISP_VER_RES *
  sizeof(lv_color_t)`. It was previously missing the `sizeof`, so at 16-bit color
  it was half the size LVGL was told it had.
- `LCD_3in49.c` included `"LCD_3IN49.h"`, which only works on a case-insensitive
  file system such as macOS's default. It now matches the file name, so the
  project also builds on Linux.
- The duplicate `lv_tick_inc()` timer in `main.cpp` was removed. With both timers
  running, LVGL's clock ran at about 2× real time.

## Audio and SD card drivers

Drivers for the ES8311 audio codec and the micro SD card are taken from Waveshare's
`02-ES8311` and `03-FatFs` demos for this board. Both are built and linked into the
firmware. The audio is used for [music streamed from the Mac](#audio-streaming);
the SD card isn't used yet.

### Audio (ES8311)

- `lib/touch349/ES8311`: codec driver over I2C (address `0x18`). It shares the I2C1
  bus with the RTC and IMU.
- `lib/touch349/Audio_PIO`: I2S via PIO. `pico_audio` holds the sample rate
  (24 kHz), bit depth (16), volume and pins.
- `lib/touch349/Audio_Data`: test tones (440 Hz sine, "Happy Birthday").
- `tools/wav2data.py`: converts a 24 kHz, 16-bit mono WAV into a C array.

Minimal playback:

```c
es8311_init(pico_audio);   // also switches on the speaker amplifier (PA_CTRL)
es8311_sample_frequency_config(pico_audio.mclk_freq, pico_audio.sample_freq);
es8311_voice_volume_set(pico_audio.volume);
Sine_440hz_out();          // blocks forever
```

The Waveshare output functions (`Sine_440hz_out`, `Happy_birthday_out`,
`Loopback_test`) loop forever using blocking PIO writes. Run them on a core that
isn't driving LVGL, or feed samples with `pio_sm_put_blocking()` from your own loop.

Changes from Waveshare's code:

- Uses this project's `DEV_Config` (`DEV_I2C_Write_Byte` / `DEV_I2C_Read_Byte`)
  instead of the demo's own copy.
- `es8311_init()` now drives `PA_CTRL` (GPIO 0) high to enable the speaker
  amplifier. The demo did this in its own `DEV_Module_Init()`.
- `pico_audio` is defined once in `audio_pio.c`. It was previously a `static` in
  the header, which gave every file its own copy.
- `Music_out()` and its `music.h` song data (about 18 MB of source) were left out.
  Use `tools/wav2data.py` to generate your own.
- The `audio_pio.pio.h` header is generated at build time rather than checked in.
- The I2S output program (`audio_pio` in `audio_pio.pio`) now lines up with
  LRCLK's falling edge on every frame. Waveshare's did so once, at start-up, and
  on about a third of boots came out a few bits off, which played as loud noise
  instead of music until the next reboot. To make room for the wait, the right
  channel's last bit is no longer sent; the codec is mono and plays the left.
  The output FIFO is also 8 frames deep instead of 4.
- `tools/wav2data.py`: fixed an unterminated string that stopped the script from
  running.

### SD card (FatFs)

- `lib/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico`: Carl Kugler's FatFs + SD driver library,
  v3.3.1 (upstream commit `aca1922`), as shipped by Waveshare. Link the `sdcard`
  target (defined in `fatfs.cmake`) to use it.
- `port/fatfs/hw_config.c`: this board's card configuration. It is a single card in
  SPI mode, mounted as `"0:"`.

```c
FATFS fs;
FIL fil;
if (f_mount(&fs, "0:", 1) == FR_OK &&
    f_open(&fil, "0:/test.txt", FA_READ) == FR_OK) {
    /* f_read / f_gets ... */
    f_close(&fil);
}
```

Waveshare's changes to the upstream library:

- Their `hw_config.h` defines `SPI_SD0`, which selects SPI mode.
- Their `rp2040_sdio.pio` uses `wait gpio` instead of `wait pin`.
- They removed the upstream reference folders (`SdFat`, `ZuluSCSI-firmware`,
  `mbed-os`).
- They added an unused `rtc.c`/`rtc.h`.

Waveshare's `hw_config.c` declared four card slots on the same pins, one of them
SDIO with no PIO assigned. The board copy in `port/fatfs` keeps only the real SPI
slot. Waveshare's copy didn't include the library's Apache-2.0 `LICENSE`, so it was
restored from upstream.

## Pin and resource map

| Function | Pins | Peripheral |
|---|---|---|
| LCD (QSPI) | CS 25, SCLK 20, D0–D3 21–24, RST 34, PWR 37 | `pio0`, 1 DMA channel + `DMA_IRQ_0` |
| LCD backlight | 36 | PWM |
| Touch | SDA 32, SCL 33, INT 11 | `i2c0` |
| RTC, IMU, ES8311 | SDA 6, SCL 7 (IMU INT 8) | `i2c1` |
| Audio I2S | DOUT 1, DIN 2, MCLK 3, BCLK 4, LRCLK 5 | `pio1` SM1–2, `pio2` SM0 |
| Speaker amp enable | 0 (`PA_CTRL`) | GPIO |
| SD card (SPI) | SCK 26, MOSI 27, MISO 28, CS 31 | `spi1`, 2 DMA channels (no IRQ) |
| Power button / hold | 38 / 39 | GPIO |
| Battery | 40 | ADC 0 |

## Build notes

The build steps are in the [main README](../README.md#install). Notes for
working on the code:

- **Targets.** The top-level `CMakeLists.txt` includes `touch349.cmake` (board
  drivers, static library `touch349`), `lvgl.cmake` (static library `lvgl`) and
  `fatfs.cmake` (interface library `sdcard`), then `src/` (the executable). The
  project name is `LVGL`, so the outputs are `build/src/LVGL.uf2` and
  `build/src/LVGL.elf`. `ninja install` runs `picotool load` on the `.elf`.
- **Board header.** Waveshare's own `waveshare_rp2350_touch_lcd_3.49.h` uses
  `pico_board_cmake_set(PICO_PLATFORM, rp2350)`, a syntax added in Pico SDK 2.2.0.
  SDK 2.1.x doesn't define that macro, so the header fails to compile there. The
  copy in `boards/` uses the older comment form,
  `// pico_cmake_set PICO_PLATFORM=rp2350`, which SDK 2.1.x and 2.2.0+ both
  understand.
- **PIO headers.** `qspi.pio` and `audio_pio.pio` are assembled at build time by
  `pico_generate_pio_header`.
- **stdio.** USB stdio is on and UART stdio is off (`src/CMakeLists.txt`). The
  serial protocol shares that port with `printf`, so debug output that starts
  with `@` would be read by the host as a protocol line.
- **Flashing while it runs.** `picotool load -f -x build/src/LVGL.uf2` reboots
  the running board into BOOTSEL, flashes it and starts it again.
- **Trying the screen without Claude.** `python3 tools/claude_usage_host.py
  --demo` sends random numbers, and `--print` shows the lines without a board.

## Online sources

Board and chips:

- [Waveshare RP2350-Touch-LCD-3.49 wiki](https://www.waveshare.com/wiki/RP2350-Touch-LCD-3.49):
  Waveshare's documentation for the board, and where its demos (`02-ES8311`,
  `03-FatFs`, the LVGL demo) come from
- [Waveshare product page](https://www.waveshare.com/rp2350-touch-lcd-3.49.htm)
- [RP2350 datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)

SDK and tools:

- [Pico SDK](https://github.com/raspberrypi/pico-sdk) and the
  [C/C++ SDK book](https://datasheets.raspberrypi.com/pico/raspberry-pi-pico-c-sdk.pdf)
- [picotool](https://github.com/raspberrypi/picotool)
- [ARM GNU Toolchain downloads](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads)
- [TinyUSB](https://github.com/hathach/tinyusb), the USB stack inside the Pico SDK

Libraries:

- [LVGL 8.1 documentation](https://docs.lvgl.io/8.1/) and
  [source at v8.1.0](https://github.com/lvgl/lvgl/tree/v8.1.0)
- [no-OS-FatFS-SD-SDIO-SPI-RPi-Pico](https://github.com/carlk3/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico)
- [FatFs](http://elm-chan.org/fsw/ff/00index_e.html)

Claude:

- [Claude Code documentation](https://code.claude.com/docs/en/overview)
- [ccusage](https://github.com/ryoppippi/ccusage), whose way of grouping usage
  into 5-hour windows the local estimate follows
- The plan-limit endpoint, `api.anthropic.com/api/oauth/usage`, is unofficial
  and has no documentation. What the script expects from it is in
  `fetch_limits()`.

## Credits

This project builds on the work of [Dr Jon Durrant](https://github.com/jondurrant),
whose LVGL port and widget code for the Waveshare RP2350 Touch LCD 3.49 form the
foundation of this project.

His port is in turn adapted from the LVGL demo and hardware drivers supplied by
[Waveshare](https://www.waveshare.com) for the board: the LCD, touch, QSPI PIO and
device config code in `lib/touch349`, and the display/touch glue in
`port/lvgl/lv_port.c`.

The ES8311 audio code (`lib/touch349/ES8311`, `Audio_PIO`, `Audio_Data`,
`tools/wav2data.py`) and the SD card setup also come from Waveshare's demos for this
board.

The UI is built with [LVGL](https://lvgl.io) v8.1.0, vendored in `lib/lvgl`.

SD card support uses
[no-OS-FatFS-SD-SDIO-SPI-RPi-Pico](https://github.com/carlk3/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico)
by Carl John Kugler III (Apache-2.0, see its `LICENSE`), which is built on ChaN's
[FatFs](http://elm-chan.org/fsw/ff/00index_e.html).
