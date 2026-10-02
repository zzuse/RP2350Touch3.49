/*
 * UsageData.h
 *
 * Claude usage snapshot, as sent by tools/claude_usage_host.py over USB serial.
 */

#ifndef SRC_USAGEDATA_H_
#define SRC_USAGEDATA_H_

#include <cstdint>

#define USAGE_HOURS 12

struct UsageData {
    // Plan limits, 0-100. -1 = unknown.
    int sessionPct = -1;          // current 5-hour window
    int32_t sessionResetMin = -1; // minutes until the 5-hour window resets
    int weekPct = -1;             // 7-day, all models
    int32_t weekResetMin = -1;
    int week2Pct = -1;            // 7-day, one model family (see week2Label)
    char week2Label[12] = "";

    // Totals from the local Claude Code logs
    uint64_t todayTokens = 0;
    uint32_t todayCostCents = 0;  // API-equivalent cost
    uint32_t todayMsgs = 0;
    uint64_t blockTokens = 0;     // tokens in the current 5-hour window
    uint32_t burnPerMin = 0;      // tokens per minute, recent

    uint32_t hourly[USAGE_HOURS] = {0}; // tokens per hour, oldest first
    char model[24] = "";
    char clock[8] = "";           // host local time, HH:MM
    char source = 'l';            // 'o' = limits from the Claude API, 'l' = local estimate
    char status[24] = "";         // why the numbers are estimated or zero, e.g. "limits: token expired"
};

// All-time stats for the stats page, sent as "@CS key=value;..." every few
// minutes (see history_stats() in tools/claude_usage_host.py)
#define STATS_HEAT_WEEKS 16
#define STATS_HEAT_DAYS  (STATS_HEAT_WEEKS * 7)

struct StatsData {
    uint64_t totalTokens = 0;     // tot
    char firstDay[11] = "";       // fd, YYYY-MM-DD: the first day the total covers
    char bestDay[11] = "";        // hd
    uint64_t bestTokens = 0;      // hdt
    uint32_t streak = 0;          // cs, days with usage up to today (or yesterday)
    uint32_t longestStreak = 0;   // ls
    int32_t longestTaskMin = -1;  // lt
    char longestTaskDay[11] = "";
    char today[11] = "";           // the Mac's date, to tell which dates are from an earlier year // ltd
    // hm: one level 0-4 per day, oldest first, starting on a Monday and
    // ending today, so day i is in week column i / 7, weekday row i % 7
    uint8_t heat[STATS_HEAT_DAYS] = {0};
    uint8_t heatDays = 0;
    uint64_t heatMax = 0;         // hmax, tokens that make level 4
};

#endif /* SRC_USAGEDATA_H_ */
