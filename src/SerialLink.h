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
 */

#ifndef SRC_SERIALLINK_H_
#define SRC_SERIALLINK_H_

#include "UsageData.h"
#include <cstddef>

class SerialLink {
public:
    // Reads whatever is waiting on stdin without blocking.
    // Returns true when a complete usage snapshot was received into out.
    bool poll(UsageData &out);

private:
    bool handleLine(char *line, UsageData &out);
    static void parseField(char *key, char *val, UsageData &out);

    char xBuf[512];
    size_t xLen = 0;
    bool xOverflow = false;
};

#endif /* SRC_SERIALLINK_H_ */
