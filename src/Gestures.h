/*
 * Gestures.h
 *
 * Turns touches on the screen into the dashboard's gestures:
 *
 *  +-------+------------------------------+-------+
 *  | drag  |      swipe left / right      | drag  |
 *  | up /  |        (change page)         | up /  |
 *  | down  |                              | down  |
 *  | LEFT  |           CENTRE             | RIGHT |
 *  +-------+------------------------------+-------+
 *
 * Coordinates are LVGL's, already rotated, so "left" is always left as you
 * look at the screen, whichever way up the board is.
 *
 * Every other object is made non-clickable, so the screen sees every touch;
 * a tap is passed on with its point and the listener decides what was hit.
 */

#ifndef SRC_GESTURES_H_
#define SRC_GESTURES_H_

#include "lvgl.h"

#define GESTURE_EDGE_W      110   // width of the left and right drag zones
#define GESTURE_DEAD_ZONE   8     // movement that still counts as a tap
#define GESTURE_SWIPE_MIN   60    // horizontal travel for a page swipe

class GestureListener {
public:
    enum Edge { LEFT, RIGHT };

    // A vertical drag on an edge zone. dy is the total travel since the
    // drag began, in pixels, positive upwards.
    virtual void onEdgeBegin(Edge edge) = 0;
    virtual void onEdgeDrag(Edge edge, lv_coord_t dy) = 0;
    virtual void onEdgeEnd(Edge edge) = 0;

    // A horizontal swipe in the centre: dir is -1 for a swipe to the left
    // (finger moving left), +1 to the right.
    virtual void onSwipe(int dir) = 0;

    virtual void onTap(const lv_point_t &p) = 0;

protected:
    ~GestureListener() = default;
};

class Gestures {
public:
    explicit Gestures(GestureListener *listener) : pListener(listener) {}

    // Attaches to the active screen
    void init();

    // Clears LV_OBJ_FLAG_CLICKABLE on obj and everything inside it, so its
    // touches reach the screen
    static void passThrough(lv_obj_t *obj);

private:
    enum Zone { Z_NONE, Z_LEFT, Z_RIGHT, Z_CENTRE };

    static void eventCB(lv_event_t *e);
    void pressed(const lv_point_t &p);
    void pressing(const lv_point_t &p);
    void released(const lv_point_t &p);

    GestureListener *pListener;
    Zone xZone = Z_NONE;
    lv_point_t xStart = {0, 0};
    lv_point_t xLast = {0, 0};
    bool xDragging = false;   // edge drag past the dead zone
    bool xMoved = false;      // moved past the dead zone at all
};

#endif /* SRC_GESTURES_H_ */
