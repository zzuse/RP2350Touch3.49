# RP2350Touch3.49-Exp
Example Project

## Building

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

### 4. Configure and build

```sh
mkdir -p build && cd build
cmake -G Ninja ..
ninja
# or
cd build && cmake -G Ninja .. && ninja
```

### 5. Flash
Put the board in BOOTSEL mode first, then:
```sh
ninja install
# or
picotool load build/src/LVGL.uf2 -v
picotool reboot
```

The resulting firmware is at `build/src/LVGL.uf2` — copy it to the board while
it's in BOOTSEL mode to flash, or run `ninja install` to flash it via `picotool`
directly (board must be in BOOTSEL mode and `picotool` on `PATH`).

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
  display is 172×640 (portrait):
  - **Display:** one full-screen draw buffer with `full_refresh`. The flush
    callback sets the LCD window, sends `0x2C` (RAMWR) over QSPI and starts a DMA
    transfer into the PIO TX FIFO. The DMA IRQ deselects the chip and calls
    `lv_disp_flush_ready()`, so flushing is asynchronous.
  - **Touch:** a GPIO falling-edge IRQ reads the touch controller and latches
    x/y. The LVGL pointer read callback reports one `PRESSED` and then `RELEASED`.
  - **Tick:** a 5 ms repeating timer calls `lv_tick_inc(5)`. This is the only
    tick source; don't add another.

### Fixes to the Waveshare-derived code

- The draw buffer is now allocated as `DISP_HOR_RES * DISP_VER_RES *
  sizeof(lv_color_t)`. It was previously missing the `sizeof`, so at 16-bit color
  it was half the size LVGL was told it had.
- The duplicate `lv_tick_inc()` timer in `main.cpp` was removed. With both timers
  running, LVGL's clock ran at about 2× real time.

## Credits

This project builds on the work of [Dr Jon Durrant](https://github.com/jondurrant),
whose LVGL port and widget code for the Waveshare RP2350 Touch LCD 3.49 form the
foundation of this example.

His port is in turn adapted from the LVGL demo and hardware drivers supplied by
[Waveshare](https://www.waveshare.com) for the board: the LCD, touch, QSPI PIO and
device config code in `lib/touch349`, and the display/touch glue in
`port/lvgl/lv_port.c`.

The UI is built with [LVGL](https://lvgl.io) v8.1.0, vendored in `lib/lvgl`.

## License

Released under the [MIT License](LICENSE).
