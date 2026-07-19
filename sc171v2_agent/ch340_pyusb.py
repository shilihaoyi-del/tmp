#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal CH340/CH341 userspace serial via pyusb (vendor class 1a86:7523).

Baud init follows Linux drivers/usb/serial/ch341.c (CH341_BAUDBASE_FACTOR).
"""

from __future__ import annotations

import usb.core
import usb.util

VID = 0x1A86
PID = 0x7523

CH341_REQ_READ_VERSION = 0x5F
CH341_REQ_WRITE_REG = 0x9A
CH341_REQ_READ_REG = 0x95
CH341_REQ_SERIAL_INIT = 0xA1
CH341_REQ_MODEM_CTRL = 0xA4

CH341_BAUDBASE_FACTOR = 1532620800
CH341_BAUDBASE_DIVMAX = 3

CH341_BITS_DATA8 = 0x03
CH341_LCR_ENABLE_RX = 0x80
CH341_LCR_ENABLE_TX = 0x40


class Ch340Serial(object):
    def __init__(self, baud: int = 1000000):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("CH340 1a86:7523 not found")
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except Exception:
            pass
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self.ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        self.ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN
            and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK,
        )
        if self.ep_out is None or self.ep_in is None:
            raise RuntimeError("CH340 bulk endpoints missing")
        self._init_uart(baud)
        # drain
        for _ in range(5):
            if not self.read(64, 20):
                break
        print(
            "[OK] CH340 pyusb baud=%s out=%s in=%s"
            % (baud, hex(self.ep_out.bEndpointAddress), hex(self.ep_in.bEndpointAddress))
        )

    def _init_uart(self, baud: int):
        try:
            ver = self.dev.ctrl_transfer(0xC0, CH341_REQ_READ_VERSION, 0, 0, 2, timeout=1000)
            print("[CH340] version=%s" % list(ver))
        except Exception as e:
            print("[CH340] version read warn: %s" % e)

        self.dev.ctrl_transfer(0x40, CH341_REQ_SERIAL_INIT, 0, 0, 0, timeout=1000)

        factor = CH341_BAUDBASE_FACTOR // int(baud)
        divisor = CH341_BAUDBASE_DIVMAX
        while factor > 0xFFF0 and divisor > 0:
            factor >>= 3
            divisor -= 1
        factor = 0x10000 - factor
        a1 = (factor & 0xFF00) | divisor
        a2 = factor & 0xFF
        # reg 0x1312 = divisor/factor high, 0x0f2c low (as in kernel)
        self.dev.ctrl_transfer(0x40, CH341_REQ_WRITE_REG, 0x1312, a1, 0, timeout=1000)
        self.dev.ctrl_transfer(0x40, CH341_REQ_WRITE_REG, 0x0F2C, a2, 0, timeout=1000)

        lcr = CH341_LCR_ENABLE_RX | CH341_LCR_ENABLE_TX | CH341_BITS_DATA8
        self.dev.ctrl_transfer(0x40, CH341_REQ_WRITE_REG, 0x2518, lcr, 0, timeout=1000)
        # DTR + RTS assert (active low bits cleared in modem ctrl)
        self.dev.ctrl_transfer(0x40, CH341_REQ_MODEM_CTRL, ~((1 << 5) | (1 << 6)) & 0xFF, 0, 0, timeout=1000)

    def write(self, data: bytes):
        wrote = self.ep_out.write(data, timeout=2000)
        if wrote != len(data):
            raise IOError("short write %s/%s" % (wrote, len(data)))

    def read(self, n: int = 64, timeout_ms: int = 50) -> bytes:
        try:
            return bytes(self.ep_in.read(n, timeout=timeout_ms))
        except usb.core.USBError:
            return b""

    def close(self):
        try:
            usb.util.release_interface(self.dev, 0)
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
