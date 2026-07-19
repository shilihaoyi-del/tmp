#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe each Lobot bus servo (IDs 1..6): TX POS_READ, wait reply, report missing."""

from __future__ import annotations

import struct
import sys
import time

CMD_POS_READ = 28
CMD_MOVE = 1
SERVO_IDS = [1, 2, 3, 4, 5, 6]


def checksum(body_wo_chk):
    return (~sum(body_wo_chk[2:])) & 0xFF


def pack_read_pos(sid):
    body = bytes([0x55, 0x55, sid & 0xFF, 3, CMD_POS_READ])
    return body + bytes([checksum(body)])


def pack_move(sid, pos, time_ms=400):
    pos = max(0, min(1000, int(pos)))
    t = max(0, min(30000, int(time_ms)))
    body = bytes(
        [
            0x55,
            0x55,
            sid & 0xFF,
            7,
            CMD_MOVE,
            pos & 0xFF,
            (pos >> 8) & 0xFF,
            t & 0xFF,
            (t >> 8) & 0xFF,
        ]
    )
    return body + bytes([checksum(body)])


def hexb(b):
    return " ".join("%02X" % x for x in b)


def parse_lobot_frames(buf):
    """Yield dicts for valid Lobot frames in buffer."""
    i = 0
    out = []
    while i + 6 <= len(buf):
        if buf[i] != 0x55 or buf[i + 1] != 0x55:
            i += 1
            continue
        if i + 4 > len(buf):
            break
        sid = buf[i + 2]
        length = buf[i + 3]
        # Length = Cmd + Params + Checksum; total frame = 2 header + 1 id + 1 len + length
        # wait: protocol says Length + 3 = packet length from header to checksum
        # Length equals data to send including itself: Cmd+Params+Checksum count = Length
        # Frame size = 2 (55 55) + 1 (ID) + Length  where Length includes Length byte? 
        # Table: Length = nparam + 3 (Cmd + Params + Checksum)
        # Total = 2 + 1 + 1 + (Length-1)? Actually: bytes after dual header: ID, Length, then (Length-1) more? 
        # Example move: 55 55 01 07 01 F4 01 E8 03 16 -> after header: ID,Len,Cmd,4params,chk = 1+1+1+4+1=8, Length=7 means Cmd+params+chk=7
        # So payload after Length byte is Length bytes? No: Length counts Cmd+Params+Checksum = 7, and Length field itself is separate.
        # Frame = [55 55][ID][Length][Cmd][Prms...][CHK] with len(Cmd+Prms+CHK)=Length
        # total = 2 + 2 + Length
        total = 2 + 2 + length
        if i + total > len(buf):
            break
        frame = bytes(buf[i : i + total])
        expect = checksum(frame[:-1])
        if frame[-1] != expect:
            i += 1
            continue
        cmd = frame[4]
        params = frame[5:-1]
        out.append({"id": sid, "cmd": cmd, "params": params, "raw": frame})
        i += total
    return out


def open_usb():
    import usb.core
    import usb.util

    dev = usb.core.find(idVendor=0x1A86, idProduct=0x55D4)
    if dev is None:
        raise RuntimeError("USB 1a86:55d4 not found")
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass
    try:
        if dev.is_kernel_driver_active(1):
            dev.detach_kernel_driver(1)
    except Exception:
        pass
    try:
        usb.util.claim_interface(dev, 0)
    except Exception:
        pass
    try:
        usb.util.claim_interface(dev, 1)
    except Exception:
        pass
    # 115200 8N1 + DTR/RTS
    line = struct.pack("<IBBB", 115200, 0, 0, 8)
    try:
        dev.ctrl_transfer(0x21, 0x20, 0, 0, line, timeout=1000)
        dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, timeout=1000)
    except Exception as e:
        print("[WARN] line_coding:", e)
    ep_out = ep_in = None
    for cfg in dev:
        for intf in cfg:
            for ep in intf:
                if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT:
                    if ep_out is None:
                        ep_out = ep
                else:
                    if ep_in is None:
                        ep_in = ep
    if ep_out is None:
        raise RuntimeError("no OUT ep")
    return dev, ep_out, ep_in


def drain(ep_in, ms=80):
    if ep_in is None:
        return b""
    buf = b""
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        try:
            chunk = bytes(ep_in.read(64, timeout=20))
            if chunk:
                buf += chunk
        except Exception:
            pass
    return buf


def main():
    print("=== Lobot per-servo probe (POS_READ cmd=28) ===")
    print("baud=115200  IDs=%s" % SERVO_IDS)
    dev, ep_out, ep_in = open_usb()
    print("[OK] USB open ep_out=%s ep_in=%s" % (hex(ep_out.bEndpointAddress), None if ep_in is None else hex(ep_in.bEndpointAddress)))

    # drain noise (AA55 STATUS flood etc.)
    junk = drain(ep_in, 150)
    print("[..] drained %s bytes before probe" % len(junk))

    results = []
    for sid in SERVO_IDS:
        # slight nudge then read — write has no ACK; read proves presence
        nudge_pos = 500 + (sid * 8)  # small unique offset around mid
        move = pack_move(sid, nudge_pos, 350)
        rd = pack_read_pos(sid)
        print("")
        print("--- ID %s ---" % sid)
        print("TX MOVE  %s" % hexb(move))
        ep_out.write(move, timeout=1000)
        time.sleep(0.05)
        drain(ep_in, 40)  # discard bus noise after write

        print("TX READ  %s" % hexb(rd))
        t0 = time.time()
        ep_out.write(rd, timeout=1000)

        # half-duplex: wait then read reply window
        time.sleep(0.02)
        rx = b""
        deadline = time.time() + 0.35
        while time.time() < deadline:
            try:
                chunk = bytes(ep_in.read(64, timeout=30))
                if chunk:
                    rx += chunk
            except Exception:
                pass

        dt = round((time.time() - t0) * 1000.0, 1)
        frames = parse_lobot_frames(rx)
        hit = None
        for fr in frames:
            if fr["id"] == sid and fr["cmd"] == CMD_POS_READ and len(fr["params"]) >= 2:
                pos = fr["params"][0] | (fr["params"][1] << 8)
                if pos > 32767:
                    pos -= 65536
                hit = {"pos": pos, "hex": hexb(fr["raw"]), "dt_ms": dt}
                break

        if hit:
            print("RX OK    pos=%s  hex=%s  dt_ms=%s" % (hit["pos"], hit["hex"], hit["dt_ms"]))
            results.append({"id": sid, "ok": True, **hit})
        else:
            print("RX MISS  raw_len=%s raw=%s dt_ms=%s" % (len(rx), hexb(rx[:40]), dt))
            # show any lobot frames seen
            for fr in frames:
                print("  other_frame id=%s cmd=%s hex=%s" % (fr["id"], fr["cmd"], hexb(fr["raw"])))
            results.append({"id": sid, "ok": False, "raw_len": len(rx), "dt_ms": dt})

        time.sleep(0.08)

    print("")
    print("========== SUMMARY ==========")
    ok_ids = [r["id"] for r in results if r["ok"]]
    miss_ids = [r["id"] for r in results if not r["ok"]]
    for r in results:
        if r["ok"]:
            print("ID %s: PASS  pos=%s" % (r["id"], r["pos"]))
        else:
            print("ID %s: FAIL  no POS_READ reply" % r["id"])
    print("---")
    print("收到应答: %s" % (ok_ids if ok_ids else "无"))
    print("未收到:   %s" % (miss_ids if miss_ids else "无"))
    print("OVERALL: %s" % ("ALL PASS" if not miss_ids else "PARTIAL/FAIL"))

    try:
        import usb.util

        usb.util.release_interface(dev, 1)
        usb.util.release_interface(dev, 0)
    except Exception:
        pass
    return 0 if not miss_ids else 1


if __name__ == "__main__":
    sys.exit(main())
