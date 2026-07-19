#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Joint soft limits + pulse maps — JetArm maps with bench-tightened soft envelope.

Pulse↔angle maps match JetArm transform.angle_transform (vendor).

Bench free-move notes (approx, Jul 2026):
  base      mid≈-0.5°@498; near-stop ≈+107°@944
  shoulder  ≈+18°@50 (mechanical upper); mid -90°@500
  elbow     ends ≈±120° (raw pulse can read >1000 / garbage high)
  wrist_p   ≈-210°@hi-stop; ≈-50°@333
  wrist_r   ≈+120°@hi; 0°@500; ≈-21°@413

Soft limits are deliberately conservative (extra margin from bench stops)
because the arm can injure / burn servos at hard ends.

Pre-write gate (`ServoSafetyGate` / `verify_servo_command`) blocks burn risks:
  soft angles/pulses, slew rate, min write interval, skip unchanged rewrites.
"""

from __future__ import annotations

import json
import os
import time
from typing import List, Optional, Sequence, Tuple

# Fallback if home_pose.json missing
# Must match frontend VIEW_HOME_JOINTS_DEG / web Z-line home
# Z-line home (viewport straight); working start pose lives in initial_pose.json
DEFAULT_HOME_JOINTS = [1.68, -89.28, 4.56, -156.72, -3.84, 45.0]
DEFAULT_INITIAL_JOINTS = [1.92, -89.76, -31.92, -210.0, -3.84, 45.0]

# Soft angle limits (deg) — conservative envelope for bench / demo
# joint: base, shoulder, elbow, wrist_pitch, wrist_roll, gripper
# wrist_p soft_min opened to taught initial pose (-210°)
JOINT_SOFT_MIN = [-70.0, -132.12, -70.0, -212.0, -70.0, 15.0]
JOINT_SOFT_MAX = [90.6, -25.0, 70.0, -35.0, 70.0, 75.0]

# Pulse command band (LX bus is 0..1000; stay well off the rails)
PULSE_SOFT_MIN = 100
PULSE_SOFT_MAX = 900

# Burn-prevention rate / spam guards (used by ServoSafetyGate)
# Absolute floor; gate also uses ~0.45 * move_time so we don't rewrite mid-move (jitter).
MIN_WRITE_INTERVAL_S = 0.08
WRITE_INTERVAL_MOVE_FRAC = 0.45
# Max |Δdeg| allowed in one move_time window (scaled by move_time_ms / 1000)
MAX_DEG_STEP_AT_1000MS = [32.0, 28.0, 32.0, 36.0, 40.0, 36.0]
# Skip UART rewrite when every joint is within this of last command
UNCHANGED_EPS_DEG = 0.45

# Pulse maps: [pmin, pmax, pmid, angle_lo_side, angle_hi_side, amid]
# pulse→angle: ((p-pmid)/(pmax-pmin))*(ahi-alo)+amid
# angle→pulse: ((a-amid)/(ahi-alo))*(pmax-pmin)+pmid
JOINT_MAPS = [
    [0, 1000, 500, -120.0, 120.0, 0.0],  # j1 base
    [0, 1000, 500, 30.0, -210.0, -90.0],  # j2 shoulder
    [0, 1000, 500, 120.0, -120.0, 0.0],  # j3 elbow
    [0, 1000, 500, 30.0, -210.0, -90.0],  # j4 wrist_pitch
    [0, 1000, 500, -120.0, 120.0, 0.0],  # j5 wrist_roll
    [0, 1000, 500, 0.0, 90.0, 45.0],  # gripper
]

# Aliases used by bridge / kinematics
JMIN = list(JOINT_SOFT_MIN)
JMAX = list(JOINT_SOFT_MAX)
SERVO_IDS = [1, 2, 3, 4, 5, 6]


def clamp_joints_deg(joints: Sequence[float]) -> List[float]:
    out = []
    for i in range(6):
        v = float(joints[i]) if i < len(joints) else 0.0
        out.append(max(JMIN[i], min(JMAX[i], v)))
    return out


def clamp_pulse(pos: int) -> int:
    return max(0, min(1000, int(pos)))


def clamp_pulse_soft(pos: int) -> int:
    return max(PULSE_SOFT_MIN, min(PULSE_SOFT_MAX, int(pos)))


def angle_transform(value: float, param: Sequence[float], inverse: bool = False) -> float:
    """Same proportional map as JetArm transform.angle_transform."""
    pmin, pmax, pmid, alo, ahi, amid = (float(x) for x in param[:6])
    if inverse:
        denom = ahi - alo
        if abs(denom) < 1e-9:
            return pmid
        return ((value - amid) / denom) * (pmax - pmin) + pmid
    denom = pmax - pmin
    if abs(denom) < 1e-9:
        return amid
    return ((value - pmid) / denom) * (ahi - alo) + amid


def deg_to_pos(deg: float, joint_idx: int) -> int:
    """Soft-clamp joint angle then map to soft pulse band."""
    i = max(0, min(5, int(joint_idx)))
    d = max(JMIN[i], min(JMAX[i], float(deg)))
    pulse = angle_transform(d, JOINT_MAPS[i], inverse=True)
    return clamp_pulse_soft(int(round(pulse)))


def pos_to_deg(pos: int, joint_idx: int) -> float:
    """Pulse 0..1000 -> joint degrees (JetArm map). Invalid/high raw clamped."""
    i = max(0, min(5, int(joint_idx)))
    p = clamp_pulse(pos)
    return float(angle_transform(float(p), JOINT_MAPS[i], inverse=False))


def joints_to_positions(joints_deg: Sequence[float]) -> List[int]:
    joints = clamp_joints_deg(joints_deg)
    return [deg_to_pos(joints[i], i) for i in range(6)]


def joints_within_soft(joints_deg: Sequence[float], eps: float = 1e-3) -> bool:
    for i in range(6):
        v = float(joints_deg[i]) if i < len(joints_deg) else 0.0
        if v < JMIN[i] - eps or v > JMAX[i] + eps:
            return False
    return True


def limit_margin_deg(joints_deg: Sequence[float]) -> List[float]:
    """How many degrees remain before hitting soft min/max (min of both sides)."""
    out = []
    for i in range(6):
        v = float(joints_deg[i]) if i < len(joints_deg) else 0.0
        out.append(min(v - JMIN[i], JMAX[i] - v))
    return out


def pulse_band() -> Tuple[int, int]:
    return PULSE_SOFT_MIN, PULSE_SOFT_MAX


def _load_joints_json(filename: str, fallback: Sequence[float], path: Optional[str] = None) -> List[float]:
    candidates = []
    if path:
        candidates.append(path)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, filename))
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            joints = data.get("joints_deg") or data.get("joints")
            if isinstance(joints, list) and len(joints) >= 6:
                return clamp_joints_deg([float(x) for x in joints[:6]])
        except Exception:
            continue
    return clamp_joints_deg(fallback)


def load_home_joints(path: Optional[str] = None) -> List[float]:
    """Z-line home from home_pose.json (soft-clamped)."""
    return _load_joints_json("home_pose.json", DEFAULT_HOME_JOINTS, path)


def load_initial_joints(path: Optional[str] = None) -> List[float]:
    """Working initial pose from initial_pose.json (soft-clamped)."""
    return _load_joints_json("initial_pose.json", DEFAULT_INITIAL_JOINTS, path)


def write_interval_s(move_time_ms: int) -> float:
    """Min gap between UART writes; keeps move_time speed, avoids mid-move fight."""
    return max(MIN_WRITE_INTERVAL_S, WRITE_INTERVAL_MOVE_FRAC * float(move_time_ms) / 1000.0)


def max_deg_step(move_time_ms: int) -> List[float]:
    """Per-joint max angle step for one command, scaled by move duration."""
    scale = max(0.2, min(2.0, float(move_time_ms) / 1000.0))
    return [v * scale for v in MAX_DEG_STEP_AT_1000MS]


def slew_limit_joints(
    target: Sequence[float],
    last: Sequence[float],
    move_time_ms: int,
) -> Tuple[List[float], bool]:
    """Pull target toward last so no joint jumps faster than max_deg_step."""
    tgt = clamp_joints_deg(target)
    if not last or len(last) < 6:
        return tgt, False
    caps = max_deg_step(move_time_ms)
    out: List[float] = []
    limited = False
    for i in range(6):
        prev = float(last[i])
        want = float(tgt[i])
        cap = caps[i]
        delta = want - prev
        if abs(delta) > cap + 1e-9:
            want = prev + (cap if delta > 0 else -cap)
            limited = True
        out.append(max(JMIN[i], min(JMAX[i], want)))
    return out, limited


def pulses_within_soft(pulses: Sequence[int]) -> bool:
    for p in pulses[:6]:
        v = int(p)
        if v < PULSE_SOFT_MIN or v > PULSE_SOFT_MAX:
            return False
    return True


def verify_servo_command(
    joints_deg: Sequence[float],
    *,
    last_joints: Optional[Sequence[float]] = None,
    last_write_ts: float = 0.0,
    now_ts: Optional[float] = None,
    move_time_ms: int = 2000,
    min_interval_s: Optional[float] = None,
    force: bool = False,
) -> Tuple[bool, List[float], List[int], str]:
    """Model safety gate before any servo write.

    Returns (allow_write, safe_joints, safe_pulses, reason).
    On reject, pulses may still be filled for logging; do not send UART.
    """
    now = time.time() if now_ts is None else float(now_ts)
    if joints_deg is None or len(joints_deg) < 6:
        return False, [0.0] * 6, [500] * 6, "reject:bad_joints"

    interval = (
        write_interval_s(move_time_ms) if min_interval_s is None else float(min_interval_s)
    )
    clamped = clamp_joints_deg(joints_deg)
    if not force and last_write_ts > 0.0 and (now - last_write_ts) < interval:
        pulses = joints_to_positions(clamped)
        return False, clamped, pulses, "reject:min_interval"

    if (
        not force
        and last_joints is not None
        and len(last_joints) >= 6
        and all(abs(clamped[i] - float(last_joints[i])) <= UNCHANGED_EPS_DEG for i in range(6))
    ):
        pulses = joints_to_positions(clamped)
        return False, clamped, pulses, "skip:unchanged"

    safe, limited = slew_limit_joints(clamped, last_joints or clamped, move_time_ms)
    pulses = joints_to_positions(safe)
    if not pulses_within_soft(pulses):
        # Should not happen after deg_to_pos soft clamp; hard reject if it does
        return False, safe, pulses, "reject:pulse_soft"

    if not joints_within_soft(safe):
        return False, safe, pulses, "reject:joint_soft"

    reason = "ok:slew_limited" if limited else "ok"
    return True, safe, pulses, reason


class ServoSafetyGate(object):
    """Stateful pre-write gate for the SC171 bridge."""

    def __init__(
        self,
        min_interval_s: Optional[float] = None,
        move_time_ms: int = 2000,
    ):
        self.move_time_ms = int(move_time_ms)
        self.min_interval_s = (
            None if min_interval_s is None else float(min_interval_s)
        )
        self.last_joints: Optional[List[float]] = None
        self.last_pulses: Optional[List[int]] = None
        self.last_write_ts: float = 0.0
        self.last_reason: str = "init"
        self.reject_count: int = 0
        self.write_count: int = 0

    def verify(
        self,
        joints_deg: Sequence[float],
        *,
        move_time_ms: Optional[int] = None,
        force: bool = False,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, List[float], List[int], str]:
        mt = self.move_time_ms if move_time_ms is None else int(move_time_ms)
        allow, safe, pulses, reason = verify_servo_command(
            joints_deg,
            last_joints=self.last_joints,
            last_write_ts=self.last_write_ts,
            now_ts=now_ts,
            move_time_ms=mt,
            min_interval_s=self.min_interval_s,
            force=force,
        )
        self.last_reason = reason
        if allow:
            self.last_joints = list(safe)
            self.last_pulses = list(pulses)
            self.last_write_ts = time.time() if now_ts is None else float(now_ts)
            self.write_count += 1
        else:
            self.reject_count += 1
        return allow, safe, pulses, reason

    def reset(self, joints: Optional[Sequence[float]] = None) -> None:
        if joints is not None and len(joints) >= 6:
            self.last_joints = clamp_joints_deg(joints)
            self.last_pulses = joints_to_positions(self.last_joints)
        else:
            self.last_joints = None
            self.last_pulses = None
        self.last_write_ts = 0.0
        self.last_reason = "reset"
