#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SC171V2 <-> STM32 UART frame pack/unpack (20-byte fixed)."""

from __future__ import annotations

import argparse
import struct
import sys
import time
from typing import Iterable, List, Optional, Sequence, Tuple

HEAD0 = 0xAA
HEAD1 = 0x55
VER = 0x01

CMD_JOINT = 0x01
CMD_HEARTBEAT = 0x02
CMD_ESTOP = 0x03
CMD_HOLD = 0x04
CMD_STATUS = 0x81  # STM32 -> SC171 main reply
CMD_ACK = 0x82
CMD_FAULT = 0x83

FLAG_ESTOP = 1 << 0
FLAG_HOLD = 1 << 1
FLAG_MOVING = 1 << 2
FLAG_FAULT = 1 << 3
FLAG_ONLINE = 1 << 4

FRAME_LEN = 20


def pack_status_reply(
    seq: int,
    joints_deg: Sequence[float],
    *,
    moving: bool = False,
    estop: bool = False,
    hold: bool = False,
    fault: bool = False,
) -> bytes:
    """STM32->SC171 STATUS(0x81) frame that SC171 already understands."""
    flags = FLAG_ONLINE
    if moving:
        flags |= FLAG_MOVING
    if estop:
        flags |= FLAG_ESTOP
    if hold:
        flags |= FLAG_HOLD
    if fault:
        flags |= FLAG_FAULT
    return pack_frame(CMD_STATUS, seq, joints_deg, flags)


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def deg_to_centi(deg: float) -> int:
    v = int(round(float(deg) * 100.0))
    return max(-32768, min(32767, v))


def centi_to_deg(c: int) -> float:
    return float(c) / 100.0


def pack_frame(
    cmd: int,
    seq: int,
    joints_deg: Sequence[float],
    flags: int = 0,
) -> bytes:
    """Build one 20-byte frame."""
    if len(joints_deg) != 6:
        raise ValueError("need 6 joints")
    body = bytearray(18)
    body[0] = HEAD0
    body[1] = HEAD1
    body[2] = VER
    body[3] = cmd & 0xFF
    body[4] = seq & 0xFF
    body[5] = flags & 0xFF
    for i, d in enumerate(joints_deg):
        struct.pack_into("<h", body, 6 + i * 2, deg_to_centi(d))
    crc = crc16_modbus(bytes(body))
    return bytes(body) + struct.pack("<H", crc)


def unpack_frame(raw: bytes) -> Optional[dict]:
    """Parse one frame; return None if invalid."""
    if len(raw) < FRAME_LEN:
        return None
    frame = raw[:FRAME_LEN]
    if frame[0] != HEAD0 or frame[1] != HEAD1 or frame[2] != VER:
        return None
    got = struct.unpack_from("<H", frame, 18)[0]
    expect = crc16_modbus(frame[:18])
    if got != expect:
        return None
    joints = [centi_to_deg(struct.unpack_from("<h", frame, 6 + i * 2)[0]) for i in range(6)]
    return {
        "cmd": frame[3],
        "seq": frame[4],
        "flags": frame[5],
        "estop": bool(frame[5] & FLAG_ESTOP),
        "hold": bool(frame[5] & FLAG_HOLD),
        "joints_deg": joints,
        "raw": frame,
    }


def hex_frame(frame: bytes) -> str:
    return " ".join("%02X" % b for b in frame)


class FrameStreamParser:
    """Byte-stream reassembler for STM32/PC side."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[dict]:
        self._buf.extend(data)
        out: List[dict] = []
        while True:
            if len(self._buf) < FRAME_LEN:
                break
            # hunt header
            idx = -1
            for i in range(len(self._buf) - 1):
                if self._buf[i] == HEAD0 and self._buf[i + 1] == HEAD1:
                    idx = i
                    break
            if idx < 0:
                self._buf.clear()
                break
            if idx > 0:
                del self._buf[:idx]
            if len(self._buf) < FRAME_LEN:
                break
            parsed = unpack_frame(bytes(self._buf[:FRAME_LEN]))
            if parsed is None:
                del self._buf[0]  # resync
                continue
            out.append(parsed)
            del self._buf[:FRAME_LEN]
        return out


def send_joint(
    port: str,
    joints: Sequence[float],
    seq: int = 1,
    baud: int = 115200,
    estop: bool = False,
    hold: bool = False,
) -> bytes:
    import serial

    flags = 0
    cmd = CMD_JOINT
    if estop:
        flags |= FLAG_ESTOP
        cmd = CMD_ESTOP
    elif hold:
        flags |= FLAG_HOLD
        cmd = CMD_HOLD
    frame = pack_frame(cmd, seq, joints, flags)
    ser = serial.Serial(port, baudrate=baud, timeout=0.2)
    try:
        ser.write(frame)
        ser.flush()
    finally:
        ser.close()
    return frame


def demo_print(joints: Sequence[float], seq: int = 1) -> None:
    frame = pack_frame(CMD_JOINT, seq, joints, 0)
    print("joints_deg:", list(joints))
    print("frame_hex:", hex_frame(frame))
    print("frame_len:", len(frame))
    back = unpack_frame(frame)
    print("unpack:", back)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="STM32 UART protocol helper")
    p.add_argument(
        "--joints",
        default="10,20,-15,0,5,40",
        help="six joint degrees, comma-separated",
    )
    p.add_argument("--seq", type=int, default=1)
    p.add_argument("--port", default="", help="serial port, e.g. /tmp/ttyACM_sc171")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--estop", action="store_true")
    p.add_argument("--hold", action="store_true")
    p.add_argument("--repeat", type=int, default=1, help="send N times")
    p.add_argument("--hz", type=float, default=20.0)
    p.add_argument(
        "--as-status",
        action="store_true",
        help="print/send STATUS(0x81) reply frame instead of JOINT",
    )
    args = p.parse_args(argv)

    joints = [float(x.strip()) for x in args.joints.split(",")]
    if len(joints) != 6:
        print("need exactly 6 joints", file=sys.stderr)
        return 2

    if args.as_status:
        frame = pack_status_reply(args.seq, joints, estop=args.estop, hold=args.hold)
        print("STATUS reply for SC171V2:")
        print("joints_deg:", list(joints))
        print("frame_hex:", hex_frame(frame))
        print("frame_len:", len(frame))
        print("unpack:", unpack_frame(frame))
        if args.port:
            import serial

            ser = serial.Serial(args.port, args.baud, timeout=0.2)
            try:
                ser.write(frame)
                ser.flush()
            finally:
                ser.close()
            print("sent to", args.port)
        return 0

    if not args.port:
        demo_print(joints, args.seq)
        return 0

    interval = 1.0 / max(args.hz, 0.1)
    for i in range(args.repeat):
        frame = send_joint(
            args.port,
            joints,
            seq=(args.seq + i) & 0xFF,
            baud=args.baud,
            estop=args.estop,
            hold=args.hold,
        )
        print("[%d] TX %s" % (i, hex_frame(frame)), flush=True)
        if i + 1 < args.repeat:
            time.sleep(interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
