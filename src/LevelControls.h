/*
 * LevelControls.h
 *
 * Backlight brightness (left edge) and speaker volume (right edge), set by
 * dragging up or down. While dragging, a slim level meter shows on that edge,
 * then fades out.
 */

#ifndef SRC_LEVELCONTROLS_H_
#define SRC_LEVELCONTROLS_H_

#include "lvgl.h"
#include "AudioPlayer.h"

#define BRIGHTNESS_MIN      5     // never fully dark, so the screen can be found again
#define BRIGHTNESS_DEFAULT  60
#define LEVEL_PX_PER_10PCT  15    // drag distance for 10 %; the full 172 px height covers it all

class LevelControls {
public:
    enum Kind { BRIGHTNESS, VOLUME };

    explicit LevelControls(AudioPlayer *audio) : pAudio(audio) {}

    void init();

    // Drag handling: dy is the total travel since begin, positive upwards
    void begin(Kind kind);
    void drag(lv_coord_t dy);
    void end();

    int brightness() const { return xBright; }

private:
    struct Meter {
        lv_obj_t *box;
        lv_obj_t *bar;
        lv_obj_t *pct;
    };

    void buildMeter(Meter &m, lv_coord_t x, const char *icon);
    void set(Kind kind, int value);
    void show(Kind kind);

    AudioPlayer *pAudio;
    int xBright = BRIGHTNESS_DEFAULT;
    Kind xKind = BRIGHTNESS;
    int xStartValue = 0;
    Meter xMeters[2];
};

#endif /* SRC_LEVELCONTROLS_H_ */
