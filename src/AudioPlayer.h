/*
 * AudioPlayer.h
 *
 * Plays 24 kHz, 16-bit mono PCM streamed from the Mac through the ES8311
 * codec and speaker.
 *
 * Core 0 (USB and LVGL) writes samples into a ring buffer as they arrive.
 * Core 1 reads them out to the I2S PIO; pio_sm_put_blocking() paces it at the
 * codec's sample rate. Every shared field has a single writer: core 0 owns the
 * write index and the stream mode, core 1 owns the read index and the
 * started/done flags. Emptying the buffer is a request that core 1 carries out.
 */

#ifndef SRC_AUDIOPLAYER_H_
#define SRC_AUDIOPLAYER_H_

#include <cstddef>
#include <cstdint>

#define AUDIO_RATE        24000
#define AUDIO_RING        32768                 // samples, 1.37 s
#define AUDIO_PREBUFFER   (AUDIO_RATE / 2)      // start after 0.5 s is buffered

class AudioPlayer {
public:
    enum State : uint8_t { IDLE, BUFFERING, PLAYING, DONE };

    // Core 0, once at boot: sets up the codec, MCLK and I2S output
    void init();

    // Core 0: stream control
    void start(const char *title, uint32_t durationSec);
    void write(const uint8_t *data, size_t len);   // little-endian int16 samples
    void end();                                    // no more data for this track
    void stop();
    void setVolume(int volume);                    // 0-100

    size_t freeBytes() const;
    State state() const;
    bool active() const { return xMode != M_IDLE; }

    // For the UI
    const char *title() const { return xTitle; }
    uint32_t durationSec() const { return xDuration; }
    uint32_t elapsedSec() const { return xPlayed / AUDIO_RATE; }
    uint32_t underruns() const { return xUnderruns; }

    // Core 1: outputs about 5 ms of audio (silence when idle) and returns.
    // Before init() it just sleeps for 5 ms.
    void pump5ms();

private:
    enum Mode : uint8_t { M_IDLE, M_STREAMING, M_ENDED };

    size_t fill() const;
    void flush();

    int16_t xRing[AUDIO_RING];

    // Written by core 0
    volatile uint32_t xHead = 0;
    volatile Mode xMode = M_IDLE;
    volatile bool xReady = false;
    volatile bool xFlushReq = false;   // cleared by core 1 once done

    // Written by core 1
    volatile uint32_t xTail = 0;
    volatile bool xStarted = false;    // prebuffer reached, samples flowing
    volatile bool xDone = false;       // ended and fully played
    volatile uint32_t xPlayed = 0;     // samples played this track
    volatile uint32_t xUnderruns = 0;

    // Core 0 only
    bool xHaveOdd = false;             // a sample split across two writes
    uint8_t xOdd = 0;
    char xTitle[48] = "";
    uint32_t xDuration = 0;
};

#endif /* SRC_AUDIOPLAYER_H_ */
