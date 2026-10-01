/*
 * UsageScreen.h
 *
 * Landscape (640x172) Claude usage dashboard.
 *
 *  +----------+--------------+------------------+
 *  |  (arc)   | WEEKLY  ===  | LAST 12 HOURS    |
 *  |   42%    | SONNET  ===  |  ▁▂▅▇▃▁▁▂▆█▅▃    |
 *  |  5-HOUR  | TODAY $12.34 | model   burn/min |
 *  +----------+--------------+------------------+
 */

#ifndef SRC_USAGESCREEN_H_
#define SRC_USAGESCREEN_H_

#include "lvgl.h"
#include "UsageData.h"
#include "SerialLink.h"
#include "AudioPlayer.h"

class UsageScreen {
public:
    explicit UsageScreen(AudioPlayer *audio = nullptr) : xLink(audio), pAudio(audio) {}

    void init();

private:
    static void pollCB(lv_timer_t *timer);
    static void tickCB(lv_timer_t *timer);
    static void clickCB(lv_event_t *e);
    static void arcAnimCB(void *arc, int32_t v);
    static void musicClickCB(lv_event_t *e);

    lv_obj_t *makeCard(lv_coord_t x, lv_coord_t w);
    lv_obj_t *makeLabel(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text);
    lv_obj_t *makeBar(lv_obj_t *parent, lv_coord_t y);

    void buildSession();
    void buildWeek();
    void buildHistory();

    void apply();          // redraw everything from xData
    void refreshTimers();  // countdowns and the link indicator
    void setBar(lv_obj_t *bar, lv_obj_t *label, int pct);
    void refreshMusic();   // now-playing row, in place of model / burn rate

    UsageData xData;
    SerialLink xLink;
    bool xHaveData = false;
    uint32_t xRxMs = 0;
    int xBrightIdx = 2;

    // Session card
    lv_obj_t *pArc;
    lv_obj_t *pSessPct;
    lv_obj_t *pSessSub;
    lv_obj_t *pSessReset;

    // Week / today card
    lv_obj_t *pWeekPct;
    lv_obj_t *pWeekBar;
    lv_obj_t *pW2Lbl;
    lv_obj_t *pW2Pct;
    lv_obj_t *pW2Bar;
    lv_obj_t *pTodayCost;
    lv_obj_t *pTodayTok;
    lv_obj_t *pTodayMsgs;
    lv_obj_t *pWeekReset;

    // History card
    lv_obj_t *pDot;
    lv_obj_t *pClock;
    lv_obj_t *pBars[USAGE_HOURS];
    lv_obj_t *pPeak;
    lv_obj_t *pModel;
    lv_obj_t *pBurn;

    // Now playing
    AudioPlayer *pAudio;
    bool xShowingMusic = false;
    lv_obj_t *pMusicRow;
    lv_obj_t *pMusicBar;
    lv_obj_t *pMusicTitle;
    lv_obj_t *pMusicTime;
};

#endif /* SRC_USAGESCREEN_H_ */
