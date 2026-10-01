/*
 * LevelControls.cpp
 */

#include "LevelControls.h"
#include "Theme.h"

#include <cstdio>

extern "C" {
#include "DEV_Config.h"
}

#define METER_W     44
#define METER_H     140
#define METER_X     8
#define METER_Y     16
#define METER_FADE  300   // ms
#define METER_HOLD  900   // ms on screen after the finger lifts

void LevelControls::init()
{
    xBright = BRIGHTNESS_DEFAULT;
    DEV_SET_PWM(xBright);

    lv_coord_t w = lv_disp_get_hor_res(NULL);
    buildMeter(xMeters[BRIGHTNESS], METER_X, LV_SYMBOL_EYE_OPEN);
    buildMeter(xMeters[VOLUME], w - METER_X - METER_W, LV_SYMBOL_VOLUME_MAX);
}

void LevelControls::buildMeter(Meter &m, lv_coord_t x, const char *icon)
{
    // On the top layer, so it stays put while the pages slide
    m.box = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(m.box);
    lv_obj_set_pos(m.box, x, METER_Y);
    lv_obj_set_size(m.box, METER_W, METER_H);
    lv_obj_set_style_bg_color(m.box, COL_CARD, 0);
    lv_obj_set_style_bg_opa(m.box, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(m.box, 12, 0);
    lv_obj_set_style_border_color(m.box, COL_ORANGE, 0);
    lv_obj_set_style_border_width(m.box, 1, 0);
    lv_obj_clear_flag(m.box, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_clear_flag(m.box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(m.box, LV_OBJ_FLAG_HIDDEN);

    m.pct = lv_label_create(m.box);
    lv_obj_set_style_text_font(m.pct, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(m.pct, COL_TEXT, 0);
    lv_label_set_text(m.pct, "");
    lv_obj_align(m.pct, LV_ALIGN_TOP_MID, 0, 8);

    // Taller than wide, so LVGL draws it filling upwards
    m.bar = lv_bar_create(m.box);
    lv_obj_remove_style_all(m.bar);
    lv_obj_set_size(m.bar, 8, METER_H - 64);
    lv_obj_align(m.bar, LV_ALIGN_TOP_MID, 0, 30);
    lv_obj_set_style_bg_color(m.bar, COL_TRACK, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(m.bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(m.bar, 4, LV_PART_MAIN);
    lv_obj_set_style_bg_color(m.bar, COL_ORANGE, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(m.bar, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_radius(m.bar, 4, LV_PART_INDICATOR);
    lv_bar_set_range(m.bar, 0, 100);
    lv_obj_clear_flag(m.bar, LV_OBJ_FLAG_CLICKABLE);

    lv_obj_t *ic = lv_label_create(m.box);
    lv_obj_set_style_text_font(ic, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(ic, COL_MUTED, 0);
    lv_label_set_text(ic, icon);
    lv_obj_align(ic, LV_ALIGN_BOTTOM_MID, 0, -8);
}

void LevelControls::begin(Kind kind)
{
    xKind = kind;
    xStartValue = kind == BRIGHTNESS ? xBright : (pAudio ? pAudio->volume() : 0);
    show(kind);
}

void LevelControls::drag(lv_coord_t dy)
{
    set(xKind, xStartValue + dy * 10 / LEVEL_PX_PER_10PCT);
}

void LevelControls::end()
{
    lv_obj_fade_out(xMeters[xKind].box, METER_FADE, METER_HOLD);
}

void LevelControls::set(Kind kind, int value)
{
    if (kind == BRIGHTNESS) {
        value = LV_CLAMP(BRIGHTNESS_MIN, value, 100);
        if (value != xBright) {
            xBright = value;
            DEV_SET_PWM((uint8_t)value);
        }
    } else {
        if (!pAudio)
            return;
        pAudio->setVolume(LV_CLAMP(0, value, 100));
        value = pAudio->volume();
    }

    Meter &m = xMeters[kind];
    lv_bar_set_value(m.bar, value, LV_ANIM_OFF);
    char buf[8];
    snprintf(buf, sizeof(buf), "%d", value);
    lv_label_set_text(m.pct, buf);
}

void LevelControls::show(Kind kind)
{
    Meter &m = xMeters[kind];
    lv_anim_del(m.box, NULL);   // cancel a fade still running
    lv_obj_set_style_opa(m.box, LV_OPA_COVER, 0);
    lv_obj_clear_flag(m.box, LV_OBJ_FLAG_HIDDEN);
    set(kind, xStartValue);
}
