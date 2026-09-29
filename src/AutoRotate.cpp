/*
 * AutoRotate.cpp
 */

#include "AutoRotate.h"

#include <cmath>
#include <cstdio>

extern "C" {
#include "lv_port.h"
#include "QMI8658.h"
}

#define SAMPLE_MS      100
#define STABLE_SAMPLES 6      // orientation must hold for 600 ms before flipping

void AutoRotate::readAccel(float acc[3])
{
    float gyro[3];
    QMI8658_read_xyz(acc, gyro, NULL);
}

void AutoRotate::init()
{
#if AUTO_ROTATE && DISP_LANDSCAPE
    // Start in the right orientation instead of flipping a moment after boot
    int w = wanted();
    if (w)
        LVGL_SetRotation(w);
    lv_timer_create(timerCB, SAMPLE_MS, this);
#endif
}

int AutoRotate::wanted()
{
    float a[3];
    readAccel(a);

    float g = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
    if (g <= 0.0f)
        return 0;

    // Units depend on how the driver is built (m/s^2 or mg), so only
    // compare the axes with each other and with the total.
    float shortAxis = a[IMU_SHORT_AXIS];
    float longAxis = a[1 - IMU_SHORT_AXIS];
    if (IMU_FLIP)
        shortAxis = -shortAxis;

    // Gravity must lie mostly along the short side: board standing in
    // landscape, not flat on the desk and not in portrait.
    if (fabsf(shortAxis) < 0.6f * g || fabsf(shortAxis) < 2.0f * fabsf(longAxis))
        return 0;
    return shortAxis > 0 ? 90 : 270;
}

void AutoRotate::check()
{
#if DISP_LANDSCAPE
    int w = wanted();
    if (w == 0 || w == LVGL_GetRotation()) {
        xCount = 0;
        return;
    }
    if (w != xCandidate) {
        xCandidate = w;
        xCount = 0;
    }
    if (++xCount >= STABLE_SAMPLES) {
        xCount = 0;
        LVGL_SetRotation(w);
        printf("@ROT %d\n", w);
    }
#endif
}

void AutoRotate::timerCB(lv_timer_t *timer)
{
    ((AutoRotate *)timer->user_data)->check();
}
