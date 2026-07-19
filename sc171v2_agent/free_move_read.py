#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unload servos so you can move the arm by hand, and stream joint angles.

Use this to discover real soft-limit envelopes vs JetArm maps in joint_protection.py.

  # on AidLux (CH340 userspace):
  python3 free_move_read.py
  python3 free_move_read.py --hz 5
  python3 free_move_read.py --reload   # re-torque when done (Ctrl+C then --reload)

Keys / lifecycle:
  - starts with UNLOAD (0x0B) on IDs 1..6  → free to move
  - polls READ_POSITION and prints pulse + deg vs soft limits
  - Ctrl+C exits (servos stay unloaded unless --reload)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jetarm_packet import (  # noqa: E402
    SUB_READ_POSITION,
    JetArmStreamParser,
    pack_load,
    pack_read_position,
    pack_unload,
    parse_bus_servo_report,
)
from joint_protection import (  # noqa: E402
    JMAX,
    JMIN,
    JOINT_MAPS,
    PULSE_SOFT_MAX,
    PULSE_SOFT_MIN,
    pos_to_deg,
)
from probe_read_positions import open_link  # noqa: E402

JOINT_NAMES = ["base", "shoulder", "elbow", "wrist_p", "wrist_r", "gripper"]


def _read_one(link, parser, sid, timeout_s=0.12):
    try:
        link.write(pack_read_position(sid))
    except Exception as e:
        return {"ok": False, "err": "tx:%s" % e}

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        chunk = link.read(64, timeout_ms=20)
        if not chunk:
            continue
        for fr in parser.feed(chunk):
            rep = parse_bus_servo_report(fr)
            if not rep:
                continue
            if int(rep["servo_id"]) != sid:
                continue
            if int(rep["sub_cmd"]) != SUB_READ_POSITION:
                continue
            ok = int(rep["success"]) == 0
            pulse = None
            deg = None
            if ok and len(rep["args"]) >= 2:
                pulse = rep["args"][0] | (rep["args"][1] << 8)
                deg = pos_to_deg(pulse, sid - 1)
            return {
                "ok": ok,
                "success": rep["success"],
                "pulse": pulse,
                "deg": deg,
            }
    return {"ok": False, "err": "timeout"}


def unload_all(link, ids):
    for sid in ids:
        try:
            link.write(pack_unload(sid))
            time.sleep(0.03)
        except Exception as e:
            print("[WARN] UNLOAD id=%s: %s" % (sid, e))
    print("[OK] UNLOAD sent → arm is free to move by hand")


def load_all(link, ids):
    for sid in ids:
        try:
            link.write(pack_load(sid))
            time.sleep(0.03)
        except Exception as e:
            print("[WARN] LOAD id=%s: %s" % (sid, e))
    print("[OK] LOAD sent → servos holding torque again")


def _limit_flag(deg, jmin, jmax, margin=2.0):
    if deg is None:
        return "?"
    if deg < jmin + margin:
        return "LO"
    if deg > jmax - margin:
        return "HI"
    return "ok"


def print_header():
    print("")
    print(
        "soft limits (deg) + pulse band [%d..%d] from joint_protection.py:"
        % (PULSE_SOFT_MIN, PULSE_SOFT_MAX)
    )
    for i, name in enumerate(JOINT_NAMES):
        m = JOINT_MAPS[i]
        print(
            "  j%d %-8s  soft=[%7.1f .. %7.1f]  map mid_pulse=%g -> amid=%g°  "
            "alo/ahi=%g/%g"
            % (i + 1, name, JMIN[i], JMAX[i], m[2], m[5], m[3], m[4])
        )
    print("")
    print(
        "note: web 3D uses the same degrees array [j1..j6] as MQTT actual[]; "
        "pulse↔deg uses JOINT_MAPS (shoulder/wrist_p mid≈-90°, not 0°)."
    )
    print("Ctrl+C to stop. Servos stay UNLOADED unless you pass --reload.")
    print("")


def format_row(results):
    parts = []
    for sid in range(1, 7):
        r = results.get(sid) or {}
        name = JOINT_NAMES[sid - 1]
        if not r.get("ok"):
            parts.append("%s:OFF" % name)
            continue
        deg = r.get("deg")
        pulse = r.get("pulse")
        flag = _limit_flag(deg, JMIN[sid - 1], JMAX[sid - 1])
        parts.append(
            "%s:%6.1f°(%4s)%s"
            % (name, deg if deg is not None else 0.0, pulse if pulse is not None else "-", flag)
        )
    return " | ".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Free-move + continuous joint read")
    ap.add_argument("--port", default="", help="serial port; empty = CH340 pyusb")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--hz", type=float, default=4.0, help="poll rate")
    ap.add_argument(
        "--ids",
        default="1,2,3,4,5,6",
        help="comma servo ids to unload/read",
    )
    ap.add_argument(
        "--reload",
        action="store_true",
        help="LOAD (hold) instead of UNLOAD, then exit after one read",
    )
    ap.add_argument(
        "--no-unload",
        action="store_true",
        help="do not send UNLOAD (read-only while bridge/other holds)",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="single sample then exit",
    )
    args = ap.parse_args()

    ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    period = 1.0 / max(0.2, float(args.hz))

    try:
        link = open_link(args.port, args.baud)
    except Exception as e:
        print("[FAIL] open:", e)
        return 1

    parser = JetArmStreamParser()
    try:
        if args.reload:
            load_all(link, ids)
            args.once = True
        elif not args.no_unload:
            unload_all(link, ids)

        print_header()
        n = 0
        while True:
            t0 = time.time()
            results = {}
            for sid in ids:
                results[sid] = _read_one(link, parser, sid)
            n += 1
            print("[%s] %s" % (time.strftime("%H:%M:%S"), format_row(results)))

            # compact CSV-ish line for logging
            degs = []
            pulses = []
            for sid in range(1, 7):
                r = results.get(sid) or {}
                degs.append(
                    "%.2f" % r["deg"] if r.get("ok") and r.get("deg") is not None else ""
                )
                pulses.append(
                    str(r["pulse"]) if r.get("ok") and r.get("pulse") is not None else ""
                )
            if n == 1 or args.once:
                print("# csv deg:   " + ",".join(degs))
                print("# csv pulse: " + ",".join(pulses))

            if args.once:
                break
            dt = time.time() - t0
            time.sleep(max(0.0, period - dt))
    except KeyboardInterrupt:
        print("\n[STOP] interrupted (servos still unloaded unless you --reload)")
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
