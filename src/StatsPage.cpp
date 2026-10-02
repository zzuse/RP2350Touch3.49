/*
 * StatsPage.cpp
 */

#include "StatsPage.h"
#include "UiKit.h"
#include "Theme.h"

#include <cstdio>

#define CARD_A_X    UI_PAD
#define CARD_B_X    (UI_PAD + 176 + UI_PAD)
#define CARD_C_X    (CARD_B_X + 176 + UI_PAD)
#define SMALL_W     176

#define HEAT_CELL   13
#define HEAT_STEP   15
#define HEAT_W      (STATS_HEAT_WEEKS * HEAT_STEP - (HEAT_STEP - HEAT_CELL))
#define HEAT_H      (7 * HEAT_STEP - (HEAT_STEP - HEAT_CELL))
#define HEAT_TOP    30

void StatsPage::build(lv_obj_t *page)
{
    // Totals and best day
    lv_obj_t *card = uiCard(page, CARD_A_X, SMALL_W);
    lv_obj_t *l = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "TOTAL TOKENS");
    lv_obj_set_pos(l, 12, 8);
    pTotal = uiLabel(card, &lv_font_montserrat_28, COL_TEXT, "--");
    lv_obj_set_pos(pTotal, 12, 26);
    pSince = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "waiting for Mac");
    lv_obj_set_pos(pSince, 12, 60);

    l = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "BEST DAY");
    lv_obj_set_pos(l, 12, 88);
    pBest = uiLabel(card, &lv_font_montserrat_24, COL_ORANGE, "--");
    lv_obj_set_pos(pBest, 12, 106);
    pBestDay = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_set_pos(pBestDay, 12, 136);

    // Streaks and longest task
    card = uiCard(page, CARD_B_X, SMALL_W);
    l = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "STREAK");
    lv_obj_set_pos(l, 12, 8);
    pStreak = uiLabel(card, &lv_font_montserrat_28, COL_TEXT, "--");
    lv_obj_set_pos(pStreak, 12, 26);
    pStreakUnit = uiLabel(card, &lv_font_montserrat_16, COL_MUTED, "");
    pStreakBest = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_set_pos(pStreakBest, 12, 60);

    l = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "LONGEST TASK");
    lv_obj_set_pos(l, 12, 88);
    pTask = uiLabel(card, &lv_font_montserrat_24, COL_TEXT, "--");
    lv_obj_set_pos(pTask, 12, 106);
    pTaskDay = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_set_pos(pTaskDay, 12, 136);

    // Heatmap
    lv_coord_t w = UI_SCREEN_W - UI_PAD - CARD_C_X;
    card = uiCard(page, CARD_C_X, w);
    char buf[24];
    snprintf(buf, sizeof(buf), "LAST %d WEEKS", STATS_HEAT_WEEKS);
    l = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, buf);
    lv_obj_set_pos(l, 12, 8);
    pPeak = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_align(pPeak, LV_ALIGN_TOP_RIGHT, -12, 8);

    pHeat = lv_obj_create(card);
    lv_obj_remove_style_all(pHeat);
    lv_obj_set_size(pHeat, HEAT_W, HEAT_H);
    lv_obj_set_pos(pHeat, (w - HEAT_W) / 2, HEAT_TOP);
    lv_obj_clear_flag(pHeat, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(pHeat, heatDrawCB, LV_EVENT_DRAW_MAIN, this);

    // Legend, right-aligned under the grid: less ▪▪▪▪▪ more
    lv_coord_t right = (w + HEAT_W) / 2;
    lv_obj_t *more = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "more");
    lv_obj_update_layout(more);
    lv_coord_t x = right - lv_obj_get_width(more);
    lv_obj_set_pos(more, x, 138);
    x -= 6 + 5 * 13;
    for (int level = 0; level <= 4; level++) {
        lv_obj_t *sq = lv_obj_create(card);
        lv_obj_remove_style_all(sq);
        lv_obj_set_size(sq, 10, 10);
        lv_obj_set_pos(sq, x + level * 13, 142);
        lv_obj_set_style_radius(sq, 2, 0);
        lv_obj_set_style_bg_color(sq, heatColor(level), 0);
        lv_obj_set_style_bg_opa(sq, LV_OPA_COVER, 0);
    }
    lv_obj_t *less = uiLabel(card, &lv_font_montserrat_14, COL_MUTED, "less");
    lv_obj_update_layout(less);
    lv_obj_set_pos(less, x - 6 - lv_obj_get_width(less), 138);
}

lv_color_t StatsPage::heatColor(int level)
{
    static const uint8_t kMix[] = {0, 80, 140, 200, 255};
    if (level <= 0)
        return COL_TRACK;
    return lv_color_mix(COL_ORANGE, COL_TRACK, kMix[level > 4 ? 4 : level]);
}

void StatsPage::heatDrawCB(lv_event_t *e)
{
    StatsPage *self = (StatsPage *)lv_event_get_user_data(e);
    lv_obj_t *obj = lv_event_get_target(e);
    const lv_area_t *clip = (const lv_area_t *)lv_event_get_param(e);
    const StatsData &d = self->xData;

    lv_area_t box;
    lv_obj_get_coords(obj, &box);

    lv_draw_rect_dsc_t dsc;
    lv_draw_rect_dsc_init(&dsc);
    dsc.radius = 3;
    dsc.bg_opa = LV_OPA_COVER;

    // Right-align the data so today is always in the last column
    int n = self->xHaveData ? d.heatDays : 0;
    int firstCol = STATS_HEAT_WEEKS - (n + 6) / 7;

    for (int col = 0; col < STATS_HEAT_WEEKS; col++) {
        for (int row = 0; row < 7; row++) {
            int i = (col - firstCol) * 7 + row;   // day index in d.heat
            if (i >= n && col >= firstCol && n > 0)
                continue;                          // later this week
            int level = (i >= 0 && i < n) ? d.heat[i] : 0;
            lv_area_t a;
            a.x1 = box.x1 + col * HEAT_STEP;
            a.y1 = box.y1 + row * HEAT_STEP;
            a.x2 = a.x1 + HEAT_CELL - 1;
            a.y2 = a.y1 + HEAT_CELL - 1;
            dsc.bg_color = heatColor(level);
            // Outline today
            bool today = n > 0 && i == n - 1;
            dsc.border_width = today ? 1 : 0;
            dsc.border_color = COL_TEXT;
            dsc.border_opa = LV_OPA_COVER;
            lv_draw_rect(&a, clip, &dsc);
        }
    }
}

void StatsPage::apply(const StatsData &d)
{
    xData = d;
    xHaveData = true;

    char buf[32], tmp[16];
    int year = 0;   // stays 0 for a host that doesn't send td, so dates show their year
    sscanf(d.today, "%4d", &year);

    fmtTokens(buf, sizeof(buf), d.totalTokens);
    lv_label_set_text(pTotal, buf);
    fmtDay(tmp, sizeof(tmp), d.firstDay, year);
    snprintf(buf, sizeof(buf), d.firstDay[0] ? "since %s" : "no usage yet", tmp);
    lv_label_set_text(pSince, buf);

    if (d.bestTokens) {
        fmtTokens(buf, sizeof(buf), d.bestTokens);
        lv_label_set_text(pBest, buf);
        fmtDay(tmp, sizeof(tmp), d.bestDay, year);
        snprintf(buf, sizeof(buf), "on %s", tmp);
        lv_label_set_text(pBestDay, buf);
    } else {
        lv_label_set_text(pBest, "--");
        lv_label_set_text(pBestDay, "");
    }

    snprintf(buf, sizeof(buf), "%u", (unsigned)d.streak);
    lv_label_set_text(pStreak, buf);
    lv_label_set_text(pStreakUnit, d.streak == 1 ? "day" : "days");
    lv_obj_align_to(pStreakUnit, pStreak, LV_ALIGN_OUT_RIGHT_BOTTOM, 6, -4);
    snprintf(buf, sizeof(buf), "longest %u %s", (unsigned)d.longestStreak,
             d.longestStreak == 1 ? "day" : "days");
    lv_label_set_text(pStreakBest, buf);

    if (d.longestTaskMin > 0) {
        fmtDuration(buf, sizeof(buf), d.longestTaskMin);
        lv_label_set_text(pTask, buf);
        fmtDay(tmp, sizeof(tmp), d.longestTaskDay, year);
        snprintf(buf, sizeof(buf), "on %s", tmp);
        lv_label_set_text(pTaskDay, buf);
    } else {
        lv_label_set_text(pTask, "--");
        lv_label_set_text(pTaskDay, "");
    }

    if (d.heatMax) {
        fmtTokens(tmp, sizeof(tmp), d.heatMax);
        snprintf(buf, sizeof(buf), "top %s", tmp);
        lv_label_set_text(pPeak, buf);
    } else {
        lv_label_set_text(pPeak, "");
    }
    lv_obj_align(pPeak, LV_ALIGN_TOP_RIGHT, -12, 8);
    lv_obj_invalidate(pHeat);
}
