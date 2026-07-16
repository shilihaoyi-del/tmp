"""Minimal unit-style checks runnable without MQTT broker."""

from app.config import get_settings
from app.models.schemas import GestureEvent, HandSide
from app.services.gesture_mapper import map_gesture_to_joints
from app.services.safety import clamp_joints


def test_mapping():
    s = get_settings()
    joints = [0.0] * 6

    ev = GestureEvent(seq=1, ts_ms=0, gesture="Swipe Right", hand=HandSide.RIGHT, confidence=0.9)
    r = map_gesture_to_joints(ev, joints, s)
    assert r.applied and r.joints[0] == s.step_base

    ev = GestureEvent(seq=2, ts_ms=0, gesture="Swipe Up", hand=HandSide.RIGHT, confidence=0.9)
    r = map_gesture_to_joints(ev, r.joints, s)
    assert r.applied and r.joints[1] == s.step_shoulder

    ev = GestureEvent(seq=3, ts_ms=0, gesture="Swipe Up", hand=HandSide.LEFT, confidence=0.9)
    r = map_gesture_to_joints(ev, r.joints, s)
    assert r.applied and r.joints[2] == s.step_elbow

    ev = GestureEvent(
        seq=4,
        ts_ms=0,
        gesture="Swipe Up",
        hand=HandSide.BOTH,
        confidence=0.9,
        left_gesture="Swipe Up",
        right_gesture="Swipe Up",
        left_confidence=0.9,
        right_confidence=0.9,
    )
    r = map_gesture_to_joints(ev, r.joints, s)
    assert r.applied and "wrist_pitch" in r.reason

    ev = GestureEvent(seq=5, ts_ms=0, gesture="Swipe V", hand=HandSide.LEFT, confidence=0.9)
    r = map_gesture_to_joints(ev, r.joints, s)
    assert r.applied and r.joints[4] == s.step_wrist_roll

    ev = GestureEvent(seq=6, ts_ms=0, gesture="Pinch", hand=HandSide.RIGHT, confidence=0.9)
    r = map_gesture_to_joints(ev, r.joints, s)
    assert r.joints[5] == s.gripper_close

    ev = GestureEvent(seq=7, ts_ms=0, gesture="Expand", hand=HandSide.RIGHT, confidence=0.9)
    r = map_gesture_to_joints(ev, r.joints, s)
    assert r.joints[5] == s.gripper_open

    ev = GestureEvent(seq=8, ts_ms=0, gesture="Tap", hand=HandSide.RIGHT, confidence=0.9)
    r = map_gesture_to_joints(ev, r.joints, s)
    assert not r.applied

    clamped = clamp_joints([999.0, -999.0, 0, 0, 0, 200.0], s)
    assert clamped[0] == s.joint_max[0]
    assert clamped[1] == s.joint_min[1]
    assert clamped[5] == s.joint_max[5]
    print("OK: gesture mapping + clamp")


if __name__ == "__main__":
    test_mapping()
