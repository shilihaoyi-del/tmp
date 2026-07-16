"""Map SHREC-14 gestures to six-DOF arm joint deltas.

Handled gestures (plan book):
  Swipe Right / Left              -> base rotation
  Swipe Up / Down (Right hand)   -> shoulder
  Swipe Up / Down (Left hand)    -> elbow
  Swipe Up / Down (both hands)   -> wrist pitch
  Swipe V (Left)                 -> wrist roll
  Pinch / Grab                   -> gripper close
  Expand                         -> gripper open

Unhandled classifiers (Tap, Rotation CW/CCW, Swipe Cross, Shake, Other) are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.models.schemas import GestureEvent, HandSide


# Only these gestures produce motion
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


@dataclass
class MapResult:
    joints: list[float]
    applied: bool
    reason: str


def _is_swipe_vertical(name: str) -> bool:
    return name in ("Swipe Up", "Swipe Down")


def map_gesture_to_joints(
    event: GestureEvent,
    current: list[float],
    settings: Settings,
) -> MapResult:
    """Apply one gesture event onto current joint targets. Returns new targets."""
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

    # Dual-hand payload: Both
    if event.hand == HandSide.BOTH or (left_g and right_g):
        return _map_dual(left_g, right_g, left_c, right_c, joints, settings)

    # Single-hand
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
    # Both hands vertical swipe -> wrist pitch
    if (
        left_g
        and right_g
        and _is_swipe_vertical(left_g)
        and _is_swipe_vertical(right_g)
        and left_c >= CONF_THRESHOLD
        and right_c >= CONF_THRESHOLD
    ):
        # Prefer right hand direction if they disagree
        direction = right_g
        delta = settings.step_wrist_pitch if direction == "Swipe Up" else -settings.step_wrist_pitch
        joints[3] += delta
        return MapResult(joints, True, "wrist_pitch:both")

    # Prefer right for base/shoulder, left for elbow / swipe-v / gripper
    applied = False
    reasons: list[str] = []

    if right_g and right_c >= CONF_THRESHOLD and right_g in HANDLED:
        r = _apply_single(right_g, HandSide.RIGHT, joints, settings)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)

    if left_g and left_c >= CONF_THRESHOLD and left_g in HANDLED:
        r = _apply_single(left_g, HandSide.LEFT, joints, settings)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)

    return MapResult(joints, applied, ",".join(reasons) if reasons else "no_action")


def _apply_single(
    gesture: str,
    hand: HandSide,
    joints: list[float],
    settings: Settings,
) -> MapResult:
    # Gripper (either hand)
    if gesture in ("Pinch", "Grab"):
        joints[5] = settings.gripper_close
        return MapResult(joints, True, "gripper:close")
    if gesture == "Expand":
        joints[5] = settings.gripper_open
        return MapResult(joints, True, "gripper:open")

    # Base rotation (either hand)
    if gesture == "Swipe Right":
        joints[0] += settings.step_base
        return MapResult(joints, True, "base:+")
    if gesture == "Swipe Left":
        joints[0] -= settings.step_base
        return MapResult(joints, True, "base:-")

    # Swipe V left hand -> wrist roll
    if gesture == "Swipe V":
        if hand == HandSide.LEFT:
            joints[4] += settings.step_wrist_roll
            return MapResult(joints, True, "wrist_roll:+")
        return MapResult(joints, False, "swipe_v:right_ignored")

    # Vertical swipe: right -> shoulder, left -> elbow
    if gesture == "Swipe Up":
        if hand == HandSide.RIGHT:
            joints[1] += settings.step_shoulder
            return MapResult(joints, True, "shoulder:+")
        if hand == HandSide.LEFT:
            joints[2] += settings.step_elbow
            return MapResult(joints, True, "elbow:+")
    if gesture == "Swipe Down":
        if hand == HandSide.RIGHT:
            joints[1] -= settings.step_shoulder
            return MapResult(joints, True, "shoulder:-")
        if hand == HandSide.LEFT:
            joints[2] -= settings.step_elbow
            return MapResult(joints, True, "elbow:-")

    return MapResult(joints, False, f"unmapped:{gesture}/{hand}")
