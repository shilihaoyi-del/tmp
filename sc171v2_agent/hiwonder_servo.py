#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hiwonder / Lobot helpers + JetArm soft-limit pulse mapping."""

from __future__ import annotations

from typing import List, Sequence

from joint_protection import (  # noqa: F401
    JMAX,
    JMIN,
    JOINT_MAPS,
    JOINT_SOFT_MAX,
    JOINT_SOFT_MIN,
    SERVO_IDS,
    clamp_joints_deg,
    clamp_pulse,
    deg_to_pos,
    joints_to_positions,
    pos_to_deg,
)

CMD_MOVE_TIME_WRITE = 1
CMD_POS_READ = 28


def _checksum(buf: bytes) -> int:
    return (~sum(buf[2:])) & 0xFF


def pack_move(servo_id: int, pos_0_1000: int, time_ms: int = 1000) -> bytes:
    pos = clamp_pulse(pos_0_1000)
    t = max(0, min(30000, int(time_ms)))
    body = bytes(
        [
            0x55,
            0x55,
            servo_id & 0xFF,
            7,
            CMD_MOVE_TIME_WRITE,
            pos & 0xFF,
            (pos >> 8) & 0xFF,
            t & 0xFF,
            (t >> 8) & 0xFF,
        ]
    )
    return body + bytes([_checksum(body)])


def pack_arm_joints_deg(joints_deg: Sequence[float], time_ms: int = 1000) -> List[bytes]:
    """Build 6 Lobot MOVE frames; angles soft-clamped then JetArm-mapped."""
    positions = joints_to_positions(joints_deg)
    return [pack_move(SERVO_IDS[i], positions[i], time_ms) for i in range(6)]


def hex_frames(frames: Sequence[bytes]) -> str:
    return " | ".join(" ".join("%02X" % b for b in f) for f in frames)
