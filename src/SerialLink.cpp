/*
 * SerialLink.cpp
 */

#include "SerialLink.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "pico/stdlib.h"
#include "lvgl.h"

static void copyStr(char *dst, size_t size, const char *src)
{
    strncpy(dst, src, size - 1);
    dst[size - 1] = '\0';
}

bool SerialLink::poll(UsageData &out)
{
    bool got = false;
    uint32_t now = to_ms_since_boot(get_absolute_time());

    // A chunk cut short (host stopped mid-write) must not swallow later lines
    if (xBinLeft && now - xLastRxMs > 1000)
        xBinLeft = 0;

    if (xAudio && xAudio->state() == AudioPlayer::DONE) {
        xAudio->stop();
        printf("@ADONE\n");
    }

    // Read in bulk: audio arrives at 48 KB/s, too fast for getchar()
    uint8_t rx[512];
    for (int reads = 0; reads < 64; reads++) {
        int n = stdio_get_until((char *)rx, sizeof(rx), get_absolute_time());
        if (n <= 0)
            break;
        xLastRxMs = now;
        int i = 0;
        while (i < n) {
            if (xBinLeft) {
                size_t take = LV_MIN((size_t)(n - i), xBinLeft);
                if (xAudio)
                    xAudio->write(rx + i, take);
                i += take;
                xBinLeft -= take;
                if (xBinLeft == 0)
                    printf("@AF %u\n", xAudio ? (unsigned)xAudio->freeBytes() : 0u);
                continue;
            }
            char ch = (char)rx[i++];
            if (ch == '\r')
                continue;
            if (ch == '\n') {
                xBuf[xLen] = '\0';
                if (!xOverflow && xLen > 0)
                    got |= handleLine(xBuf, out);
                xLen = 0;
                xOverflow = false;
                continue;
            }
            if (xLen < sizeof(xBuf) - 1)
                xBuf[xLen++] = ch;
            else
                xOverflow = true;
        }
    }
    return got;
}

void SerialLink::handleAudio(char *line)
{
    if (!xAudio)
        return;
    if (!strncmp(line, "@A ", 3)) {
        // Followed by that many bytes of raw PCM
        xBinLeft = strtoul(line + 3, nullptr, 10);
    } else if (!strcmp(line, "@AQ")) {
        printf("@AF %u\n", (unsigned)xAudio->freeBytes());
    } else if (!strncmp(line, "@PLAY", 5)) {
        // @PLAY dur=<seconds>;title=<text>
        char title[48] = "";
        uint32_t dur = 0;
        char *save = nullptr;
        char *args = line[5] == ' ' ? line + 6 : line + 5;
        for (char *tok = strtok_r(args, ";", &save); tok; tok = strtok_r(nullptr, ";", &save)) {
            if (!strncmp(tok, "dur=", 4))
                dur = strtoul(tok + 4, nullptr, 10);
            else if (!strncmp(tok, "title=", 6))
                copyStr(title, sizeof(title), tok + 6);
        }
        xAudio->start(title, dur);
        printf("@AOK %u\n", (unsigned)xAudio->freeBytes());
    } else if (!strcmp(line, "@AEND")) {
        xAudio->end();
    } else if (!strcmp(line, "@STOP")) {
        xAudio->stop();
    } else if (!strncmp(line, "@VOL ", 5)) {
        xAudio->setVolume(atoi(line + 5));
    }
}

bool SerialLink::handleLine(char *line, UsageData &out)
{
    if (strcmp(line, "@PING") == 0) {
        printf("@PONG claude-usage 1\n");
        return false;
    }
    if (!strncmp(line, "@A", 2) || !strncmp(line, "@PLAY", 5) ||
        !strcmp(line, "@STOP") || !strncmp(line, "@VOL ", 5)) {
        handleAudio(line);
        return false;
    }
    if (strncmp(line, "@CU ", 4) != 0)
        return false;

    UsageData d;
    char *save = nullptr;
    for (char *tok = strtok_r(line + 4, ";", &save); tok; tok = strtok_r(nullptr, ";", &save)) {
        char *eq = strchr(tok, '=');
        if (!eq)
            continue;
        *eq = '\0';
        parseField(tok, eq + 1, d);
    }
    out = d;
    printf("@OK\n");
    return true;
}

void SerialLink::parseField(char *key, char *val, UsageData &d)
{
    if (!strcmp(key, "sp"))       d.sessionPct = atoi(val);
    else if (!strcmp(key, "sr"))  d.sessionResetMin = atol(val);
    else if (!strcmp(key, "wp"))  d.weekPct = atoi(val);
    else if (!strcmp(key, "wr"))  d.weekResetMin = atol(val);
    else if (!strcmp(key, "w2p")) d.week2Pct = atoi(val);
    else if (!strcmp(key, "w2l")) copyStr(d.week2Label, sizeof(d.week2Label), val);
    else if (!strcmp(key, "tt"))  d.todayTokens = strtoull(val, nullptr, 10);
    else if (!strcmp(key, "tc"))  d.todayCostCents = strtoul(val, nullptr, 10);
    else if (!strcmp(key, "tm"))  d.todayMsgs = strtoul(val, nullptr, 10);
    else if (!strcmp(key, "bt"))  d.blockTokens = strtoull(val, nullptr, 10);
    else if (!strcmp(key, "br"))  d.burnPerMin = strtoul(val, nullptr, 10);
    else if (!strcmp(key, "m"))   copyStr(d.model, sizeof(d.model), val);
    else if (!strcmp(key, "t"))   copyStr(d.clock, sizeof(d.clock), val);
    else if (!strcmp(key, "src")) d.source = val[0];
    else if (!strcmp(key, "h")) {
        int i = 0;
        char *p = val;
        while (i < USAGE_HOURS && *p) {
            d.hourly[i++] = strtoul(p, &p, 10);
            if (*p == ',')
                p++;
            else
                break;
        }
    }
}
