/*
 * Pager.h
 *
 * Full-screen pages side by side; a swipe slides the next one in. Small dots
 * along the bottom edge show which page is up. Wraps around at either end.
 */

#ifndef SRC_PAGER_H_
#define SRC_PAGER_H_

#include "lvgl.h"

#define PAGER_MAX   4
#define PAGER_ANIM  250   // ms

class Pager {
public:
    // Creates count empty pages on the active screen; page 0 shows first
    void init(int count);

    lv_obj_t *page(int i) const { return pPages[i]; }
    int current() const { return xCur; }

    // dir -1: finger moved left, so the next page comes in from the right.
    // dir +1: the previous page comes in from the left.
    void slide(int dir);

private:
    static void animX(void *obj, int32_t x);
    static void animDone(lv_anim_t *a);
    void updateDots();

    lv_obj_t *pPages[PAGER_MAX] = {};
    lv_obj_t *pDots[PAGER_MAX] = {};
    int xCount = 0;
    int xCur = 0;
    int xPrev = -1;           // page sliding out, hidden once the animation ends
    bool xBusy = false;
};

#endif /* SRC_PAGER_H_ */
