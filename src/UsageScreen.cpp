/*
 * UsageScreen.cpp
 */

#include "UsageScreen.h"
#include "Theme.h"

#include <cstdio>
#include <cstring>
#include "pico/stdlib.h"

extern "C" {
#include "DEV_Config.h"
}

#define SCREEN_H    172
#define PAD         6
#define CARD_H      (SCREEN_H - 2 * PAD)

#define CHART_X     16
#define CHART_TOP   32
#define CHART_H     78
#define BAR_W       14
#define BAR_STEP    18

#define STALE_MS    (120 * 1000)

static lv_color_t levelColor(int pct)
{
    if (pct < 0)  return COL_MUTED;
    if (pct < 60) return COL_GREEN;
    if (pct < 85) return COL_ORANGE;
    return COL_RED;
}

static void fmtTokens(char *buf, size_t n, uint64_t t)
{
    if (t < 1000ULL)                snprintf(buf, n, "%u", (unsigned)t);
    else if (t < 1000000ULL)        snprintf(buf, n, "%.1fk", t / 1e3);
    else if (t < 1000000000ULL)     snprintf(buf, n, "%.2fM", t / 1e6);
    else                            snprintf(buf, n, "%.2fB", t / 1e9);
}

static void fmtDuration(char *buf, size_t n, int32_t min)
{
    if (min < 0)            snprintf(buf, n, "--");
    else if (min >= 24 * 60) snprintf(buf, n, "%dd %dh", (int)(min / 1440), (int)((min % 1440) / 60));
    else if (min >= 60)     snprintf(buf, n, "%dh %02dm", (int)(min / 60), (int)(min % 60));
    else                    snprintf(buf, n, "%dm", (int)min);
}

/* ------------------------------------------------------------------------- */

void UsageScreen::init()
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, COL_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    xPager.init(2);
    buildSession();
    buildWeek();
    buildHistory();
    buildStats();

    apply();

    // All touches go to the screen, which sorts them into gestures and taps
    Gestures::passThrough(scr);
    xGestures.init();
    xLevels.init();

    // Frequent polling keeps up with streamed audio (48 KB/s)
    lv_timer_create(pollCB, 5, this);
    lv_timer_create(tickCB, 1000, this);
}

lv_obj_t *UsageScreen::makeCard(lv_obj_t *page, lv_coord_t x, lv_coord_t w)
{
    lv_obj_t *card = lv_obj_create(page);
    lv_obj_remove_style_all(card);
    lv_obj_set_pos(card, x, PAD);
    lv_obj_set_size(card, w, CARD_H);
    lv_obj_set_style_bg_color(card, COL_CARD, 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 14, 0);
    lv_obj_set_style_border_color(card, COL_BORDER, 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_CLICKABLE);
    return card;
}

lv_obj_t *UsageScreen::makeLabel(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

lv_obj_t *UsageScreen::makeBar(lv_obj_t *parent, lv_coord_t y)
{
    lv_obj_t *bar = lv_bar_create(parent);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, 176, 8);
    lv_obj_set_pos(bar, 12, y);
    lv_obj_set_style_bg_color(bar, COL_TRACK, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(bar, 4, LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, COL_GREEN, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 4, LV_PART_INDICATOR);
    lv_obj_set_style_anim_time(bar, 600, LV_PART_MAIN);
    lv_bar_set_range(bar, 0, 100);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_CLICKABLE);
    return bar;
}

void UsageScreen::buildSession()
{
    lv_obj_t *card = makeCard(xPager.page(0), PAD, 172);

    pArc = lv_arc_create(card);
    lv_obj_set_size(pArc, 128, 128);
    lv_obj_align(pArc, LV_ALIGN_TOP_MID, 0, 6);
    lv_arc_set_bg_angles(pArc, 135, 45);
    lv_arc_set_range(pArc, 0, 100);
    lv_arc_set_value(pArc, 0);
    lv_obj_remove_style(pArc, NULL, LV_PART_KNOB);
    lv_obj_clear_flag(pArc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_pad_all(pArc, 0, 0);
    lv_obj_set_style_arc_width(pArc, 12, LV_PART_MAIN);
    lv_obj_set_style_arc_color(pArc, COL_TRACK, LV_PART_MAIN);
    lv_obj_set_style_arc_width(pArc, 12, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(pArc, COL_ORANGE, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(pArc, true, LV_PART_INDICATOR);

    // Plain align (not align_to) so the labels stay centred when their text changes.
    // The arc's centre is at y = 6 + 64 = 70.
    pSessPct = makeLabel(card, &lv_font_montserrat_30, COL_TEXT, "--");
    lv_obj_align(pSessPct, LV_ALIGN_TOP_MID, 0, 48);

    pSessSub = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "5-HOUR");
    lv_obj_align(pSessSub, LV_ALIGN_TOP_MID, 0, 82);

    pSessReset = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "waiting for Mac");
    lv_obj_align(pSessReset, LV_ALIGN_BOTTOM_MID, 0, -8);
}

void UsageScreen::buildWeek()
{
    lv_obj_t *card = makeCard(xPager.page(0), PAD + 172 + PAD, 200);

    lv_obj_t *l = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "WEEKLY");
    lv_obj_set_pos(l, 12, 8);
    pWeekPct = makeLabel(card, &lv_font_montserrat_16, COL_TEXT, "--");
    lv_obj_align(pWeekPct, LV_ALIGN_TOP_RIGHT, -12, 7);
    pWeekBar = makeBar(card, 28);

    pW2Lbl = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "MODEL");
    lv_obj_set_pos(pW2Lbl, 12, 42);
    pW2Pct = makeLabel(card, &lv_font_montserrat_16, COL_TEXT, "--");
    lv_obj_align(pW2Pct, LV_ALIGN_TOP_RIGHT, -12, 41);
    pW2Bar = makeBar(card, 62);

    l = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "TODAY");
    lv_obj_set_pos(l, 12, 80);
    pTodayMsgs = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_align(pTodayMsgs, LV_ALIGN_TOP_RIGHT, -12, 80);

    pTodayCost = makeLabel(card, &lv_font_montserrat_28, COL_TEXT, "$0.00");
    lv_obj_set_pos(pTodayCost, 12, 98);
    pTodayTok = makeLabel(card, &lv_font_montserrat_16, COL_ORANGE, "0");
    lv_obj_align(pTodayTok, LV_ALIGN_TOP_RIGHT, -12, 106);

    pWeekReset = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_set_pos(pWeekReset, 12, 136);
}

void UsageScreen::buildHistory()
{
    lv_coord_t x = PAD + 172 + PAD + 200 + PAD;
    lv_obj_t *card = makeCard(xPager.page(0), x, 640 - x - PAD);

    lv_obj_t *l = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "LAST 12 HOURS");
    lv_obj_set_pos(l, 12, 8);

    pClock = makeLabel(card, &lv_font_montserrat_16, COL_TEXT, "--:--");
    lv_obj_align(pClock, LV_ALIGN_TOP_RIGHT, -12, 7);

    pDot = lv_obj_create(card);
    lv_obj_remove_style_all(pDot);
    lv_obj_set_size(pDot, 8, 8);
    lv_obj_set_style_radius(pDot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(pDot, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(pDot, COL_MUTED, 0);
    lv_obj_align_to(pDot, pClock, LV_ALIGN_OUT_LEFT_MID, -6, 0);

    // Baseline under the bars
    lv_obj_t *base = lv_obj_create(card);
    lv_obj_remove_style_all(base);
    lv_obj_set_size(base, (USAGE_HOURS - 1) * BAR_STEP + BAR_W, 1);
    lv_obj_set_pos(base, CHART_X, CHART_TOP + CHART_H + 1);
    lv_obj_set_style_bg_color(base, COL_BORDER, 0);
    lv_obj_set_style_bg_opa(base, LV_OPA_COVER, 0);

    for (int i = 0; i < USAGE_HOURS; i++) {
        lv_obj_t *b = lv_obj_create(card);
        lv_obj_remove_style_all(b);
        lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(b, i == USAGE_HOURS - 1 ? COL_ORANGE : COL_ODIM, 0);
        lv_obj_set_style_radius(b, 3, 0);
        lv_obj_set_size(b, BAR_W, 2);
        lv_obj_set_pos(b, CHART_X + i * BAR_STEP, CHART_TOP + CHART_H - 2);
        pBars[i] = b;
    }

    pPeak = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "-12h");
    lv_obj_set_pos(pPeak, CHART_X, CHART_TOP + CHART_H + 4);
    l = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "now");
    lv_obj_update_layout(l);
    lv_obj_set_pos(l, CHART_X + (USAGE_HOURS - 1) * BAR_STEP + BAR_W - lv_obj_get_width(l), CHART_TOP + CHART_H + 4);

    pModel = makeLabel(card, &lv_font_montserrat_14, COL_ORANGE, "");
    lv_obj_set_pos(pModel, 12, 136);
    lv_label_set_long_mode(pModel, LV_LABEL_LONG_DOT);
    lv_obj_set_width(pModel, 120);

    pBurn = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_align(pBurn, LV_ALIGN_TOP_RIGHT, -12, 136);

    // Now-playing row: hidden until audio streams. Tap it for the next track
    // (see onTap).
    pMusicRow = lv_obj_create(card);
    lv_obj_remove_style_all(pMusicRow);
    lv_obj_set_pos(pMusicRow, 0, 131);
    lv_obj_set_size(pMusicRow, 640 - x - PAD - 2, CARD_H - 131 - 2);
    lv_obj_clear_flag(pMusicRow, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(pMusicRow, LV_OBJ_FLAG_HIDDEN);

    pMusicBar = lv_bar_create(pMusicRow);
    lv_obj_remove_style_all(pMusicBar);
    lv_obj_set_pos(pMusicBar, 12, 0);
    lv_obj_set_size(pMusicBar, 640 - x - PAD - 26, 3);
    lv_obj_set_style_bg_color(pMusicBar, COL_TRACK, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(pMusicBar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_bg_color(pMusicBar, COL_ORANGE, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(pMusicBar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_bar_set_range(pMusicBar, 0, 1000);
    lv_obj_clear_flag(pMusicBar, LV_OBJ_FLAG_CLICKABLE);

    pMusicTitle = makeLabel(pMusicRow, &lv_font_montserrat_14, COL_ORANGE, "");
    lv_obj_set_pos(pMusicTitle, 12, 5);
    lv_label_set_long_mode(pMusicTitle, LV_LABEL_LONG_DOT);
    lv_obj_set_width(pMusicTitle, 140);

    pMusicTime = makeLabel(pMusicRow, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_align(pMusicTime, LV_ALIGN_TOP_RIGHT, -12, 5);
}

void UsageScreen::buildStats()
{
    // Placeholder until the stats page is built out
    lv_obj_t *card = makeCard(xPager.page(1), PAD, 640 - 2 * PAD);

    lv_obj_t *l = makeLabel(card, &lv_font_montserrat_14, COL_MUTED, "UNDERSTAND YOUR CLAUDE USAGE");
    lv_obj_set_pos(l, 16, 12);

    l = makeLabel(card, &lv_font_montserrat_16, COL_TEXT, "Usage stats are coming soon");
    lv_obj_align(l, LV_ALIGN_CENTER, 0, -8);
    l = makeLabel(card, &lv_font_montserrat_14, COL_MUTED,
                  "total tokens  " LV_SYMBOL_BULLET "  best day  " LV_SYMBOL_BULLET "  streaks  "
                  LV_SYMBOL_BULLET "  longest task  " LV_SYMBOL_BULLET "  daily heatmap");
    lv_obj_align(l, LV_ALIGN_CENTER, 0, 20);
}

void UsageScreen::refreshMusic()
{
    bool show = pAudio && pAudio->active();
    if (show != xShowingMusic) {
        xShowingMusic = show;
        if (show) {
            lv_obj_add_flag(pModel, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(pBurn, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_flag(pMusicRow, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(pModel, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_flag(pBurn, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(pMusicRow, LV_OBJ_FLAG_HIDDEN);
        }
    }
    if (!show)
        return;

    char buf[64];
    snprintf(buf, sizeof(buf), LV_SYMBOL_AUDIO " %s", pAudio->title());
    if (strcmp(lv_label_get_text(pMusicTitle), buf) != 0)
        lv_label_set_text(pMusicTitle, buf);

    uint32_t el = pAudio->elapsedSec();
    uint32_t dur = pAudio->durationSec();
    if (pAudio->state() == AudioPlayer::BUFFERING)
        snprintf(buf, sizeof(buf), "buffering");
    else if (dur)
        snprintf(buf, sizeof(buf), "%u:%02u / %u:%02u",
                 (unsigned)(el / 60), (unsigned)(el % 60), (unsigned)(dur / 60), (unsigned)(dur % 60));
    else
        snprintf(buf, sizeof(buf), "%u:%02u", (unsigned)(el / 60), (unsigned)(el % 60));
    if (strcmp(lv_label_get_text(pMusicTime), buf) != 0)
        lv_label_set_text(pMusicTime, buf);

    int32_t prog = dur ? (int32_t)LV_MIN(1000u, el * 1000 / dur) : 0;
    if (lv_bar_get_value(pMusicBar) != prog)
        lv_bar_set_value(pMusicBar, prog, LV_ANIM_OFF);
}

/* ------------------------------------------------------------------------- */

void UsageScreen::onEdgeBegin(Edge edge)
{
    xLevels.begin(edge == LEFT ? LevelControls::BRIGHTNESS : LevelControls::VOLUME);
}

void UsageScreen::onEdgeDrag(Edge edge, lv_coord_t dy)
{
    (void)edge;
    xLevels.drag(dy);
}

void UsageScreen::onEdgeEnd(Edge edge)
{
    (void)edge;
    xLevels.end();
}

void UsageScreen::onSwipe(int dir)
{
    xPager.slide(dir);
}

void UsageScreen::onTap(const lv_point_t &p)
{
    if (xShowingMusic && xPager.current() == 0) {
        lv_area_t a;
        lv_obj_get_coords(pMusicRow, &a);
        if (p.x >= a.x1 && p.x <= a.x2 && p.y >= a.y1 && p.y <= a.y2) {
            // The Mac owns the playlist; ask it for the next track
            printf("@ANEXT\n");
        }
    }
}

/* ------------------------------------------------------------------------- */

void UsageScreen::arcAnimCB(void *arc, int32_t v)
{
    lv_arc_set_value((lv_obj_t *)arc, (int16_t)v);
}

void UsageScreen::setBar(lv_obj_t *bar, lv_obj_t *label, int pct)
{
    char buf[16];
    if (pct < 0) {
        lv_label_set_text(label, "--");
        lv_bar_set_value(bar, 0, LV_ANIM_OFF);
    } else {
        snprintf(buf, sizeof(buf), "%d%%", pct);
        lv_label_set_text(label, buf);
        lv_bar_set_value(bar, LV_MIN(pct, 100), LV_ANIM_ON);
    }
    lv_obj_set_style_bg_color(bar, levelColor(pct), LV_PART_INDICATOR);
}

void UsageScreen::apply()
{
    char buf[32];
    const UsageData &d = xData;

    // Session arc
    int sp = xHaveData ? d.sessionPct : -1;
    if (sp >= 0) {
        snprintf(buf, sizeof(buf), "%d%%", sp);
        lv_label_set_text(pSessPct, buf);
    } else {
        lv_label_set_text(pSessPct, "--");
    }
    lv_label_set_text(pSessSub, d.source == 'o' || !xHaveData ? "5-HOUR" : "5-HOUR est.");
    lv_obj_set_style_arc_color(pArc, levelColor(sp), LV_PART_INDICATOR);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, pArc);
    lv_anim_set_exec_cb(&a, arcAnimCB);
    lv_anim_set_values(&a, lv_arc_get_value(pArc), LV_CLAMP(0, sp, 100));
    lv_anim_set_time(&a, 700);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_start(&a);

    // Weekly bars
    setBar(pWeekBar, pWeekPct, xHaveData ? d.weekPct : -1);
    if (d.week2Label[0]) {
        lv_label_set_text(pW2Lbl, d.week2Label);
        setBar(pW2Bar, pW2Pct, d.week2Pct);
    } else {
        // No per-model limit: show the current window's token count instead
        lv_label_set_text(pW2Lbl, "5H TOKENS");
        fmtTokens(buf, sizeof(buf), d.blockTokens);
        lv_label_set_text(pW2Pct, buf);
        lv_bar_set_value(pW2Bar, LV_CLAMP(0, sp, 100), LV_ANIM_ON);
        lv_obj_set_style_bg_color(pW2Bar, COL_BLUE, LV_PART_INDICATOR);
    }

    // Today
    snprintf(buf, sizeof(buf), "$%u.%02u", (unsigned)(d.todayCostCents / 100), (unsigned)(d.todayCostCents % 100));
    lv_label_set_text(pTodayCost, buf);
    fmtTokens(buf, sizeof(buf), d.todayTokens);
    strncat(buf, " tok", sizeof(buf) - strlen(buf) - 1);
    lv_label_set_text(pTodayTok, buf);
    snprintf(buf, sizeof(buf), "%u msgs", (unsigned)d.todayMsgs);
    lv_label_set_text(pTodayMsgs, buf);

    // History bars, scaled to the busiest hour
    uint32_t peak = 1;
    for (int i = 0; i < USAGE_HOURS; i++)
        peak = LV_MAX(peak, d.hourly[i]);
    for (int i = 0; i < USAGE_HOURS; i++) {
        lv_coord_t h = (lv_coord_t)((uint64_t)d.hourly[i] * CHART_H / peak);
        h = LV_MAX(h, 2);
        lv_obj_set_height(pBars[i], h);
        lv_obj_set_y(pBars[i], CHART_TOP + CHART_H - h);
    }
    if (xHaveData && peak > 1) {
        char tok[16];
        fmtTokens(tok, sizeof(tok), peak);
        snprintf(buf, sizeof(buf), "-12h  peak %s", tok);
        lv_label_set_text(pPeak, buf);
    } else {
        lv_label_set_text(pPeak, "-12h");
    }

    lv_label_set_text(pModel, d.model);
    if (xHaveData) {
        fmtTokens(buf, sizeof(buf), d.burnPerMin);
        strncat(buf, "/min", sizeof(buf) - strlen(buf) - 1);
        lv_label_set_text(pBurn, buf);
    } else {
        lv_label_set_text(pBurn, "");
    }

    refreshTimers();
}

void UsageScreen::refreshTimers()
{
    char buf[32], dur[16];
    uint32_t now = to_ms_since_boot(get_absolute_time());
    uint32_t age = now - xRxMs;
    int32_t elapsedMin = (int32_t)(age / 60000);

    if (!xHaveData) {
        lv_label_set_text(pSessReset, "waiting for Mac");
        lv_obj_set_style_bg_color(pDot, COL_MUTED, 0);
        return;
    }

    if (xData.status[0]) {
        // The Mac explains why the numbers are estimated or zero
        snprintf(buf, sizeof(buf), "%s", xData.status);
    } else if (xData.sessionResetMin >= 0) {
        fmtDuration(dur, sizeof(dur), LV_MAX(0, xData.sessionResetMin - elapsedMin));
        snprintf(buf, sizeof(buf), "resets in %s", dur);
    } else {
        snprintf(buf, sizeof(buf), "no active window");
    }
    lv_label_set_text(pSessReset, buf);
    lv_obj_set_style_text_color(pSessReset, xData.status[0] ? COL_AMBER : COL_MUTED, 0);

    if (xData.weekResetMin >= 0) {
        fmtDuration(dur, sizeof(dur), LV_MAX(0, xData.weekResetMin - elapsedMin));
        snprintf(buf, sizeof(buf), "week resets in %s", dur);
        lv_label_set_text(pWeekReset, buf);
    } else {
        lv_label_set_text(pWeekReset, "");
    }

    bool stale = age > STALE_MS;
    lv_obj_set_style_bg_color(pDot, stale ? COL_AMBER : COL_GREEN, 0);
    lv_label_set_text(pClock, xData.clock[0] ? xData.clock : "--:--");
    lv_obj_align_to(pDot, pClock, LV_ALIGN_OUT_LEFT_MID, -6, 0);
}

/* ------------------------------------------------------------------------- */

void UsageScreen::pollCB(lv_timer_t *timer)
{
    UsageScreen *self = (UsageScreen *)timer->user_data;
    if (self->xLink.poll(self->xData)) {
        self->xHaveData = true;
        self->xRxMs = to_ms_since_boot(get_absolute_time());
        self->apply();
    }
    // Catch a track starting or stopping straight away; the time updates once a second
    if (self->pAudio && self->pAudio->active() != self->xShowingMusic)
        self->refreshMusic();
}

void UsageScreen::tickCB(lv_timer_t *timer)
{
    UsageScreen *self = (UsageScreen *)timer->user_data;
    self->refreshTimers();
    self->refreshMusic();
}
