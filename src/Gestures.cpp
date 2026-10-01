/*
 * Gestures.cpp
 */

#include "Gestures.h"

#include <cstdlib>

void Gestures::init()
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_add_flag(scr, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(scr, eventCB, LV_EVENT_PRESSED, this);
    lv_obj_add_event_cb(scr, eventCB, LV_EVENT_PRESSING, this);
    lv_obj_add_event_cb(scr, eventCB, LV_EVENT_RELEASED, this);
    lv_obj_add_event_cb(scr, eventCB, LV_EVENT_PRESS_LOST, this);
}

void Gestures::passThrough(lv_obj_t *obj)
{
    lv_obj_clear_flag(obj, LV_OBJ_FLAG_CLICKABLE);
    uint32_t n = lv_obj_get_child_cnt(obj);
    for (uint32_t i = 0; i < n; i++)
        passThrough(lv_obj_get_child(obj, i));
}

void Gestures::eventCB(lv_event_t *e)
{
    Gestures *self = (Gestures *)lv_event_get_user_data(e);
    lv_indev_t *indev = lv_indev_get_act();
    if (!indev)
        return;
    lv_point_t p;
    lv_indev_get_point(indev, &p);

    switch (lv_event_get_code(e)) {
    case LV_EVENT_PRESSED:    self->pressed(p);  break;
    case LV_EVENT_PRESSING:   self->pressing(p); break;
    case LV_EVENT_RELEASED:
    case LV_EVENT_PRESS_LOST: self->released(self->xLast); break;
    default: break;
    }
}

void Gestures::pressed(const lv_point_t &p)
{
    lv_coord_t w = lv_disp_get_hor_res(NULL);
    if (p.x < GESTURE_EDGE_W)
        xZone = Z_LEFT;
    else if (p.x >= w - GESTURE_EDGE_W)
        xZone = Z_RIGHT;
    else
        xZone = Z_CENTRE;
    xStart = xLast = p;
    xDragging = false;
    xMoved = false;
}

void Gestures::pressing(const lv_point_t &p)
{
    if (xZone == Z_NONE)
        return;
    xLast = p;
    lv_coord_t dx = p.x - xStart.x;
    lv_coord_t dy = p.y - xStart.y;
    if (abs(dx) > GESTURE_DEAD_ZONE || abs(dy) > GESTURE_DEAD_ZONE)
        xMoved = true;

    if (xZone == Z_CENTRE)
        return;   // swipes are decided on release

    GestureListener::Edge edge = xZone == Z_LEFT ? GestureListener::LEFT : GestureListener::RIGHT;
    if (!xDragging) {
        if (abs(dy) <= GESTURE_DEAD_ZONE)
            return;
        xDragging = true;
        // Start counting from here so the value doesn't jump by the dead zone
        xStart.y = p.y;
        pListener->onEdgeBegin(edge);
        return;
    }
    pListener->onEdgeDrag(edge, xStart.y - p.y);
}

void Gestures::released(const lv_point_t &p)
{
    Zone zone = xZone;
    xZone = Z_NONE;
    if (zone == Z_NONE)
        return;

    if (xDragging) {
        pListener->onEdgeEnd(zone == Z_LEFT ? GestureListener::LEFT : GestureListener::RIGHT);
        return;
    }
    if (!xMoved) {
        pListener->onTap(xStart);
        return;
    }
    lv_coord_t dx = p.x - xStart.x;
    lv_coord_t dy = p.y - xStart.y;
    if (zone == Z_CENTRE && abs(dx) >= GESTURE_SWIPE_MIN && abs(dx) > 2 * abs(dy))
        pListener->onSwipe(dx < 0 ? -1 : 1);
}
