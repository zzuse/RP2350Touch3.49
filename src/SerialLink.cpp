/*
 * SerialLink.cpp
 */

#include "SerialLink.h"
#include "AutoRotate.h"

extern "C" {
#include "lv_port.h"
}

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

int SerialLink::poll(UsageData &usage, StatsData &stats)
{
    int got = 0;
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
                    got |= handleLine(xBuf, usage, stats);
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

int SerialLink::handleLine(char *line, UsageData &out, StatsData &stats)
{
    if (strcmp(line, "@PING") == 0) {
        printf("@PONG claude-usage 1\n");
        return 0;
    }
    if (strcmp(line, "@IMU") == 0) {
        // For setting IMU_SHORT_AXIS / IMU_FLIP in AutoRotate.h
        float a[3];
        AutoRotate::readAccel(a);
#if DISP_LANDSCAPE
        int rot = LVGL_GetRotation();
#else
        int rot = 0;
#endif
        printf("@IMU x=%.2f y=%.2f z=%.2f rot=%d\n", a[0], a[1], a[2], rot);
        return 0;
    }
    if (!strncmp(line, "@A", 2) || !strncmp(line, "@PLAY", 5) ||
        !strcmp(line, "@STOP") || !strncmp(line, "@VOL ", 5)) {
        handleAudio(line);
        return 0;
    }
    if (!strncmp(line, "@CS ", 4)) {
        StatsData d;
        char *save = nullptr;
        for (char *tok = strtok_r(line + 4, ";", &save); tok; tok = strtok_r(nullptr, ";", &save)) {
            char *eq = strchr(tok, '=');
            if (!eq)
                continue;
            *eq = '\0';
            parseStat(tok, eq + 1, d);
        }
        stats = d;
        printf("@OK\n");
        return GOT_STATS;
    }
    if (strncmp(line, "@CU ", 4) != 0)
        return 0;

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
    return GOT_USAGE;
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
    else if (!strcmp(key, "st"))  copyStr(d.status, sizeof(d.status), val);
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

void SerialLink::parseStat(char *key, char *val, StatsData &d)
{
    if (!strcmp(key, "tot"))       d.totalTokens = strtoull(val, nullptr, 10);
    else if (!strcmp(key, "fd"))   copyStr(d.firstDay, sizeof(d.firstDay), val);
    else if (!strcmp(key, "hd"))   copyStr(d.bestDay, sizeof(d.bestDay), val);
    else if (!strcmp(key, "hdt"))  d.bestTokens = strtoull(val, nullptr, 10);
    else if (!strcmp(key, "cs"))   d.streak = strtoul(val, nullptr, 10);
    else if (!strcmp(key, "ls"))   d.longestStreak = strtoul(val, nullptr, 10);
    else if (!strcmp(key, "lt"))   d.longestTaskMin = atol(val);
    else if (!strcmp(key, "ltd"))  copyStr(d.longestTaskDay, sizeof(d.longestTaskDay), val);
    else if (!strcmp(key, "hmax")) d.heatMax = strtoull(val, nullptr, 10);
    else if (!strcmp(key, "td"))   copyStr(d.today, sizeof(d.today), val);
    else if (!strcmp(key, "hm")) {
        // Keep the most recent weeks if there are more than fit, dropping
        // whole weeks so day 0 is still a Monday
        size_t n = strlen(val);
        size_t skip = n > STATS_HEAT_DAYS ? (n - STATS_HEAT_DAYS + 6) / 7 * 7 : 0;
        size_t count = n - skip;
        for (size_t i = 0; i < count; i++) {
            char c = val[skip + i];
            d.heat[i] = (c >= '0' && c <= '4') ? (uint8_t)(c - '0') : 0;
        }
        d.heatDays = (uint8_t)count;
    }
}
