#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hiwonder / Lobot bus-servo frames (幻尔) for SC171 direct drive over USB-UART."""

from __future__ import annotations

from typing import List, Sequence

# Soft limits (deg) — match cloud/SC171
JMIN = [-180.0, -90.0, -135.0, -90.0, -180.0, 0.0]
JMAX = [180.0, 90.0, 135.0, 90.0, 180.0, 90.0]
SERVO_IDS = [1, 2, 3, 4, 5, 6]

CMD_MOVE_TIME_WRITE = 1
CMD_POS_READ = 28


def deg_to_pos(deg: float, min_deg: float, max_deg: float) -> int:
    if max_deg <= min_deg:
        return 500
    t = (float(deg) - min_deg) / (max_deg - min_deg)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return int(round(t * 1000.0))


def pos_to_deg(pos: int, min_deg: float, max_deg: float) -> float:
    pos = max(0, min(1000, int(pos)))
    return min_deg + (pos / 1000.0) * (max_deg - min_deg)


def _checksum(buf: bytes) -> int:
    # sum from ID through last param, then ~ 
    return (~sum(buf[2:])) & 0xFF


def pack_move(servo_id: int, pos_0_1000: int, time_ms: int = 500) -> bytes:
    pos = max(0, min(1000, int(pos_0_1000)))
    t = max(0, min(30000, int(time_ms)))
    # 55 55 | ID | Len=7 | Cmd=1 | posL posH timeL timeH | CHK
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


def pack_arm_joints_deg(joints_deg: Sequence[float], time_ms: int = 500) -> List[bytes]:
    """Build 6 Lobot MOVE frames for a 6-DOF arm."""
    frames = []
    for i in range(6):
        deg = float(joints_deg[i]) if i < len(joints_deg) else 0.0
        pos = deg_to_pos(deg, JMIN[i], JMAX[i])
        frames.append(pack_move(SERVO_IDS[i], pos, time_ms))
    return frames


def hex_frames(frames: Sequence[bytes]) -> str:
    return " | ".join(" ".join("%02X" % b for b in f) for f in frames)
