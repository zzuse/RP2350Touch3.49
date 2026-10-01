/*
 * AudioPlayer.cpp
 */

#include "AudioPlayer.h"

#include <cstring>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/sync.h"

extern "C" {
#include "DEV_Config.h"
#include "audio_pio.h"
#include "es8311.h"
}

#define PUMP_SAMPLES (AUDIO_RATE / 200)   // 5 ms

// The codec drives the I2S clocks. If it isn't running, a blocking put would
// hang core 1, and with it the power button, so give up after 20 ms.
static bool putFrame(uint32_t frame)
{
    absolute_time_t until = make_timeout_time_ms(20);
    while (pio_sm_is_tx_fifo_full(pico_audio.pio_2, pico_audio.sm_dout)) {
        if (time_reached(until))
            return false;
    }
    pio_sm_put(pico_audio.pio_2, pico_audio.sm_dout, frame);
    return true;
}

void AudioPlayer::init()
{
    es8311_init(pico_audio);
    es8311_sample_frequency_config(pico_audio.mclk_freq, pico_audio.sample_freq);
    xVolume = pico_audio.volume;
    es8311_voice_volume_set(xVolume);
    mclk_pio_init();
    dout_pio_init();

    // Keep the speaker amplifier off while nothing is playing, to avoid hiss
    es8311_voice_mute(true);
    DEV_Digital_Write(PA_CTRL, 0);

    __dmb();
    xReady = true;
}

size_t AudioPlayer::fill() const
{
    return (xHead - xTail) & (AUDIO_RING - 1);
}

size_t AudioPlayer::freeBytes() const
{
    if (xMode != M_STREAMING)
        return 0;
    // One slot stays empty so that head == tail always means "empty"
    return (AUDIO_RING - 1 - fill()) * sizeof(int16_t);
}

AudioPlayer::State AudioPlayer::state() const
{
    if (xMode == M_IDLE) return IDLE;
    if (xDone)           return DONE;
    if (xStarted)        return PLAYING;
    return BUFFERING;
}

void AudioPlayer::flush()
{
    xMode = M_IDLE;
    __dmb();
    xFlushReq = true;
    // Core 1 handles it at the start of its next 5 ms pump
    if (xReady) {
        while (xFlushReq)
            tight_loop_contents();
    } else {
        xTail = xHead;
        xFlushReq = false;
    }
    xHaveOdd = false;
}

void AudioPlayer::start(const char *title, uint32_t durationSec)
{
    flush();
    strncpy(xTitle, title ? title : "", sizeof(xTitle) - 1);
    xTitle[sizeof(xTitle) - 1] = '\0';
    xDuration = durationSec;

    DEV_Digital_Write(PA_CTRL, 1);
    es8311_voice_mute(false);
    __dmb();
    xMode = M_STREAMING;
}

void AudioPlayer::write(const uint8_t *data, size_t len)
{
    if (xMode != M_STREAMING)
        return;

    uint32_t head = xHead;
    uint32_t tail = xTail;
    auto push = [&](int16_t s) {
        uint32_t next = (head + 1) & (AUDIO_RING - 1);
        if (next == tail)
            return;             // full: the host overran its credit, drop
        xRing[head] = s;
        head = next;
    };

    size_t i = 0;
    if (xHaveOdd && len > 0) {
        push((int16_t)(xOdd | (data[0] << 8)));
        xHaveOdd = false;
        i = 1;
    }
    for (; i + 1 < len; i += 2)
        push((int16_t)(data[i] | (data[i + 1] << 8)));
    if (i < len) {
        xOdd = data[i];
        xHaveOdd = true;
    }

    __dmb();                    // samples are visible before the new head
    xHead = head;
}

void AudioPlayer::end()
{
    if (xMode == M_STREAMING)
        xMode = M_ENDED;
}

void AudioPlayer::stop()
{
    flush();
    es8311_voice_mute(true);
    DEV_Digital_Write(PA_CTRL, 0);
}

void AudioPlayer::setVolume(int volume)
{
    volume = volume < 0 ? 0 : volume > 100 ? 100 : volume;
    if (volume == xVolume)
        return;
    xVolume = volume;
    es8311_voice_volume_set(volume);
}

void AudioPlayer::pump5ms()
{
    if (!xReady) {
        sleep_ms(5);
        return;
    }

    if (xFlushReq) {
        xTail = xHead;
        xStarted = false;
        xDone = false;
        xPlayed = 0;
        xUnderruns = 0;
        __dmb();
        xFlushReq = false;
    }

    Mode mode = xMode;
    if (mode != M_IDLE && !xStarted && (fill() >= AUDIO_PREBUFFER || mode == M_ENDED))
        xStarted = true;

    bool reading = mode != M_IDLE && xStarted && !xDone;
    uint32_t tail = xTail;
    uint32_t played = 0, under = 0;

    for (int n = 0; n < PUMP_SAMPLES; n++) {
        int16_t s = 0;
        if (reading) {
            if (tail != xHead) {
                __dmb();
                s = xRing[tail];
                tail = (tail + 1) & (AUDIO_RING - 1);
                played++;
            } else if (mode == M_ENDED) {
                xDone = true;
                reading = false;
            } else {
                under++;
            }
        }
        // One 32-bit word per I2S frame: left in the high half, right in the
        // low half. The speaker is mono, so both get the same sample.
        uint32_t frame = ((uint32_t)(uint16_t)s << 16) | (uint16_t)s;
        if (!putFrame(frame))
            break;
    }

    // A flush requested during this pump runs at the next one, and core 0
    // waits for it before writing again, so publishing this tail is safe.
    __dmb();
    xTail = tail;
    xPlayed = xPlayed + played;
    xUnderruns = xUnderruns + under;
}
