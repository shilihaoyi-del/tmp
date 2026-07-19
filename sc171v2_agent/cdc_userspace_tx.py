#!/usr/bin/env python3
"""Userspace CDC ACM TX/RX for WCH 1a86:55d4 when kernel cdc_acm is unavailable."""
from __future__ import annotations

import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("NEED: pip install pyusb", flush=True)
    sys.exit(2)

VID, PID = 0x1A86, 0x55D4


def main() -> int:
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("device 1a86:55d4 not found", flush=True)
        return 1

    print("found:", hex(dev.idVendor), hex(dev.idProduct), flush=True)
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception as e:
        print("detach0:", e, flush=True)
    try:
        if dev.is_kernel_driver_active(1):
            dev.detach_kernel_driver(1)
    except Exception as e:
        print("detach1:", e, flush=True)

    # CDC: IF0 comm, IF1 data
    usb.util.claim_interface(dev, 0)
    usb.util.claim_interface(dev, 1)

    # find bulk endpoints on interface 1
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
    print("ep_out", None if ep_out is None else hex(ep_out.bEndpointAddress), flush=True)
    print("ep_in", None if ep_in is None else hex(ep_in.bEndpointAddress), flush=True)
    if ep_out is None:
        print("no OUT endpoint", flush=True)
        return 1

    payload = b"SC171V2_CDC_TEST\r\n"
    written = ep_out.write(payload, timeout=2000)
    print("TX bytes:", written, "data:", payload, flush=True)

    if ep_in is not None:
        try:
            data = ep_in.read(64, timeout=1000)
            print("RX:", bytes(data), flush=True)
        except usb.core.USBError as e:
            print("RX timeout/err (ok if device silent):", e, flush=True)

    usb.util.release_interface(dev, 1)
    usb.util.release_interface(dev, 0)
    print("OK userspace CDC TX done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
