#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JetArm merchant AA55 packet protocol (USART1 / Type-C @ 1 Mbps).

Frame: AA 55 | function | data_length | data... | CRC8
CRC8 covers [function, data_length, data...] — same table as JetArm checksum.c
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

PROTO_START1 = 0xAA
PROTO_START2 = 0x55

PACKET_FUNC_SYS = 0
PACKET_FUNC_LED = 1
PACKET_FUNC_BUZZER = 2
PACKET_FUNC_MOTOR = 3
PACKET_FUNC_PWM_SERVO = 4
PACKET_FUNC_BUS_SERVO = 5
PACKET_FUNC_KEY = 6

# Bus-servo sub-commands (packet_handle.c)
SUB_SET_POSITION = 0x01
SUB_READ_POSITION = 0x05
SUB_READ_VIN = 0x07
SUB_UNLOAD = 0x0B
SUB_LOAD = 0x0C
SUB_READ_ID = 0x12

# CRC8 table from JetArmF4 checksum.c
_CRC8_TABLE = [
    0, 94, 188, 226, 97, 63, 221, 131, 194, 156, 126, 32, 163, 253, 31, 65,
    157, 195, 33, 127, 252, 162, 64, 30, 95, 1, 227, 189, 62, 96, 130, 220,
    35, 125, 159, 193, 66, 28, 254, 160, 225, 191, 93, 3, 128, 222, 60, 98,
    190, 224, 2, 92, 223, 129, 99, 61, 124, 34, 192, 158, 29, 67, 161, 255,
    70, 24, 250, 164, 39, 121, 155, 197, 132, 218, 56, 102, 229, 187, 89, 7,
    219, 133, 103, 57, 186, 228, 6, 88, 25, 71, 165, 251, 120, 38, 196, 154,
    101, 59, 217, 135, 4, 90, 184, 230, 167, 249, 27, 69, 198, 152, 122, 36,
    248, 166, 68, 26, 153, 199, 37, 123, 58, 100, 134, 216, 91, 5, 231, 185,
    140, 210, 48, 110, 237, 179, 81, 15, 78, 16, 242, 172, 47, 113, 147, 205,
    17, 79, 173, 243, 112, 46, 204, 146, 211, 141, 111, 49, 178, 236, 14, 80,
    175, 241, 19, 77, 206, 144, 114, 44, 109, 51, 209, 143, 12, 82, 176, 238,
    50, 108, 142, 208, 83, 13, 239, 177, 240, 174, 76, 18, 145, 207, 45, 115,
    202, 148, 118, 40, 171, 245, 23, 73, 8, 86, 180, 234, 105, 55, 213, 139,
    87, 9, 235, 181, 54, 104, 138, 212, 149, 203, 41, 119, 244, 170, 72, 22,
    233, 183, 85, 11, 136, 214, 52, 106, 43, 117, 151, 201, 74, 20, 246, 168,
    116, 42, 200, 150, 21, 75, 169, 247, 182, 232, 10, 84, 215, 137, 107, 53,
]


def checksum_crc8(buf: bytes) -> int:
    check = 0
    for b in buf:
        check = _CRC8_TABLE[check ^ b]
    return check & 0xFF


def pack_frame(function: int, data: Sequence[int]) -> bytes:
    data_bytes = bytes(int(x) & 0xFF for x in data)
    body = bytes([function & 0xFF, len(data_bytes)]) + data_bytes
    return bytes([PROTO_START1, PROTO_START2]) + body + bytes([checksum_crc8(body)])


def pack_set_positions(
    ids: Sequence[int],
    positions: Sequence[int],
    duration_ms: int = 1000,
) -> bytes:
    """BUS_SERVO 0x01: multi servo set position."""
    if len(ids) != len(positions) or not ids:
        raise ValueError("ids/positions length mismatch")
    dur = max(0, min(30000, int(duration_ms)))
    data: List[int] = [
        SUB_SET_POSITION,
        dur & 0xFF,
        (dur >> 8) & 0xFF,
        len(ids) & 0xFF,
    ]
    for sid, pos in zip(ids, positions):
        p = max(0, min(1000, int(pos)))
        data.extend([int(sid) & 0xFF, p & 0xFF, (p >> 8) & 0xFF])
    return pack_frame(PACKET_FUNC_BUS_SERVO, data)


def pack_read_position(servo_id: int) -> bytes:
    return pack_frame(PACKET_FUNC_BUS_SERVO, [SUB_READ_POSITION, int(servo_id) & 0xFF])


def pack_load(servo_id: int) -> bytes:
    return pack_frame(PACKET_FUNC_BUS_SERVO, [SUB_LOAD, int(servo_id) & 0xFF])


def pack_unload(servo_id: int) -> bytes:
    return pack_frame(PACKET_FUNC_BUS_SERVO, [SUB_UNLOAD, int(servo_id) & 0xFF])


def hex_frame(data: bytes) -> str:
    return " ".join("%02X" % b for b in data)


def parse_bus_servo_report(frame: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a completed BUS_SERVO report frame dict from JetArmStreamParser."""
    if frame.get("function") != PACKET_FUNC_BUS_SERVO:
        return None
    data = frame.get("data") or b""
    if len(data) < 3:
        return None
    # Report: servo_id, sub_command, success, args...
    return {
        "servo_id": data[0],
        "sub_cmd": data[1],
        "success": data[2],  # 0 = OK, 0xFF = fail
        "args": bytes(data[3:]),
        "raw": frame.get("raw"),
    }


class JetArmStreamParser(object):
    """Incremental parser for JetArm AA55 frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        if not data:
            return []
        self._buf.extend(data)
        out: List[Dict[str, Any]] = []
        while True:
            fr = self._try_pop_one()
            if fr is None:
                break
            out.append(fr)
        return out

    def _try_pop_one(self) -> Optional[Dict[str, Any]]:
        buf = self._buf
        # sync to AA 55
        while len(buf) >= 2 and not (buf[0] == PROTO_START1 and buf[1] == PROTO_START2):
            del buf[0]
        if len(buf) < 4:
            return None
        func = buf[2]
        length = buf[3]
        total = 4 + length + 1  # header+func+len+data+crc
        if length > 250:
            del buf[0]
            return None
        if len(buf) < total:
            return None
        raw = bytes(buf[:total])
        del buf[:total]
        body = raw[2 : 4 + length]  # func, len, data
        crc_got = raw[-1]
        crc_exp = checksum_crc8(body)
        if crc_got != crc_exp:
            return None
        return {
            "function": func,
            "data_length": length,
            "data": bytes(raw[4 : 4 + length]),
            "raw": raw,
        }


def self_test() -> None:
    """Validate against VOFA-proven frames."""
    # KEY press frame from user
    key = bytes([0xAA, 0x55, 0x06, 0x02, 0x00, 0x01, 0x18])
    assert checksum_crc8(key[2:-1]) == key[-1]
    # Read position ID1 request / reply
    req = pack_read_position(1)
    assert hex_frame(req) == "AA 55 05 02 05 01 6F"
    move = pack_set_positions([1], [450], 500)
    assert hex_frame(move) == "AA 55 05 07 01 F4 01 01 01 C2 01 D7"
    p = JetArmStreamParser()
    frames = p.feed(bytes.fromhex("AA 55 05 05 01 05 00 00 02 D2"))
    assert len(frames) == 1
    rep = parse_bus_servo_report(frames[0])
    assert rep is not None
    assert rep["success"] == 0
    assert rep["servo_id"] == 1
    pos = rep["args"][0] | (rep["args"][1] << 8)
    assert pos == 512
    print("jetarm_packet self_test OK")


if __name__ == "__main__":
    self_test()
