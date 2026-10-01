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

static void copyStr(char *dst, size_t size, const char *src)
{
    strncpy(dst, src, size - 1);
    dst[size - 1] = '\0';
}

bool SerialLink::poll(UsageData &out)
{
    bool got = false;
    for (;;) {
        int ch = getchar_timeout_us(0);
        if (ch == PICO_ERROR_TIMEOUT || ch < 0)
            break;
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
            xBuf[xLen++] = (char)ch;
        else
            xOverflow = true;
    }
    return got;
}

bool SerialLink::handleLine(char *line, UsageData &out)
{
    if (strcmp(line, "@PING") == 0) {
        printf("@PONG claude-usage 1\n");
        return false;
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
