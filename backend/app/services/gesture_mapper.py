"""Map SHREC-14 gestures to Cartesian / orientation pose deltas (+ gripper).

Handled gestures:
  Swipe Right / Left              -> ±Y
  Swipe Up / Down (Right hand)   -> ±Z
  Swipe Up / Down (Left hand)    -> ±X
  Swipe Up / Down (both hands)   -> wrist pitch (pose pitch)
  Swipe V (Left)                 -> roll
  Pinch / Grab                   -> gripper close
  Expand                         -> gripper open

SC171 runs IK on pose_delta; joint deltas are no longer the primary path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import Settings
from app.models.schemas import GestureEvent, HandSide


HANDLED = {
    "Swipe Right",
    "Swipe Left",
    "Swipe Up",
    "Swipe Down",
    "Swipe V",
    "Pinch",
    "Grab",
    "Expand",
}

CONF_THRESHOLD = 0.35

# Default Cartesian / orientation steps (meters, radians)
STEP_XY = 0.02
STEP_Z = 0.02
STEP_PITCH = 0.08
STEP_ROLL = 0.10


@dataclass
class MapResult:
    joints: list[float]
    applied: bool
    reason: str
    pose_delta: Optional[dict] = None
    gripper: Optional[float] = None


def _empty_delta() -> dict:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}


def _is_swipe_vertical(name: str) -> bool:
    return name in ("Swipe Up", "Swipe Down")


def map_gesture_to_joints(
    event: GestureEvent,
    current: list[float],
    settings: Settings,
) -> MapResult:
    """Apply one gesture event. Prefer pose_delta; joints kept for UI mirror."""
    joints = list(current)
    if len(joints) != 6:
        joints = [0.0] * 6

    left_g = event.left_gesture or (event.gesture if event.hand == HandSide.LEFT else None)
    right_g = event.right_gesture or (event.gesture if event.hand == HandSide.RIGHT else None)
    left_c = event.left_confidence if event.left_gesture is not None else (
        event.confidence if event.hand == HandSide.LEFT else 0.0
    )
    right_c = event.right_confidence if event.right_gesture is not None else (
        event.confidence if event.hand == HandSide.RIGHT else 0.0
    )

    if event.hand == HandSide.BOTH or (left_g and right_g):
        return _map_dual(left_g, right_g, left_c, right_c, joints, settings)

    gesture = event.gesture
    conf = event.confidence
    hand = event.hand

    if gesture not in HANDLED:
        return MapResult(joints, False, f"ignored:{gesture}")
    if conf < CONF_THRESHOLD:
        return MapResult(joints, False, "low_confidence")

    return _apply_single(gesture, hand, joints, settings)


def _map_dual(
    left_g: str | None,
    right_g: str | None,
    left_c: float,
    right_c: float,
    joints: list[float],
    settings: Settings,
) -> MapResult:
    if (
        left_g
        and right_g
        and _is_swipe_vertical(left_g)
        and _is_swipe_vertical(right_g)
        and left_c >= CONF_THRESHOLD
        and right_c >= CONF_THRESHOLD
    ):
        direction = right_g
        d = _empty_delta()
        d["pitch"] = STEP_PITCH if direction == "Swipe Up" else -STEP_PITCH
        return MapResult(joints, True, "pitch:both", pose_delta=d)

    applied = False
    reasons: list[str] = []
    merged = _empty_delta()
    gripper: Optional[float] = None

    if right_g and right_c >= CONF_THRESHOLD and right_g in HANDLED:
        r = _apply_single(right_g, HandSide.RIGHT, joints, settings)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)
            if r.pose_delta:
                for k in merged:
                    merged[k] += float(r.pose_delta.get(k, 0.0))
            if r.gripper is not None:
                gripper = r.gripper

    if left_g and left_c >= CONF_THRESHOLD and left_g in HANDLED:
        r = _apply_single(left_g, HandSide.LEFT, joints, settings)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)
            if r.pose_delta:
                for k in merged:
                    merged[k] += float(r.pose_delta.get(k, 0.0))
            if r.gripper is not None:
                gripper = r.gripper

    pose_delta = merged if any(abs(v) > 1e-12 for v in merged.values()) else None
    return MapResult(
        joints,
        applied,
        ",".join(reasons) if reasons else "no_action",
        pose_delta=pose_delta,
        gripper=gripper,
    )


def _apply_single(
    gesture: str,
    hand: HandSide,
    joints: list[float],
    settings: Settings,
) -> MapResult:
    if gesture in ("Pinch", "Grab"):
        joints[5] = settings.gripper_close
        return MapResult(joints, True, "gripper:close", gripper=settings.gripper_close)
    if gesture == "Expand":
        joints[5] = settings.gripper_open
        return MapResult(joints, True, "gripper:open", gripper=settings.gripper_open)

    d = _empty_delta()
    if gesture == "Swipe Right":
        d["y"] = STEP_XY
        return MapResult(joints, True, "pose:y+", pose_delta=d)
    if gesture == "Swipe Left":
        d["y"] = -STEP_XY
        return MapResult(joints, True, "pose:y-", pose_delta=d)

    if gesture == "Swipe V":
        if hand == HandSide.LEFT:
            d["roll"] = STEP_ROLL
            return MapResult(joints, True, "pose:roll+", pose_delta=d)
        return MapResult(joints, False, "swipe_v:right_ignored")

    if gesture == "Swipe Up":
        if hand == HandSide.RIGHT:
            d["z"] = STEP_Z
            return MapResult(joints, True, "pose:z+", pose_delta=d)
        if hand == HandSide.LEFT:
            d["x"] = STEP_XY
            return MapResult(joints, True, "pose:x+", pose_delta=d)
    if gesture == "Swipe Down":
        if hand == HandSide.RIGHT:
            d["z"] = -STEP_Z
            return MapResult(joints, True, "pose:z-", pose_delta=d)
        if hand == HandSide.LEFT:
            d["x"] = -STEP_XY
            return MapResult(joints, True, "pose:x-", pose_delta=d)

    return MapResult(joints, False, f"unmapped:{gesture}/{hand}")
