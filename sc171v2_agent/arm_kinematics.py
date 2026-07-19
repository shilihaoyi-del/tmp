#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JetArm 6-DOF FK / numerical IK (pure Python, no numpy).

Link chain from jetarm_6dof_description.urdf.xacro (meters, radians).
Joints 0..4 drive pose; joint 5 is gripper (not in FK chain).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from joint_protection import JMAX as JOINT_MAX_DEG
from joint_protection import JMIN as JOINT_MIN_DEG
from joint_protection import clamp_joints_deg
from joint_protection import joints_within_soft

# Fixed transforms before each revolute joint (xyz + rpy), then axis Z rotation by q
# From URDF:
#   j1: xyz 0 0 0.10314916202, rpy 0 0 0
#   j2: xyz 0 0 0, rpy pi/2 0 0
#   j3: xyz 0 0.12941763737 0, rpy 0 0 0
#   j4: xyz 0 0.12941763737 0, rpy 0 0 0
#   j5: xyz 0 0.05945312631 0, rpy -pi/2 0 0
#   endpoint: xyz 0 0 0.11054687369
_PI = math.pi
_BASE_Z = 0.10314916202
_L2 = 0.12941763737
_L3 = 0.12941763737
_L4 = 0.05945312631
_TOOL_Z = 0.11054687369
_FIXED = [
    (0.0, 0.0, _BASE_Z, 0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, _PI / 2.0, 0.0, 0.0),
    (0.0, _L2, 0.0, 0.0, 0.0, 0.0),
    (0.0, _L3, 0.0, 0.0, 0.0, 0.0),
    (0.0, _L4, 0.0, -_PI / 2.0, 0.0, 0.0),
]
_TOOL = (0.0, 0.0, _TOOL_Z, 0.0, 0.0, 0.0)

# Conservative workspace from URDF link sum (margin keeps IK off singularity / floor)
_MAX_REACH = _L2 + _L3 + _L4 + _TOOL_Z  # ≈ 0.429 m from shoulder
_MAX_REACH_SOFT = _MAX_REACH * 0.85
_MIN_Z = 0.06
_MAX_Z = _BASE_Z + _MAX_REACH_SOFT
_MIN_R_XY = 0.03  # avoid base column singularity


def _mat_mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += a[i][k] * b[k][j]
            out[i][j] = s
    return out


def _mat_eye() -> List[List[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _rotz(q: float) -> List[List[float]]:
    c, s = math.cos(q), math.sin(q)
    return [
        [c, -s, 0.0, 0.0],
        [s, c, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _rpy_xyz(x: float, y: float, z: float, roll: float, pitch: float, yaw: float) -> List[List[float]]:
    """Fixed XYZ rpy then translation (URDF convention)."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # R = Rz(yaw) * Ry(pitch) * Rx(roll)
    r00 = cy * cp
    r01 = cy * sp * sr - sy * cr
    r02 = cy * sp * cr + sy * sr
    r10 = sy * cp
    r11 = sy * sp * sr + cy * cr
    r12 = sy * sp * cr - cy * sr
    r20 = -sp
    r21 = cp * sr
    r22 = cp * cr
    return [
        [r00, r01, r02, x],
        [r10, r11, r12, y],
        [r20, r21, r22, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _mat_from_fixed(t: Tuple[float, float, float, float, float, float]) -> List[List[float]]:
    return _rpy_xyz(t[0], t[1], t[2], t[3], t[4], t[5])


def _rot_to_rpy(R: List[List[float]]) -> Tuple[float, float, float]:
    # pitch = -asin(R20), with gimbal handling
    sy = -R[2][0]
    sy = max(-1.0, min(1.0, sy))
    pitch = math.asin(sy)
    if abs(sy) < 0.9999:
        roll = math.atan2(R[2][1], R[2][2])
        yaw = math.atan2(R[1][0], R[0][0])
    else:
        roll = math.atan2(-R[0][1], R[1][1])
        yaw = 0.0
    return roll, pitch, yaw


def deg_to_rad(joints_deg: Sequence[float]) -> List[float]:
    return [math.radians(float(j)) for j in joints_deg[:6]]


def rad_to_deg(joints_rad: Sequence[float]) -> List[float]:
    return [math.degrees(float(j)) for j in joints_rad[:6]]


def fk_matrix(joints_rad: Sequence[float]) -> List[List[float]]:
    """Full T_base_tool for joints 0..4 (joint5 ignored)."""
    T = _mat_eye()
    for i in range(5):
        T = _mat_mul(T, _mat_from_fixed(_FIXED[i]))
        q = float(joints_rad[i]) if i < len(joints_rad) else 0.0
        T = _mat_mul(T, _rotz(q))
    T = _mat_mul(T, _mat_from_fixed(_TOOL))
    return T


def fk(joints_deg: Sequence[float]) -> Dict[str, float]:
    """Forward kinematics: degrees -> pose dict (m, rad)."""
    q = deg_to_rad(clamp_joints_deg(joints_deg))
    T = fk_matrix(q)
    roll, pitch, yaw = _rot_to_rpy(T)
    return {
        "x": T[0][3],
        "y": T[1][3],
        "z": T[2][3],
        "roll": roll,
        "pitch": pitch,
        "yaw": yaw,
    }


def pose_dict(
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
) -> Dict[str, float]:
    return {"x": x, "y": y, "z": z, "roll": roll, "pitch": pitch, "yaw": yaw}


def apply_pose_delta(pose: Dict[str, float], delta: Dict[str, float]) -> Dict[str, float]:
    out = dict(pose)
    for k in ("x", "y", "z", "roll", "pitch", "yaw"):
        out[k] = float(out.get(k, 0.0)) + float(delta.get(k, 0.0))
    return out


def _wrap_pi(a: float) -> float:
    """Wrap angle to [-pi, pi] for RPY error (avoid ±pi flips)."""
    while a > _PI:
        a -= 2.0 * _PI
    while a < -_PI:
        a += 2.0 * _PI
    return a


def _pose_error(current: Dict[str, float], target: Dict[str, float]) -> List[float]:
    return [
        float(target["x"]) - float(current["x"]),
        float(target["y"]) - float(current["y"]),
        float(target["z"]) - float(current["z"]),
        _wrap_pi(float(target["roll"]) - float(current["roll"])),
        _wrap_pi(float(target["pitch"]) - float(current["pitch"])),
        _wrap_pi(float(target["yaw"]) - float(current["yaw"])),
    ]


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in v))


def pose_in_workspace(pose: Dict[str, float]) -> Tuple[bool, str]:
    """Coarse URDF workspace gate before/after IK (meters / rad)."""
    x = float(pose.get("x", 0.0))
    y = float(pose.get("y", 0.0))
    z = float(pose.get("z", 0.0))
    if z < _MIN_Z:
        return False, "z_below_floor"
    if z > _MAX_Z:
        return False, "z_above_reach"
    r_xy = math.sqrt(x * x + y * y)
    if r_xy < _MIN_R_XY and z < (_BASE_Z + 0.05):
        return False, "near_base_column"
    # Distance from shoulder origin (0,0,_BASE_Z)
    dx, dy, dz = x, y, z - _BASE_Z
    reach = math.sqrt(dx * dx + dy * dy + dz * dz)
    if reach > _MAX_REACH_SOFT:
        return False, "beyond_max_reach"
    if reach < 0.05:
        return False, "inside_min_reach"
    return True, "ok"


def fk_matches_pose(
    joints_deg: Sequence[float],
    target_pose: Dict[str, float],
    *,
    pos_tol: float = 0.008,
    ori_tol: float = 0.12,
) -> Tuple[bool, float, float]:
    """Return (ok, pos_err_m, ori_err_rad) for FK(joints) vs target pose."""
    cur = fk(joints_deg)
    err = _pose_error(cur, target_pose)
    pos_e = _norm(err[:3])
    ori_e = _norm(err[3:])
    return (pos_e <= pos_tol and ori_e <= ori_tol), pos_e, ori_e


def ik(
    target_pose: Dict[str, float],
    seed_deg: Sequence[float],
    *,
    max_iters: int = 80,
    pos_tol: float = 0.005,
    ori_tol: float = 0.08,
    step: float = 0.55,
    eps: float = 1e-4,
) -> Tuple[List[float], bool]:
    """Numerical Jacobian IK for joints 0..4; joint5 (gripper) kept from seed.

    Returns (joints_deg, ok). Orientation weights are reduced vs position.
    """
    q_deg = clamp_joints_deg(seed_deg)
    gripper = q_deg[5] if len(q_deg) > 5 else JOINT_MIN_DEG[5]
    w = [1.0, 1.0, 1.0, 0.25, 0.25, 0.25]

    for _ in range(max_iters):
        cur = fk(q_deg)
        err = _pose_error(cur, target_pose)
        err_w = [err[i] * w[i] for i in range(6)]
        pos_e = _norm(err[:3])
        ori_e = _norm(err[3:])
        if pos_e < pos_tol and ori_e < ori_tol:
            q_deg[5] = gripper
            return clamp_joints_deg(q_deg), True

        # Numerical Jacobian 6x5
        J = [[0.0] * 5 for _ in range(6)]
        base = deg_to_rad(q_deg)
        for j in range(5):
            qp = list(base)
            qp[j] += eps
            fp = fk(rad_to_deg(qp + [0.0]))
            for r in range(6):
                keys = ("x", "y", "z", "roll", "pitch", "yaw")
                J[r][j] = (fp[keys[r]] - cur[keys[r]]) / eps

        # Weight rows
        for r in range(6):
            for j in range(5):
                J[r][j] *= w[r]

        # Damped least-squares: dq = J^T (J J^T + l^2 I)^-1 err
        # Adaptive λ near singularity (small ||J||_F → larger damping → less chatter)
        f2 = sum(J[r][k] * J[r][k] for r in range(6) for k in range(5))
        lam2 = 2e-3 + 8e-3 / (f2 + 1e-6)
        dq = _dls_joint_step(J, err_w, lam2)
        if dq is None:
            break

        for j in range(5):
            q_deg[j] += math.degrees(dq[j] * step)
        q_deg = clamp_joints_deg(q_deg)
        q_deg[5] = gripper

    q_deg[5] = gripper
    q_deg = clamp_joints_deg(q_deg)
    ok, pos_e, _ori_e = fk_matches_pose(
        q_deg, target_pose, pos_tol=0.012, ori_tol=0.20
    )
    return q_deg, ok


def solve_reachable(
    target_pose: Dict[str, float],
    seed_deg: Sequence[float],
    *,
    gripper: Optional[float] = None,
) -> Tuple[Optional[List[float]], bool, str]:
    """IK + URDF workspace + FK verify. On failure returns (None, False, reason)."""
    ws_ok, ws_why = pose_in_workspace(target_pose)
    if not ws_ok:
        return None, False, "workspace:%s" % ws_why

    joints, ok = ik(target_pose, seed_deg)
    if gripper is not None:
        joints[5] = float(gripper)
        joints = clamp_joints_deg(joints)

    if not joints_within_soft(joints):
        return None, False, "joint_soft_limit"

    match, pos_e, ori_e = fk_matches_pose(joints, target_pose)
    if not ok or not match:
        return None, False, "ik_miss:pos=%.4f,ori=%.3f" % (pos_e, ori_e)

    return joints, True, "ok"


def _solve6(A: List[List[float]], b: Sequence[float]) -> Optional[List[float]]:
    """Solve 6x6 linear system; returns None on singular."""
    M = [row[:] + [float(b[i])] for i, row in enumerate(A)]
    n = 6
    for col in range(n):
        pivot = col
        best = abs(M[col][col])
        for r in range(col + 1, n):
            v = abs(M[r][col])
            if v > best:
                best = v
                pivot = r
        if best < 1e-12:
            return None
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
        div = M[col][col]
        for c in range(col, n + 1):
            M[col][c] /= div
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                M[r][c] -= factor * M[col][c]
    return [M[i][n] for i in range(n)]


def numerical_jacobian(
    joints_deg: Sequence[float], *, eps: float = 1e-4
) -> List[List[float]]:
    """6x5 geometric Jacobian via finite difference (m, rad / rad)."""
    q = clamp_joints_deg(joints_deg)
    cur = fk(q)
    keys = ("x", "y", "z", "roll", "pitch", "yaw")
    J = [[0.0] * 5 for _ in range(6)]
    base = deg_to_rad(q)
    for j in range(5):
        qp = list(base)
        qp[j] += eps
        fp = fk(rad_to_deg(qp + [0.0]))
        for r in range(6):
            d = float(fp[keys[r]]) - float(cur[keys[r]])
            if r >= 3:
                d = _wrap_pi(d)
            J[r][j] = d / eps
    return J


def _j_times_dq(J: List[List[float]], dq_rad: Sequence[float]) -> List[float]:
    out = [0.0] * 6
    for r in range(6):
        s = 0.0
        for j in range(5):
            s += J[r][j] * float(dq_rad[j])
        out[r] = s
    return out


def _dls_joint_step(
    J: List[List[float]], dx: Sequence[float], lam2: float
) -> Optional[List[float]]:
    """dq = J^T (J J^T + λ² I)^{-1} dx  (5 joints)."""
    A = [[0.0] * 6 for _ in range(6)]
    for r in range(6):
        for c in range(6):
            s = 0.0
            for k in range(5):
                s += J[r][k] * J[c][k]
            A[r][c] = s + (lam2 if r == c else 0.0)
    y = _solve6(A, dx)
    if y is None:
        return None
    dq = [0.0] * 5
    for j in range(5):
        s = 0.0
        for r in range(6):
            s += J[r][j] * y[r]
        dq[j] = s
    return dq


# Half of stock JetArm pace (~500ms / ~0.06 m/s TCP) → ~0.03 m/s, ~0.18 rad/s
_TCP_VEL_HALF_MPS = 0.03
_ORI_VEL_HALF_RPS = 0.18
# Near singularity, further cut Cartesian / joint rates (anti-jitter)
_TCP_VEL_SING_MPS = 0.012
_ORI_VEL_SING_RPS = 0.08
# Max |Δq| deg per command (hard cap; tighter near singularity)
_MAX_DQ_DEG = [12.0, 10.0, 12.0, 14.0, 16.0]
_MAX_DQ_DEG_SING = [5.0, 4.0, 5.0, 6.0, 7.0]


def _singularity_score(joints_deg: Sequence[float], f2: float) -> float:
    """0 = well-conditioned, 1 = strongly singular (wrist/elbow/reach).

    Combines Jacobian Frobenius energy with JetArm geometric heuristics:
      - elbow near 0° → arm stretched (elbow singularity)
      - wrist_pitch near ±90° of shoulder plane → wrist singularity risk
    """
    # Low ||J||_F → singular
    jac_s = 1.0 / (1.0 + f2 * 25.0)
    elbow = abs(float(joints_deg[2]))  # deg; ~0 is stretched
    elbow_s = max(0.0, 1.0 - elbow / 35.0)  # strong when |elbow| < 35°
    # wrist_p around -90 / +0 relative configs are twitchy; use distance to -90
    wp = float(joints_deg[3])
    wrist_s = max(0.0, 1.0 - abs(wp + 90.0) / 50.0)
    # blend
    score = max(jac_s, 0.65 * elbow_s + 0.35 * wrist_s * jac_s)
    return max(0.0, min(1.0, score))


def smooth_joints_jacobian(
    current_deg: Sequence[float],
    target_deg: Sequence[float],
    *,
    move_time_ms: int = 2000,
) -> Tuple[List[float], str, int]:
    """Map joint step through J → limit TCP → DLS back; adapt move_time.

    Speed policy (half of original) + singularity anti-jitter:
      - Cap Cartesian velocity; cut further when singular
      - Stronger DLS λ near singularity
      - Cap per-joint Δq; stretch move_time when singular
    """
    base_ms = max(400, int(move_time_ms))
    cur = clamp_joints_deg(current_deg)
    tgt = clamp_joints_deg(target_deg)
    dq_des = [math.radians(float(tgt[i]) - float(cur[i])) for i in range(5)]
    if _norm(dq_des) < 1e-9:
        out = list(cur)
        out[5] = tgt[5]
        return clamp_joints_deg(out), "jac:noop", base_ms

    J = numerical_jacobian(cur)
    dx_full = _j_times_dq(J, dq_des)
    f2 = sum(J[r][k] * J[r][k] for r in range(6) for k in range(5))
    sing = _singularity_score(cur, f2)  # 0..1

    tcp_vel = _TCP_VEL_HALF_MPS * (1.0 - 0.60 * sing) + _TCP_VEL_SING_MPS * (0.60 * sing)
    ori_vel = _ORI_VEL_HALF_RPS * (1.0 - 0.60 * sing) + _ORI_VEL_SING_RPS * (0.60 * sing)
    # Time needed at (possibly reduced) speed for uncapped Cartesian step
    t_pos = _norm(dx_full[:3]) / max(1e-9, tcp_vel)
    t_ori = _norm(dx_full[3:]) / max(1e-9, ori_vel)
    # Singularity stretch on duration (up to ~3.2x base)
    stretch = 1.0 + 2.2 * sing
    t_need = max(t_pos, t_ori, base_ms / 1000.0 * 0.55) * stretch
    adapt_ms = int(max(base_ms * 0.8, min(base_ms * 3.2, t_need * 1000.0)))
    dt = adapt_ms / 1000.0

    max_pos = tcp_vel * dt
    max_ori = ori_vel * dt
    dx = list(dx_full)
    pos_n = _norm(dx[:3])
    ori_n = _norm(dx[3:])
    limited = False
    if pos_n > max_pos and pos_n > 1e-12:
        s = max_pos / pos_n
        for i in range(3):
            dx[i] *= s
        limited = True
    if ori_n > max_ori and ori_n > 1e-12:
        s = max_ori / ori_n
        for i in range(3, 6):
            dx[i] *= s
        limited = True

    # DLS damping: much stronger near singularity (classic anti-jitter)
    lam2 = (2.0e-3 + 4.0e-2 * sing) + (2.5e-2 + 0.18 * sing) / (f2 + 1e-6)
    dq = _dls_joint_step(J, dx, lam2)
    if dq is None:
        return clamp_joints_deg(tgt), "jac:fallback", adapt_ms

    # Hard per-joint step caps (tighter when singular)
    caps = [
        _MAX_DQ_DEG[i] * (1.0 - sing) + _MAX_DQ_DEG_SING[i] * sing for i in range(5)
    ]
    out = list(cur)
    for j in range(5):
        ddeg = math.degrees(dq[j])
        if abs(ddeg) > caps[j]:
            ddeg = math.copysign(caps[j], ddeg)
            limited = True
        out[j] = float(cur[j]) + ddeg
    out[5] = float(tgt[5])

    if sing >= 0.55 and limited:
        why = "jac:limited_sing"
    elif sing >= 0.55:
        why = "jac:sing_slow"
    elif limited:
        why = "jac:limited"
    else:
        why = "jac:ok"
    return clamp_joints_deg(out), why, adapt_ms


class JacobianSmoother(object):
    """Stateful Jacobian smooth + EMA + anti-chatter for bridge writes."""

    def __init__(self, ema: float = 0.35, chatter_deg: float = 2.4):
        # Lower ema → heavier smoothing; larger chatter window kills sing flips
        self.ema = float(ema)
        self.chatter_deg = float(chatter_deg)
        self._filt: Optional[List[float]] = None
        self._last_dq = [0.0] * 6
        self.last_move_time_ms = 2000
        self.last_sing = 0.0

    def reset(self, joints: Optional[Sequence[float]] = None) -> None:
        if joints is not None and len(joints) >= 6:
            self._filt = clamp_joints_deg(joints)
        else:
            self._filt = None
        self._last_dq = [0.0] * 6
        self.last_sing = 0.0

    def step(
        self,
        current_deg: Sequence[float],
        target_deg: Sequence[float],
        *,
        move_time_ms: int = 2000,
    ) -> Tuple[List[float], str, int]:
        cur = clamp_joints_deg(current_deg)
        raw, why, adapt_ms = smooth_joints_jacobian(
            cur, target_deg, move_time_ms=move_time_ms
        )
        # Estimate singularity for EMA / anti-chatter tuning
        J = numerical_jacobian(cur)
        f2 = sum(J[r][k] * J[r][k] for r in range(6) for k in range(5))
        sing = _singularity_score(cur, f2)
        self.last_sing = sing

        dq = [float(raw[i]) - float(cur[i]) for i in range(6)]
        # Near singularity: kill small direction reversals more aggressively
        chatter = self.chatter_deg * (1.0 + 1.8 * sing)
        for i in range(5):
            if self._last_dq[i] * dq[i] < 0.0 and abs(dq[i]) < chatter:
                raw[i] = cur[i]
                dq[i] = 0.0
                why = "jac:anti_chatter"
        # Heavier EMA when singular (less twitch)
        a = self.ema * (1.0 - 0.55 * sing)
        if self._filt is None:
            self._filt = list(raw)
        else:
            blended = [
                a * float(raw[i]) + (1.0 - a) * float(self._filt[i]) for i in range(6)
            ]
            blended[5] = float(raw[5])
            self._filt = clamp_joints_deg(blended)
        self._last_dq = dq
        self.last_move_time_ms = int(adapt_ms)
        return list(self._filt), why, int(adapt_ms)


def self_test() -> None:
    # Reachable seed inside soft limits (elbow up keeps TCP above floor)
    q0 = [0.0, -90.0, 60.0, -90.0, 0.0, 45.0]
    p0 = fk(q0)
    assert p0["z"] > _MIN_Z
    ws_ok, ws_why = pose_in_workspace(p0)
    assert ws_ok, ws_why
    target = apply_pose_delta(p0, {"x": 0.02, "y": 0.0, "z": 0.01})
    q1, ok, why = solve_reachable(target, q0)
    assert ok and q1 is not None, why
    p1 = fk(q1)
    err = _norm([p1["x"] - target["x"], p1["y"] - target["y"], p1["z"] - target["z"]])
    assert err < 0.015

    J = numerical_jacobian(q0)
    assert len(J) == 6 and len(J[0]) == 5
    q_far = clamp_joints_deg([40.0, -40.0, 50.0, -60.0, 20.0, 45.0])
    q_s, why_s, mt_s = smooth_joints_jacobian(q0, q_far, move_time_ms=2000)
    assert why_s.startswith("jac:")
    # Singularity stretch allows up to ~3.2x base move_time
    assert 1000 <= mt_s <= 7000
    # Smoothed step should not overshoot past target on every axis blindly;
    # TCP displacement from q0→q_s must be finite and smaller than q0→q_far jump.
    p_s = fk(q_s)
    p_f = fk(q_far)
    d_s = _norm([p_s["x"] - p0["x"], p_s["y"] - p0["y"], p_s["z"] - p0["z"]])
    d_f = _norm([p_f["x"] - p0["x"], p_f["y"] - p0["y"], p_f["z"] - p0["z"]])
    assert d_s <= d_f + 1e-6
    sm = JacobianSmoother()
    sm.reset(q0)
    q_a, _, mt_a = sm.step(q0, q_far, move_time_ms=2000)
    q_b, why_b, mt_b = sm.step(q_a, q0, move_time_ms=2000)  # reverse → anti-chatter possible
    assert len(q_b) == 6
    assert mt_a >= 1000 and mt_b >= 1000
    _ = why_b
    far = pose_dict(x=2.0, y=0.0, z=0.2)
    _q_bad, ok_bad, why_bad = solve_reachable(far, q0)
    assert not ok_bad and why_bad.startswith("workspace")
    # Through-floor joint combo must fail workspace gate
    q_bad = clamp_joints_deg([0.0, -90.0, 0.0, -90.0, 0.0, 45.0])
    ws2, why2 = pose_in_workspace(fk(q_bad))
    assert not ws2 and why2 == "z_below_floor"
    print(
        "arm_kinematics self_test OK pose0=%s ik_ok=%s err=%.4f reject=%s"
        % (p0, ok, err, why_bad)
    )


if __name__ == "__main__":
    self_test()
