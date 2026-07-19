#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot: open USB CDC @ 1Mbps, LOAD + read positions ID1..6 (JetArm protocol)."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jetarm_packet import (  # noqa: E402
    SUB_READ_POSITION,
    JetArmStreamParser,
    hex_frame,
    pack_load,
    pack_read_position,
    parse_bus_servo_report,
)
from joint_protection import pos_to_deg  # noqa: E402


class Link(object):
    def write(self, data):
        raise NotImplementedError

    def read(self, n=64, timeout_ms=40):
        raise NotImplementedError

    def close(self):
        pass


class SerialLink(Link):
    def __init__(self, port, baud):
        import serial

        self.ser = serial.Serial(port, baud, timeout=0.04)
        # flush
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        print("[OK] serial %s @ %s" % (port, baud))

    def write(self, data):
        self.ser.write(data)
        self.ser.flush()

    def read(self, n=64, timeout_ms=40):
        self.ser.timeout = timeout_ms / 1000.0
        return self.ser.read(n) or b""

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class PyusbLink(Link):
    def __init__(self, baud=1000000, vid=0x1A86, pid=0x55D4):
        import struct
        import usb.core
        import usb.util

        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise RuntimeError("USB %04x:%04x not found" % (vid, pid))
        for i in (0, 1):
            try:
                if self.dev.is_kernel_driver_active(i):
                    self.dev.detach_kernel_driver(i)
            except Exception:
                pass
        usb.util.claim_interface(self.dev, 0)
        usb.util.claim_interface(self.dev, 1)
        cfg = self.dev.get_active_configuration()
        intf = cfg[(1, 0)]
        self.ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        self.ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN,
        )
        if self.ep_out is None or self.ep_in is None:
            raise RuntimeError("missing bulk endpoints")
        line_coding = struct.pack("<IBBB", baud, 0, 0, 8)
        self.dev.ctrl_transfer(0x21, 0x20, 0, 0, line_coding, timeout=1000)
        self.dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, timeout=1000)
        print(
            "[OK] pyusb %04x:%04x baud=%s"
            % (vid, pid, baud)
        )

    def write(self, data):
        self.ep_out.write(data, timeout=1000)

    def read(self, n=64, timeout_ms=40):
        try:
            return bytes(self.ep_in.read(n, timeout=timeout_ms))
        except Exception:
            return b""


class Ch340Link(Link):
    def __init__(self, baud):
        from ch340_pyusb import Ch340Serial

        self._s = Ch340Serial(baud)

    def write(self, data):
        self._s.write(data)

    def read(self, n=64, timeout_ms=40):
        return self._s.read(n, timeout_ms)

    def close(self):
        self._s.close()


def open_link(port="", baud=1000000):
    errors = []
    # On AidLux, CH340 often has no /dev/ttyUSB* — use userspace first
    if not port:
        try:
            return Ch340Link(baud)
        except Exception as e:
            errors.append("ch340_pyusb: %s" % e)
    candidates = []
    if port:
        candidates.append(port)
    candidates.extend(["/dev/ttyUSB0", "/dev/ttyACM0"])
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            return SerialLink(p, baud)
        except Exception as e:
            errors.append("%s: %s" % (p, e))
    if not port:
        for pid in (0x55D4,):
            try:
                return PyusbLink(baud=baud, pid=pid)
            except Exception as e:
                errors.append("pyusb 1a86:%04x: %s" % (pid, e))
    detail = "; ".join(errors) if errors else "no candidates"
    hint = ""
    if any("Errno 6" in e or "No such device" in e for e in errors):
        hint = (
            " | hint: /dev/ttyACM* is a stale node — unplug/replug JetArm Type-C "
            "(expect lsusb 1a86:7523 CH340 or a live ttyACM/ttyUSB)"
        )
    elif any("CH340" in e and "not found" in e for e in errors):
        hint = (
            " | hint: no USB serial seen — check Type-C to SC171, then: lsusb | grep -i 1a86"
        )
    raise RuntimeError("no link: %s%s" % (detail, hint))


def probe_once(link):
    parser = JetArmStreamParser()
    results = {}

    for sid in range(1, 7):
        try:
            link.write(pack_load(sid))
            time.sleep(0.02)
        except Exception as e:
            print("[WARN] LOAD id=%s: %s" % (sid, e))

    for sid in range(1, 7):
        req = pack_read_position(sid)
        print("[TX] id=%s %s" % (sid, hex_frame(req)))
        try:
            link.write(req)
        except Exception as e:
            print("[FAIL] TX id=%s: %s" % (sid, e))
            results[sid] = {"ok": False, "err": str(e)}
            continue

        deadline = time.time() + 0.4
        got = None
        raw_all = bytearray()
        while time.time() < deadline and got is None:
            chunk = link.read(64, timeout_ms=50)
            if not chunk:
                continue
            raw_all.extend(chunk)
            for fr in parser.feed(chunk):
                rep = parse_bus_servo_report(fr)
                if not rep:
                    continue
                if int(rep["servo_id"]) != sid:
                    continue
                if int(rep["sub_cmd"]) != SUB_READ_POSITION:
                    continue
                ok = int(rep["success"]) == 0
                pos = None
                deg = None
                if ok and len(rep["args"]) >= 2:
                    pos = rep["args"][0] | (rep["args"][1] << 8)
                    deg = pos_to_deg(pos, sid - 1)
                got = {
                    "ok": ok,
                    "success": rep["success"],
                    "pulse": pos,
                    "deg": None if deg is None else round(deg, 2),
                    "hex": hex_frame(rep.get("raw") or b""),
                }
                break
        if got is None:
            results[sid] = {"ok": False, "err": "timeout/no reply"}
            print(
                "[RX] id=%s NO REPLY raw=%s"
                % (sid, hex_frame(bytes(raw_all)) if raw_all else "empty")
            )
        else:
            results[sid] = got
            print(
                "[RX] id=%s ok=%s pulse=%s deg=%s %s"
                % (sid, got["ok"], got.get("pulse"), got.get("deg"), got.get("hex"))
            )
    return results


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="")
    ap.add_argument("--baud", type=int, default=1000000)
    args = ap.parse_args()

    try:
        link = open_link(args.port, args.baud)
    except Exception as e:
        print("[FAIL] open:", e)
        return 1

    try:
        results = probe_once(link)
    finally:
        link.close()

    print("===== SUMMARY baud=%s =====" % args.baud)
    online = []
    for sid in range(1, 7):
        r = results.get(sid) or {}
        flag = "ONLINE" if r.get("ok") else "OFFLINE"
        print(
            "ID%s %-7s pulse=%s deg=%s"
            % (sid, flag, r.get("pulse"), r.get("deg"))
        )
        if r.get("ok"):
            online.append(sid)
    print("online_ids=%s count=%s/6" % (online, len(online)))
    return 0 if online else 2


if __name__ == "__main__":
    sys.exit(main())
