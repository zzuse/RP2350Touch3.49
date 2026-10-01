/*
 * Pager.cpp
 */

#include "Pager.h"
#include "Theme.h"

#define DOT_SIZE    4
#define DOT_STEP    10

void Pager::init(int count)
{
    xCount = LV_MIN(count, PAGER_MAX);
    lv_obj_t *scr = lv_scr_act();
    lv_coord_t w = lv_disp_get_hor_res(NULL);
    lv_coord_t h = lv_disp_get_ver_res(NULL);

    for (int i = 0; i < xCount; i++) {
        lv_obj_t *p = lv_obj_create(scr);
        lv_obj_remove_style_all(p);
        lv_obj_set_size(p, w, h);
        lv_obj_set_pos(p, 0, 0);
        lv_obj_clear_flag(p, LV_OBJ_FLAG_SCROLLABLE);
        if (i != 0)
            lv_obj_add_flag(p, LV_OBJ_FLAG_HIDDEN);
        pPages[i] = p;
    }

    // Dots sit in the gap under the cards, on top of the pages
    lv_coord_t x0 = (w - (xCount - 1) * DOT_STEP - DOT_SIZE) / 2;
    for (int i = 0; i < xCount && xCount > 1; i++) {
        lv_obj_t *d = lv_obj_create(lv_layer_top());
        lv_obj_remove_style_all(d);
        lv_obj_set_size(d, DOT_SIZE, DOT_SIZE);
        lv_obj_set_pos(d, x0 + i * DOT_STEP, h - DOT_SIZE - 1);
        lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
        lv_obj_clear_flag(d, LV_OBJ_FLAG_CLICKABLE);
        pDots[i] = d;
    }
    updateDots();
}

void Pager::slide(int dir)
{
    if (xBusy || xCount < 2)
        return;
    int next = (xCur + (dir < 0 ? 1 : xCount - 1)) % xCount;
    lv_coord_t w = lv_disp_get_hor_res(NULL);
    lv_coord_t in = dir < 0 ? w : -w;   // where the new page starts

    lv_obj_t *out = pPages[xCur];
    lv_obj_t *nxt = pPages[next];
    lv_obj_set_x(nxt, in);
    lv_obj_clear_flag(nxt, LV_OBJ_FLAG_HIDDEN);

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_exec_cb(&a, animX);
    lv_anim_set_time(&a, PAGER_ANIM);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);

    lv_anim_set_var(&a, out);
    lv_anim_set_values(&a, 0, -in);
    lv_anim_start(&a);

    lv_anim_set_var(&a, nxt);
    lv_anim_set_values(&a, in, 0);
    lv_anim_set_user_data(&a, this);
    lv_anim_set_ready_cb(&a, animDone);
    lv_anim_start(&a);

    xBusy = true;
    xPrev = xCur;
    xCur = next;
    updateDots();
}

void Pager::animX(void *obj, int32_t x)
{
    lv_obj_set_x((lv_obj_t *)obj, (lv_coord_t)x);
}

void Pager::animDone(lv_anim_t *a)
{
    Pager *self = (Pager *)a->user_data;
    if (self->xPrev >= 0) {
        lv_obj_add_flag(self->pPages[self->xPrev], LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_x(self->pPages[self->xPrev], 0);
    }
    self->xPrev = -1;
    self->xBusy = false;
}

void Pager::updateDots()
{
    for (int i = 0; i < xCount; i++) {
        if (pDots[i])
            lv_obj_set_style_bg_color(pDots[i], i == xCur ? COL_ORANGE : COL_TRACK, 0);
    }
}
