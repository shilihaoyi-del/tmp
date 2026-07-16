"""Joint limits, TTL and emergency-stop helpers."""

from __future__ import annotations

from app.config import Settings


def clamp_joints(joints: list[float], settings: Settings) -> list[float]:
    """Clamp each joint angle into configured soft limits."""
    out: list[float] = []
    for i, value in enumerate(joints):
        lo = settings.joint_min[i]
        hi = settings.joint_max[i]
        out.append(max(lo, min(hi, float(value))))
    return out


def is_command_expired(cmd_ts_ms: int, now_ms: int, ttl_ms: int) -> bool:
    """Return True when a command has exceeded its validity window."""
    if ttl_ms <= 0:
        return False
    return (now_ms - cmd_ts_ms) > ttl_ms
