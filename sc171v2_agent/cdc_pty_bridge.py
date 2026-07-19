#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CDC ACM PTY bridge for AidLux when kernel cdc_acm cannot load
(WCH 1a86:55d4 / CH343 CDC mode).

Creates a PTY that apps can open like a serial port, e.g.:
  /tmp/ttyACM_sc171 -> /dev/pts/N
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("NEED: pip3 install pyusb", file=sys.stderr, flush=True)
    sys.exit(2)

VID, PID = 0x1A86, 0x55D4
LINK = "/tmp/ttyACM_sc171"


def open_cdc():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise RuntimeError("USB 1a86:55d4 not found")
    for i in (0, 1):
        try:
            if dev.is_kernel_driver_active(i):
                dev.detach_kernel_driver(i)
        except Exception:
            pass
    usb.util.claim_interface(dev, 0)
    usb.util.claim_interface(dev, 1)
    cfg = dev.get_active_configuration()
    intf = cfg[(1, 0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_OUT,
    )
    ep_in = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_IN,
    )
    if ep_out is None:
        raise RuntimeError("no BULK OUT endpoint")
    return dev, ep_out, ep_in


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--link", default=LINK)
    ap.add_argument("--baud-note", default="115200", help="informational only")
    args = ap.parse_args()

    print("[..] open CDC device", flush=True)
    dev, ep_out, ep_in = open_cdc()
    print(
        "[OK] CDC claimed ep_out=%s ep_in=%s"
        % (
            hex(ep_out.bEndpointAddress),
            None if ep_in is None else hex(ep_in.bEndpointAddress),
        ),
        flush=True,
    )

    master, slave = os.openpty()
    slave_name = os.ttyname(slave)
    try:
        import termios
        import tty

        tty.setraw(slave)
        attrs = termios.tcgetattr(slave)
        attrs[3] = attrs[3] & ~(termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ICANON)
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        attrs_m = termios.tcgetattr(master)
        attrs_m[3] = attrs_m[3] & ~(termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ICANON)
        termios.tcsetattr(master, termios.TCSANOW, attrs_m)
    except Exception as e:
        print("[WARN] termios raw:", e, flush=True)
    try:
        os.chmod(slave_name, 0o666)
    except Exception as e:
        print("[WARN] chmod pty:", e, flush=True)
    try:
        if os.path.islink(args.link) or os.path.exists(args.link):
            os.unlink(args.link)
        os.symlink(slave_name, args.link)
    except Exception as e:
        print("[WARN] symlink:", e, flush=True)

    print("[OK] PTY ready: %s  (symlink %s)" % (slave_name, args.link), flush=True)
    print("[OK] use:  screen %s 115200   or   pyserial %s" % (args.link, args.link), flush=True)

    try:
        while True:
            rlist = [master]
            readable, _, _ = select.select(rlist, [], [], 0.05)
            if master in readable:
                data = os.read(master, 512)
                if data:
                    ep_out.write(data, timeout=1000)
                    print("[TX] %r" % data, flush=True)
            if ep_in is not None:
                try:
                    chunk = ep_in.read(64, timeout=50)
                    if chunk:
                        b = bytes(chunk)
                        os.write(master, b)
                        print("[RX] %r" % b, flush=True)
                except usb.core.USBError:
                    pass
    except KeyboardInterrupt:
        print("[STOP]", flush=True)
    finally:
        try:
            usb.util.release_interface(dev, 1)
            usb.util.release_interface(dev, 0)
        except Exception:
            pass
        try:
            os.close(master)
            os.close(slave)
        except Exception:
            pass
        try:
            if os.path.islink(args.link):
                os.unlink(args.link)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
