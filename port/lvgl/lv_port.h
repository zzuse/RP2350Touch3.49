/*
 * lv_port.h
 *
 *  Created on: 6 Feb 2026
 *      Author: jondurrant
 */

#ifndef PORT_LVGL_LV_PORT_H_
#define PORT_LVGL_LV_PORT_H_

/* Native panel geometry (portrait) */
#define LCD_PHYS_W 172
#define LCD_PHYS_H 640

/* 1: LVGL sees a 640x172 landscape screen, rotated in the flush callback.
 * 0: LVGL sees the native 172x640 portrait screen. */
#ifndef DISP_LANDSCAPE
#define DISP_LANDSCAPE 1
#endif

/* Landscape rotation at boot, 90 or 270. With AUTO_ROTATE (src/AutoRotate.h)
 * the IMU changes it at run time; otherwise flip it if the picture is upside down. */
#ifndef DISP_ROTATION
#define DISP_ROTATION 90
#endif

#if DISP_LANDSCAPE
#define DISP_HOR_RES LCD_PHYS_H
#define DISP_VER_RES LCD_PHYS_W
#else
#define DISP_HOR_RES LCD_PHYS_W
#define DISP_VER_RES LCD_PHYS_H
#endif

#define INPUTDEV_TS  1

void LVGL_Init(void);

#if DISP_LANDSCAPE
/* Turn the landscape picture (and touch) to 90 or 270 degrees and redraw.
 * Call from the LVGL thread. */
void LVGL_SetRotation(int rotation);
int LVGL_GetRotation(void);
#endif

#endif /* PORT_LVGL_LV_PORT_H_ */
