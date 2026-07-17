#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SC171V2 servo bridge with TX+RX hop tracing.

Hops:
  H1-MQTT  cloud -> module command
  H2-PACK  pack 20B UART frame
  H3-UART  USB CDC TX to STM32/servo link
  H4-RX    USB CDC RX valid protocol frame from STM32
  H5-UP    publish status/trace back to cloud
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("NEED paho-mqtt", flush=True)
    sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uart_protocol import (  # noqa: E402
    CMD_ESTOP,
    CMD_HEARTBEAT,
    CMD_HOLD,
    CMD_JOINT,
    CMD_STATUS,
    FLAG_ESTOP,
    FLAG_HOLD,
    FrameStreamParser,
    hex_frame,
    pack_frame,
    pack_status_reply,
)
from hiwonder_servo import hex_frames, pack_arm_joints_deg  # noqa: E402

TOPIC_CMD = "arm/device/cmd"
TOPIC_MODE = "arm/device/mode"
TOPIC_STATUS = "arm/device/status"
TOPIC_HB = "arm/device/heartbeat"
TOPIC_TRACE = "arm/device/trace"

JOINT_MIN = [-180.0, -90.0, -135.0, -90.0, -180.0, 0.0]
JOINT_MAX = [180.0, 90.0, 135.0, 90.0, 180.0, 90.0]


def clamp_joints(joints):
    out = []
    for i in range(6):
        v = float(joints[i]) if i < len(joints) else 0.0
        out.append(max(JOINT_MIN[i], min(JOINT_MAX[i], v)))
    return out


def now_ms():
    return int(time.time() * 1000)


def log(msg):
    print(msg, flush=True)


class UartLink(object):
    """Bidirectional USB-CDC / serial link."""

    def __init__(self, port):
        self.port = port
        self._fd = None
        self._ser = None
        self._usb = None
        self._ep_out = None
        self._ep_in = None
        self.mode = "none"
        self.last_error = ""
        self.tx_ok = 0
        self.tx_fail = 0
        self.rx_bytes = 0
        self._open()

    def _open_pyusb(self):
        try:
            import usb.core
            import usb.util

            dev = usb.core.find(idVendor=0x1A86, idProduct=0x55D4)
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
                raise RuntimeError("no bulk OUT")
            self._usb = dev
            self._ep_out = ep_out
            self._ep_in = ep_in
            # Critical: set CDC ACM line coding to 115200 8N1 (was missing → STM32/servo bus garbage)
            try:
                import struct

                line_coding = struct.pack("<IBBB", 115200, 0, 0, 8)  # baud, 1 stop, no parity, 8 bits
                dev.ctrl_transfer(0x21, 0x20, 0, 0, line_coding, timeout=1000)
                dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, timeout=1000)  # DTR|RTS
                log("[H0-OPEN] CDC line_coding=115200 8N1 DTR/RTS on")
            except Exception as e:
                log("[H0-OPEN] CDC line_coding warn: %s" % e)
            self.mode = "pyusb:1a86:55d4"
            log("[H0-OPEN] link=%s ep_out=%s ep_in=%s" % (
                self.mode,
                hex(ep_out.bEndpointAddress),
                None if ep_in is None else hex(ep_in.bEndpointAddress),
            ))
            return True
        except Exception as e:
            self.last_error = "pyusb fail: %s" % e
            log("[H0-OPEN] pyusb fail: %s" % e)
            return False

    def _open(self):
        prefer = (self.port or "").strip().lower()
        if prefer in ("", "auto", "pyusb", "usb"):
            if self._open_pyusb():
                return
        if self.port and os.path.exists(self.port):
            try:
                self._fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                self.mode = "pty:%s" % self.port
                log("[H0-OPEN] link=%s" % self.mode)
                return
            except Exception as e:
                self.last_error = "pty open fail: %s" % e
        try:
            import serial

            self._ser = serial.Serial(self.port, 115200, timeout=0.05)
            self.mode = "serial:%s" % self.port
            log("[H0-OPEN] link=%s" % self.mode)
            return
        except Exception as e:
            self.last_error = "serial open fail: %s" % e
        if self._open_pyusb():
            return
        log("[H0-OPEN] FAILED: %s" % self.last_error)
        self.mode = "none"

    def write(self, frame):
        try:
            if self._fd is not None:
                n = os.write(self._fd, frame)
            elif self._ser is not None:
                n = self._ser.write(frame)
                self._ser.flush()
            elif self._ep_out is not None:
                n = self._ep_out.write(frame, timeout=1000)
            else:
                raise IOError("no link: %s" % self.last_error)
            if n != len(frame):
                raise IOError("short write %s/%s" % (n, len(frame)))
            self.tx_ok += 1
            return True, ""
        except Exception as e:
            self.tx_fail += 1
            self.last_error = str(e)
            try:
                self.close()
            except Exception:
                pass
            self._open()
            return False, self.last_error

    def read(self, max_bytes=64, timeout_ms=20):
        try:
            if self._fd is not None:
                try:
                    data = os.read(self._fd, max_bytes)
                    if data:
                        self.rx_bytes += len(data)
                    return data or b""
                except BlockingIOError:
                    return b""
            if self._ser is not None:
                n = self._ser.in_waiting
                if n <= 0:
                    return b""
                data = self._ser.read(min(n, max_bytes))
                self.rx_bytes += len(data)
                return data
            if self._ep_in is not None:
                try:
                    chunk = self._ep_in.read(max_bytes, timeout=timeout_ms)
                    data = bytes(chunk)
                    self.rx_bytes += len(data)
                    return data
                except Exception:
                    return b""
            return b""
        except Exception as e:
            self.last_error = "read fail: %s" % e
            return b""

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        if self._usb is not None:
            try:
                import usb.util

                usb.util.release_interface(self._usb, 1)
                usb.util.release_interface(self._usb, 0)
            except Exception:
                pass
            self._usb = None
            self._ep_out = None
            self._ep_in = None


class ServoBridge(object):
    def __init__(
        self,
        host,
        port,
        uart_port,
        client_id,
        carrier,
        hb_interval,
        echo_sim=False,
        drive="lobot",
        move_time_ms=500,
    ):
        self.host = host
        self.port = port
        self.carrier = carrier
        self.hb_interval = hb_interval
        self.echo_sim = echo_sim
        # drive: lobot = 幻尔 55 55 direct (servos move if USB on servo bus)
        #        aa55  = only SC171↔STM32 protocol (needs flashed STM32)
        #        both  = send both
        self.drive = (drive or "lobot").lower()
        self.move_time_ms = int(move_time_ms)
        self.link = UartLink(uart_port)
        self.parser = FrameStreamParser()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.connected = False
        self.seq = 0
        self.uart_seq = 0
        self.mode = "idle"
        self.estop = False
        self.target = [0.0] * 6
        self.actual = [0.0] * 6
        self.last_cmd_seq = 0
        self.recv_mqtt = 0
        self.tx_uart = 0
        self.rx_frames = 0
        self.rx_status = 0
        self.rx_garbage = 0
        self.last_rx_at = 0.0
        self.stm32_online = False
        self.last_hop = {}
        self._pending_rtt = None  # (uart_seq, t0, joints)

        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _pub(self, topic, payload, qos=0):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.client.publish(topic, body, qos=qos)

    def _trace(self, hop, **kw):
        info = {"hop": hop, "ts_ms": now_ms()}
        info.update(kw)
        self.last_hop = info
        log("[%s] %s" % (hop, json.dumps(kw, ensure_ascii=False)))
        if self.connected:
            try:
                self._pub(TOPIC_TRACE, info, qos=0)
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe([(TOPIC_CMD, 1), (TOPIC_MODE, 1)])
            log("[OK] MQTT %s:%s link=%s" % (self.host, self.port, self.link.mode))
            self._publish_hb()
            self._publish_status(force=True)
            self._trace(
                "H0-READY",
                mqtt=True,
                link=self.link.mode,
                echo_sim=self.echo_sim,
                drive=self.drive,
            )
        else:
            log("[ERR] mqtt rc=%s" % rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        log("[WARN] mqtt down rc=%s" % rc)

    def _forward_uart(self, joints, estop=False, hold=False, mqtt_seq=0):
        flags = 0
        cmd = CMD_JOINT
        if estop:
            flags |= FLAG_ESTOP
            cmd = CMD_ESTOP
        elif hold:
            flags |= FLAG_HOLD
            cmd = CMD_HOLD

        self.uart_seq = (self.uart_seq + 1) & 0xFF
        ok_any = False
        t0 = time.time()

        # --- AA55 path (STM32 firmware required for motion) ---
        if self.drive in ("aa55", "both") and not estop:
            frame = pack_frame(cmd, self.uart_seq, joints, flags)
            self._trace(
                "H2-PACK",
                mqtt_seq=mqtt_seq,
                uart_seq=self.uart_seq,
                cmd=cmd,
                flags=flags,
                joints=joints,
                protocol="aa55",
                hex=hex_frame(frame),
            )
            ok, err = self.link.write(frame)
            dt = (time.time() - t0) * 1000.0
            if ok:
                ok_any = True
                self.tx_uart += 1
                self._pending_rtt = (self.uart_seq, t0, list(joints))
                self._trace(
                    "H3-UART",
                    ok=True,
                    protocol="aa55",
                    bytes=len(frame),
                    sink=self.link.mode,
                    dt_ms=round(dt, 2),
                    tx_ok=self.link.tx_ok,
                )
                if self.echo_sim and cmd == CMD_JOINT:
                    echo = pack_status_reply(self.uart_seq, joints, moving=False)
                    self._handle_rx_bytes(echo, source="echo_sim")
            else:
                self._trace(
                    "H3-UART",
                    ok=False,
                    protocol="aa55",
                    err=err,
                    sink=self.link.mode,
                    dt_ms=round(dt, 2),
                )
        elif self.drive in ("aa55", "both") and estop:
            frame = pack_frame(CMD_ESTOP, self.uart_seq, joints, FLAG_ESTOP)
            ok, err = self.link.write(frame)
            ok_any = ok_any or ok
            self._trace("H3-UART", ok=ok, protocol="aa55", kind="estop", err=err)

        # --- Lobot 55 55 path (direct bus drive; USB must be on servo UART) ---
        if self.drive in ("lobot", "both") and cmd == CMD_JOINT and not estop:
            frames = pack_arm_joints_deg(joints, self.move_time_ms)
            self._trace(
                "H2-PACK",
                mqtt_seq=mqtt_seq,
                uart_seq=self.uart_seq,
                protocol="lobot",
                joints=joints,
                move_time_ms=self.move_time_ms,
                hex=hex_frames(frames),
            )
            lobot_ok = True
            n = 0
            for fr in frames:
                ok, err = self.link.write(fr)
                if not ok:
                    lobot_ok = False
                    self._trace("H3-UART", ok=False, protocol="lobot", err=err)
                    break
                n += len(fr)
                time.sleep(0.002)
            dt = (time.time() - t0) * 1000.0
            if lobot_ok:
                ok_any = True
                self.tx_uart += 1
                # Without STM32 STATUS, mirror target so cloud "actual" updates
                self.actual = list(joints)
                self._trace(
                    "H3-UART",
                    ok=True,
                    protocol="lobot",
                    bytes=n,
                    frames=len(frames),
                    sink=self.link.mode,
                    dt_ms=round(dt, 2),
                    note="direct_hiwonder_bus",
                )
                if self.echo_sim:
                    echo = pack_status_reply(self.uart_seq, joints, moving=False)
                    self._handle_rx_bytes(echo, source="echo_sim")
                else:
                    # Publish mirrored actual so UI shows motion command accepted
                    self._publish_status(force=True)

        return ok_any

    def _handle_rx_bytes(self, data, source="usb"):
        if not data:
            return
        # quick garbage meter: bytes that never form frames
        before = self.rx_frames
        frames = self.parser.feed(data)
        if not frames:
            self.rx_garbage += len(data)
            # occasionally show raw for diagnosis
            if self.rx_garbage % 200 < len(data):
                self._trace(
                    "H4-RX",
                    ok=False,
                    source=source,
                    raw_len=len(data),
                    raw_hex=hex_frame(data[:20]),
                    note="no_valid_frame_yet",
                    rx_bytes=self.link.rx_bytes,
                    rx_garbage=self.rx_garbage,
                )
            return

        for fr in frames:
            self.rx_frames += 1
            self.last_rx_at = time.time()
            self.stm32_online = True
            joints = fr["joints_deg"]
            rtt_ms = None
            if self._pending_rtt is not None:
                u_seq, t0, _ = self._pending_rtt
                if fr["cmd"] == CMD_STATUS:
                    rtt_ms = round((time.time() - t0) * 1000.0, 2)
                    self._pending_rtt = None
            self._trace(
                "H4-RX",
                ok=True,
                source=source,
                cmd=fr["cmd"],
                seq=fr["seq"],
                flags=fr["flags"],
                joints=joints,
                hex=hex_frame(fr["raw"]),
                rtt_ms=rtt_ms,
                rx_frames=self.rx_frames,
            )
            if fr["cmd"] == CMD_STATUS:
                self.rx_status += 1
                with self._lock:
                    self.actual = list(joints)
                self._publish_status()
                self._trace(
                    "H5-UP",
                    ok=True,
                    actual=list(joints),
                    rtt_ms=rtt_ms,
                    stm32_online=True,
                    rx_status=self.rx_status,
                )
            elif fr["cmd"] in (0x82, 0x83):  # ACK / FAULT
                self.stm32_online = True
                self._trace(
                    "H5-UP",
                    ok=True,
                    kind="ack" if fr["cmd"] == 0x82 else "fault",
                    seq=fr["seq"],
                    flags=fr["flags"],
                )

    def _rx_loop(self):
        while not self._stop.is_set():
            data = self.link.read(64, timeout_ms=30)
            if data:
                self._handle_rx_bytes(data, source="usb")
            else:
                # timeout STM32 online
                if self.stm32_online and (time.time() - self.last_rx_at) > 3.0:
                    self.stm32_online = False
                    self._trace("H4-RX", ok=False, note="stm32_timeout_3s")
                time.sleep(0.005)

    def _on_message(self, client, userdata, msg):
        t_mqtt = now_ms()
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            self._trace("H1-MQTT", ok=False, err="bad json: %s" % e)
            return

        with self._lock:
            self.recv_mqtt += 1
            if msg.topic == TOPIC_MODE:
                self.mode = str(payload.get("mode", self.mode))
                self.estop = bool(payload.get("estop", self.estop))
                self._trace("H1-MQTT", topic="mode", mode=self.mode, estop=self.estop)
                hold = self.mode in ("hold", "paused", "idle")
                self._forward_uart(self.target, estop=self.estop, hold=hold)
            elif msg.topic == TOPIC_CMD:
                self.last_cmd_seq = int(payload.get("seq", 0) or 0)
                self.mode = str(payload.get("mode", self.mode))
                self.estop = bool(payload.get("estop", False))
                target = payload.get("target")
                if isinstance(target, list) and len(target) >= 6:
                    self.target = clamp_joints([float(x) for x in target[:6]])
                self._trace(
                    "H1-MQTT",
                    topic="cmd",
                    seq=self.last_cmd_seq,
                    mode=self.mode,
                    estop=self.estop,
                    target=self.target,
                    age_ms=max(0, t_mqtt - int(payload.get("ts_ms", t_mqtt) or t_mqtt)),
                )
                hold = (not self.estop) and self.mode in ("hold", "paused", "idle")
                self._forward_uart(
                    self.target,
                    estop=self.estop,
                    hold=hold,
                    mqtt_seq=self.last_cmd_seq,
                )
            self._publish_status()

    def _publish_hb(self):
        self._pub(
            TOPIC_HB,
            {
                "ts_ms": now_ms(),
                "online": True,
                "module_id": "SC171V2",
                "carrier": self.carrier,
                "uart_mode": self.link.mode,
                "uart_tx_ok": self.link.tx_ok,
                "uart_rx_bytes": self.link.rx_bytes,
                "rx_frames": self.rx_frames,
                "rx_status": self.rx_status,
                "stm32_online": self.stm32_online,
            },
        )

    def _publish_status(self, force=False):
        with self._lock:
            self.seq += 1
            payload = {
                "seq": self.seq,
                "ts_ms": now_ms(),
                "online": True,
                "stm32_online": self.stm32_online,
                "mode": self.mode,
                "target": list(self.target),
                "actual": list(self.actual),
                "fault": "" if self.link.mode != "none" else "uart_down",
                "estop": self.estop,
                "carrier": self.carrier,
                "uart_mode": self.link.mode,
                "uart_tx_ok": self.link.tx_ok,
                "uart_rx_bytes": self.link.rx_bytes,
                "rx_frames": self.rx_frames,
                "rx_status": self.rx_status,
                "rx_garbage": self.rx_garbage,
                "last_hop": self.last_hop.get("hop", ""),
            }
        self._pub(TOPIC_STATUS, payload)
        if force:
            self._trace("H5-UP", boot=True, **{k: payload[k] for k in ("seq", "uart_mode", "stm32_online")})

    def start(self):
        log(
            "[..] mqtt://%s:%s link=%s echo_sim=%s drive=%s"
            % (self.host, self.port, self.link.mode, self.echo_sim, self.drive)
        )
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        rx = threading.Thread(target=self._rx_loop, name="uart-rx", daemon=True)
        rx.start()
        while not self._stop.wait(self.hb_interval):
            if not self.connected:
                continue
            self._publish_hb()
            with self._lock:
                joints = list(self.target)
                estop = self.estop
            # Only AA55 path needs UART heartbeat; Lobot direct drive skips (bus noise)
            if self.drive in ("aa55", "both"):
                self.uart_seq = (self.uart_seq + 1) & 0xFF
                cmd = CMD_ESTOP if estop else CMD_HEARTBEAT
                flags = FLAG_ESTOP if estop else 0
                frame = pack_frame(cmd, self.uart_seq, joints, flags)
                ok, err = self.link.write(frame)
                if not ok:
                    self._trace("H3-UART", ok=False, kind="heartbeat", protocol="aa55", err=err)

    def stop(self):
        self._stop.set()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        self.link.close()
        log(
            "[STOP] mqtt_rx=%s tx=%s rx_frames=%s rx_status=%s garbage=%s"
            % (self.recv_mqtt, self.tx_uart, self.rx_frames, self.rx_status, self.rx_garbage)
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="121.41.67.80")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--uart", default="pyusb")
    ap.add_argument("--client-id", default="sc171v2-servo-bridge")
    ap.add_argument("--carrier", default="Wi-Fi")
    ap.add_argument("--hb-interval", type=float, default=1.0)
    ap.add_argument(
        "--echo-sim",
        action="store_true",
        help="simulate STM32 STATUS echo locally (path self-test)",
    )
    ap.add_argument(
        "--drive",
        default="lobot",
        choices=["lobot", "aa55", "both"],
        help="lobot=幻尔直驱(默认,舵机要动); aa55=仅STM32协议; both=两者都发",
    )
    ap.add_argument("--move-time-ms", type=int, default=500, help="Lobot move time ms")
    args = ap.parse_args()
    bridge = ServoBridge(
        args.host,
        args.port,
        args.uart,
        args.client_id,
        args.carrier,
        args.hb_interval,
        args.echo_sim,
        args.drive,
        args.move_time_ms,
    )

    def _sig(s, f):
        bridge.stop()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    try:
        bridge.start()
    except Exception as e:
        log("[FATAL] %s" % e)
        bridge.stop()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
