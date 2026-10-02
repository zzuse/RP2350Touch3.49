/*
 * UiKit.cpp
 */

#include "UiKit.h"
#include "Theme.h"

#include <cstdio>
#include <cstdlib>

lv_obj_t *uiCard(lv_obj_t *page, lv_coord_t x, lv_coord_t w)
{
    lv_obj_t *card = lv_obj_create(page);
    lv_obj_remove_style_all(card);
    lv_obj_set_pos(card, x, UI_PAD);
    lv_obj_set_size(card, w, UI_CARD_H);
    lv_obj_set_style_bg_color(card, COL_CARD, 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 14, 0);
    lv_obj_set_style_border_color(card, COL_BORDER, 0);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_CLICKABLE);
    return card;
}

lv_obj_t *uiLabel(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_label_set_text(l, text);
    return l;
}

void fmtTokens(char *buf, size_t n, uint64_t t)
{
    if (t < 1000ULL)                snprintf(buf, n, "%u", (unsigned)t);
    else if (t < 1000000ULL)        snprintf(buf, n, "%.1fk", t / 1e3);
    else if (t < 1000000000ULL)     snprintf(buf, n, "%.2fM", t / 1e6);
    else                            snprintf(buf, n, "%.2fB", t / 1e9);
}

void fmtDuration(char *buf, size_t n, int32_t min)
{
    if (min < 0)            snprintf(buf, n, "--");
    else if (min >= 24 * 60) snprintf(buf, n, "%dd %dh", (int)(min / 1440), (int)((min % 1440) / 60));
    else if (min >= 60)     snprintf(buf, n, "%dh %02dm", (int)(min / 60), (int)(min % 60));
    else                    snprintf(buf, n, "%dm", (int)min);
}

void fmtDay(char *buf, size_t n, const char *isoDate, int thisYear)
{
    static const char *const kMonths[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
    // YYYY-MM-DD
    int year = 0, month = 0, day = 0;
    if (!isoDate || sscanf(isoDate, "%4d-%2d-%2d", &year, &month, &day) != 3 ||
        month < 1 || month > 12 || day < 1 || day > 31)
        snprintf(buf, n, "--");
    else if (year == thisYear)
        snprintf(buf, n, "%s %d", kMonths[month - 1], day);
    else
        snprintf(buf, n, "%s %d, %d", kMonths[month - 1], day, year);
}
