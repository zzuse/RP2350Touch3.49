/*
 * SerialLink.h
 *
 * Reads usage updates from the Mac over the USB CDC serial port (stdio).
 *
 * Line protocol, one message per line:
 *   host -> board  "@PING"                    board answers "@PONG claude-usage 1"
 *   host -> board  "@CU key=value;key=value"  a usage snapshot, board answers "@OK"
 *
 * Keys: sp sr wp wr w2p w2l tt tc tm bt br h m t src (see UsageData.h and
 * tools/claude_usage_host.py). Unknown keys are ignored.
 *
 * Audio (24 kHz, 16-bit little-endian mono PCM), credit based: the host only
 * sends as many bytes as the board last reported free.
 *   host -> board  "@PLAY dur=<s>;title=<text>"  board answers "@AOK <free bytes>"
 *   host -> board  "@A <n>" + n raw bytes        board answers "@AF <free bytes>"
 *   host -> board  "@AQ"                         board answers "@AF <free bytes>"
 *   host -> board  "@AEND"                       board answers "@ADONE" once played out
 *   host -> board  "@STOP", "@VOL <0-100>"
 *   board -> host  "@ANEXT"                      the user tapped the now-playing row
 */

#ifndef SRC_SERIALLINK_H_
#define SRC_SERIALLINK_H_

#include "UsageData.h"
#include "AudioPlayer.h"
#include <cstddef>

class SerialLink {
public:
    explicit SerialLink(AudioPlayer *audio = nullptr) : xAudio(audio) {}

    // Reads whatever is waiting on stdin without blocking.
    // Returns true when a complete usage snapshot was received into out.
    bool poll(UsageData &out);

private:
    bool handleLine(char *line, UsageData &out);
    void handleAudio(char *line);
    static void parseField(char *key, char *val, UsageData &out);

    char xBuf[512];
    size_t xLen = 0;
    bool xOverflow = false;

    AudioPlayer *xAudio;
    size_t xBinLeft = 0;        // raw PCM bytes still to come for the current chunk
    uint32_t xLastRxMs = 0;
};

#endif /* SRC_SERIALLINK_H_ */
