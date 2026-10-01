/*
 * AutoRotate.h
 *
 * Uses the QMI8658 accelerometer to keep the landscape picture upright:
 * turn the board over (USB side up or down) and the screen flips 180 degrees.
 *
 * The UI is laid out for landscape only, so holding the board portrait, or
 * lying it flat, keeps whatever orientation it had.
 */

#ifndef SRC_AUTOROTATE_H_
#define SRC_AUTOROTATE_H_

#include "lvgl.h"

/* 0 disables auto-rotation; DISP_ROTATION in lv_port.h is then fixed. */
#ifndef AUTO_ROTATE
#define AUTO_ROTATE 1
#endif

/* Accelerometer axis that runs along the panel's short (172 px) side:
 * 0 = X, 1 = Y. If the screen never flips, or flips when you stand the
 * board up in portrait, it is the other one. Send "@IMU" over the serial
 * port to see the live readings. */
#ifndef IMU_SHORT_AXIS
#define IMU_SHORT_AXIS 0
#endif

/* Set to 1 if the picture ends up upside down in both orientations. */
#ifndef IMU_FLIP
#define IMU_FLIP 0
#endif

class AutoRotate {
public:
    void init();

    // Latest accelerometer reading, in the driver's units
    static void readAccel(float acc[3]);

private:
    static void timerCB(lv_timer_t *timer);
    int wanted();          // 90, 270, or 0 when the board isn't clearly landscape
    void check();

    int xCandidate = 0;
    int xCount = 0;
};

#endif /* SRC_AUTOROTATE_H_ */
