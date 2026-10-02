/*
 * StatsPage.h
 *
 * Page 1: "Understand your Claude usage", from the @CS stats line.
 *
 *  +--------------+--------------+---------------------------+
 *  | TOTAL TOKENS | STREAK       | LAST 16 WEEKS     top 48M |
 *  |   1.24B      |   12 days    |  ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪         |
 *  | since Jun 3  | longest 31   |  ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪  7 rows  |
 *  | BEST DAY     | LONGEST TASK |  ...              Mon-Sun |
 *  |   48.20M     |   3h 42m     |                           |
 *  | on Sep 14    | on Sep 22    |        less ▪▪▪▪▪ more    |
 *  +--------------+--------------+---------------------------+
 */

#ifndef SRC_STATSPAGE_H_
#define SRC_STATSPAGE_H_

#include "lvgl.h"
#include "UsageData.h"

class StatsPage {
public:
    void build(lv_obj_t *page);
    void apply(const StatsData &d);

private:
    static void heatDrawCB(lv_event_t *e);
    static lv_color_t heatColor(int level);

    StatsData xData;
    bool xHaveData = false;

    lv_obj_t *pTotal;
    lv_obj_t *pSince;
    lv_obj_t *pBest;
    lv_obj_t *pBestDay;
    lv_obj_t *pStreak;
    lv_obj_t *pStreakUnit;
    lv_obj_t *pStreakBest;
    lv_obj_t *pTask;
    lv_obj_t *pTaskDay;
    lv_obj_t *pPeak;
    lv_obj_t *pHeat;      // drawn in heatDrawCB: one object instead of 112 keeps LVGL's heap small
};

#endif /* SRC_STATSPAGE_H_ */
