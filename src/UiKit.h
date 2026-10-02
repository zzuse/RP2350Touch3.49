/*
 * UiKit.h
 *
 * Building blocks and number formatting shared by the dashboard pages.
 */

#ifndef SRC_UIKIT_H_
#define SRC_UIKIT_H_

#include "lvgl.h"
#include <cstddef>
#include <cstdint>

#define UI_SCREEN_W 640
#define UI_SCREEN_H 172
#define UI_PAD      6
#define UI_CARD_H   (UI_SCREEN_H - 2 * UI_PAD)

// A rounded card on page, full height, at x with width w
lv_obj_t *uiCard(lv_obj_t *page, lv_coord_t x, lv_coord_t w);
lv_obj_t *uiLabel(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const char *text);

void fmtTokens(char *buf, size_t n, uint64_t t);       // 1.2k, 3.45M, 1.20B
void fmtDuration(char *buf, size_t n, int32_t min);    // 42m, 3h 05m, 2d 4h; "--" if < 0
// "2026-09-14" -> "Sep 14", or "Sep 14, 2026" when the year isn't thisYear
// (0 = unknown); "--" if empty or malformed
void fmtDay(char *buf, size_t n, const char *isoDate, int thisYear);

#endif /* SRC_UIKIT_H_ */
