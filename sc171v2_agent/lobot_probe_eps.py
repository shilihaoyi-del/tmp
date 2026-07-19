#!/usr/bin/env python3
import struct
import time
import usb.core
import usb.util

def ck(b):
    return (~sum(b[2:])) & 0xFF

def pack_read(sid):
    body = bytes([0x55, 0x55, sid, 3, 28])
    return body + bytes([ck(body)])

def pack_move(sid, pos=520, t=300):
    body = bytes([0x55, 0x55, sid, 7, 1, pos & 0xFF, (pos >> 8) & 0xFF, t & 0xFF, (t >> 8) & 0xFF])
    return body + bytes([ck(body)])

dev = usb.core.find(idVendor=0x1A86, idProduct=0x55D4)
if not dev:
    raise SystemExit("no device")
for i in (0, 1):
    try:
        if dev.is_kernel_driver_active(i):
            dev.detach_kernel_driver(i)
    except Exception:
        pass
    try:
        usb.util.claim_interface(dev, i)
    except Exception as e:
        print("claim", i, e)

line = struct.pack("<IBBB", 115200, 0, 0, 8)
dev.ctrl_transfer(0x21, 0x20, 0, 0, line, timeout=1000)
dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, timeout=1000)

eps_out, eps_in = [], []
for cfg in dev:
    print("cfg", cfg.bConfigurationValue)
    for intf in cfg:
        print(" intf", intf.bInterfaceNumber, "class", intf.bInterfaceClass)
        for ep in intf:
            print("  ep", hex(ep.bEndpointAddress), "attr", ep.bmAttributes)
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT:
                eps_out.append(ep)
            else:
                eps_in.append(ep)

print("OUT", [hex(e.bEndpointAddress) for e in eps_out])
print("IN", [hex(e.bEndpointAddress) for e in eps_in])
ep_out = eps_out[0]

for ep in eps_in:
    got = b""
    for _ in range(8):
        try:
            got += bytes(ep.read(64, timeout=25))
        except Exception:
            break
    print("drain", hex(ep.bEndpointAddress), len(got), got[:24].hex() if got else "")

results = []
for sid in range(1, 7):
    mv, rd = pack_move(sid), pack_read(sid)
    print("\n=== ID %s ===" % sid)
    print("TX MOVE", mv.hex())
    print("TX READ", rd.hex())
    ep_out.write(mv, timeout=1000)
    time.sleep(0.04)
    for ep in eps_in:
        try:
            ep.read(64, timeout=20)
        except Exception:
            pass
    ep_out.write(rd, timeout=1000)
    time.sleep(0.02)
    rx = b""
    t0 = time.time()
    while time.time() - t0 < 0.45:
        for ep in eps_in:
            try:
                c = bytes(ep.read(64, timeout=25))
                if c:
                    rx += c
                    print(" RX", hex(ep.bEndpointAddress), c.hex())
            except Exception:
                pass
    ok = False
    # look for 55 55 sid 05 1C
    i = 0
    while i + 8 <= len(rx):
        if rx[i] == 0x55 and rx[i + 1] == 0x55 and rx[i + 2] == sid and rx[i + 4] == 28:
            ok = True
            print(" HIT", rx[i : i + 8].hex())
            break
        i += 1
    results.append((sid, ok, len(rx)))
    if not ok:
        print(" MISS len=%s" % len(rx))

print("\nSUMMARY")
for sid, ok, n in results:
    print("ID %s: %s (rx_bytes=%s)" % (sid, "PASS" if ok else "FAIL", n))
miss = [sid for sid, ok, _ in results if not ok]
print("未收到:", miss if miss else "无")
