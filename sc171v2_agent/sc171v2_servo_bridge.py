#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SC171V2 servo bridge — JetArm merchant protocol + FK/IK.

Architecture:
  Cloud -> SC171  MQTT (target / pose / pose_delta)
  SC171 -> IK (pose*) -> joint angles
  SC171 -> STM32  JetArm AA55 BUS_SERVO @ 1 Mbps (USB Type-C = USART1)
  STM32 -> SC171  position reports
  SC171 -> FK -> pose + MQTT status

Legacy --drive aa55|lobot kept for debug.
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
    hex_frame as hex_aa55,
    pack_frame as pack_aa55,
    pack_status_reply,
)
from hiwonder_servo import (  # noqa: E402
    JMAX,
    JMIN,
    SERVO_IDS,
    hex_frames,
    pack_arm_joints_deg,
    pos_to_deg,
)
from joint_protection import (  # noqa: E402
    ServoSafetyGate,
    clamp_joints_deg,
    joints_to_positions,
    load_home_joints,
    load_initial_joints,
)
from jetarm_packet import (  # noqa: E402
    PACKET_FUNC_BUS_SERVO,
    SUB_READ_POSITION,
    JetArmStreamParser,
    hex_frame,
    pack_load,
    pack_read_position,
    pack_set_positions,
    pack_unload,
    parse_bus_servo_report,
)
from arm_kinematics import (  # noqa: E402
    JacobianSmoother,
    apply_pose_delta,
    fk,
    pose_dict,
    pose_in_workspace,
    solve_reachable,
)

TOPIC_CMD = "arm/device/cmd"
TOPIC_MODE = "arm/device/mode"
TOPIC_STATUS = "arm/device/status"
TOPIC_HB = "arm/device/heartbeat"
TOPIC_TRACE = "arm/device/trace"

JOINT_MIN = list(JMIN)
JOINT_MAX = list(JMAX)
UART_BAUD_JETARM = 1000000
UART_BAUD_LEGACY = 115200


def clamp_joints(joints):
    return clamp_joints_deg(joints)


def now_ms():
    return int(time.time() * 1000)


def log(msg):
    print(msg, flush=True)


class UartLink(object):
    """Bidirectional USB-CDC / serial link."""

    def __init__(self, port, baud=UART_BAUD_JETARM):
        self.port = port
        self.baud = int(baud)
        self._fd = None
        self._ser = None
        self._usb = None
        self._ch340 = None
        self._ep_out = None
        self._ep_in = None
        self.mode = "none"
        self.last_error = ""
        self.tx_ok = 0
        self.tx_fail = 0
        self.rx_bytes = 0
        self._open()

    def _open_pyusb(self):
        # Prefer CH340 userspace (1a86:7523) — AidLux often has no /dev/ttyUSB*
        try:
            from ch340_pyusb import Ch340Serial

            self._ch340 = Ch340Serial(self.baud)
            self.mode = "pyusb:1a86:7523:ch340"
            log("[H0-OPEN] link=%s baud=%s" % (self.mode, self.baud))
            return True
        except Exception as e:
            log("[H0-OPEN] ch340_pyusb skip: %s" % e)

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
            try:
                import struct

                line_coding = struct.pack("<IBBB", self.baud, 0, 0, 8)
                dev.ctrl_transfer(0x21, 0x20, 0, 0, line_coding, timeout=1000)
                dev.ctrl_transfer(0x21, 0x22, 0x0003, 0, timeout=1000)
                log("[H0-OPEN] CDC line_coding=%s 8N1 DTR/RTS on" % self.baud)
            except Exception as e:
                log("[H0-OPEN] CDC line_coding warn: %s" % e)
            self.mode = "pyusb:1a86:55d4"
            log(
                "[H0-OPEN] link=%s baud=%s ep_out=%s ep_in=%s"
                % (
                    self.mode,
                    self.baud,
                    hex(ep_out.bEndpointAddress),
                    None if ep_in is None else hex(ep_in.bEndpointAddress),
                )
            )
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

            self._ser = serial.Serial(self.port, self.baud, timeout=0.05)
            self.mode = "serial:%s" % self.port
            log("[H0-OPEN] link=%s baud=%s" % (self.mode, self.baud))
            return
        except Exception as e:
            self.last_error = "serial open fail: %s" % e
        if self._open_pyusb():
            return
        log("[H0-OPEN] FAILED: %s" % self.last_error)
        self.mode = "none"

    def write(self, frame):
        try:
            if self._ch340 is not None:
                self._ch340.write(frame)
                n = len(frame)
            elif self._fd is not None:
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
            if self._ch340 is not None:
                data = self._ch340.read(max_bytes, timeout_ms)
                if data:
                    self.rx_bytes += len(data)
                return data or b""
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
        if self._ch340 is not None:
            try:
                self._ch340.close()
            except Exception:
                pass
            self._ch340 = None
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
        drive="jetarm",
        move_time_ms=2000,
        baud=None,
        boot_home=True,
        poll_interval=0.12,
        boot_pose="initial",
    ):
        self.host = host
        self.port = port
        self.carrier = carrier
        self.hb_interval = hb_interval
        self.echo_sim = echo_sim
        # drive: jetarm | aa55 | lobot | both
        self.drive = (drive or "jetarm").lower()
        # boot_pose: initial | home | none  (boot_home=False forces none)
        if not boot_home:
            self.boot_pose = "none"
        else:
            self.boot_pose = (boot_pose or "initial").lower()
            if self.boot_pose not in ("initial", "home", "none"):
                self.boot_pose = "initial"
        self.boot_home = self.boot_pose != "none"
        self.move_time_ms = int(move_time_ms)
        if baud is None:
            baud = UART_BAUD_JETARM if self.drive == "jetarm" else UART_BAUD_LEGACY
        self.baud = int(baud)
        self.link = UartLink(uart_port, baud=self.baud)
        self.parser_aa55 = FrameStreamParser()
        self.parser_jetarm = JetArmStreamParser()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.connected = False
        self.seq = 0
        self.uart_seq = 0
        self.mode = "idle"
        self.estop = False
        # home = Z-line taught pose; initial = working start pose
        self.home = load_home_joints()
        self.initial = load_initial_joints()
        self.target = list(self.initial)
        self.actual = list(self.target)
        self.pose = fk(self.actual)
        self.ik_ok = True
        self.servo_online = [False] * 6
        self.last_cmd_seq = 0
        self.recv_mqtt = 0
        self.tx_uart = 0
        self.rx_frames = 0
        self.rx_status = 0
        self.rx_garbage = 0
        self.last_rx_at = 0.0
        self.stm32_online = False
        self.last_hop = {}
        self._pending_rtt = None
        self._pending_read = {}  # servo_id -> t0
        # Telemetry rate (~8 Hz). Main loop tick is independent of hb_interval.
        self._poll_interval = max(0.05, float(poll_interval))
        self._loop_tick = min(0.05, self._poll_interval)
        self._poll_busy = False
        self._batch_status = False  # defer MQTT status until full joint scan
        self._status_min_interval = 0.05
        self._last_status_pub = 0.0
        self._trace_mqtt_hops = frozenset(
            {
                "H0-READY",
                "H0-HOME",
                "H0-INIT",
                "H0-FOLLOW",
                "H1-MQTT",
                "H2-PACK",
                "H3-UART",
            }
        )
        # Pre-UART: Jacobian smooth (anti-jitter) + soft limits / slew / write pacing
        self.safety = ServoSafetyGate(move_time_ms=self.move_time_ms)
        self.safety.reset(self.target)
        self.jac_smooth = JacobianSmoother(ema=0.35, chatter_deg=2.4)
        self.jac_smooth.reset(self.target)
        self._loaded = False
        self._homed = False
        self._booting = False  # True while H0-INIT/H0-HOME running

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
        # High-rate RX/UP hops: local log only (MQTT flood was the main lag source)
        if hop in ("H4-RX", "H5-UP") and not kw.get("boot"):
            return
        log("[%s] %s" % (hop, json.dumps(kw, ensure_ascii=False)))
        if self.connected and hop in self._trace_mqtt_hops:
            try:
                self._pub(TOPIC_TRACE, info, qos=0)
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe([(TOPIC_CMD, 1), (TOPIC_MODE, 1)])
            log(
                "[OK] MQTT %s:%s link=%s baud=%s drive=%s"
                % (self.host, self.port, self.link.mode, self.baud, self.drive)
            )
            self._publish_hb()
            self._publish_status(force=True)
            self._trace(
                "H0-READY",
                mqtt=True,
                link=self.link.mode,
                baud=self.baud,
                echo_sim=self.echo_sim,
                drive=self.drive,
            )
            if self.drive == "jetarm":
                if self.boot_pose == "none":
                    threading.Thread(target=self._jetarm_boot_follow, daemon=True).start()
                else:
                    threading.Thread(target=self._jetarm_boot_probe, daemon=True).start()
        else:
            log("[ERR] mqtt rc=%s" % rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        log("[WARN] mqtt down rc=%s" % rc)

    def _boot_goal(self):
        """Goal joints for boot move: working initial (default) or Z-line home."""
        if self.boot_pose == "home":
            return list(self.home)
        return list(self.initial)

    def _jetarm_boot_follow(self):
        """Sync mode: read actual only (no boot move, no torque LOAD). Web follows arm."""
        time.sleep(0.3)
        # Keep unloaded so free-move observation does not fight servo torque
        self._jetarm_unload_all()
        self._jetarm_read_all()
        with self._lock:
            seed = (
                clamp_joints(self.actual) if any(self.servo_online) else list(self.initial)
            )
            self.target = list(seed)
            # Keep taught Z-line home; do not overwrite from live actual
            self.safety.reset(seed)
            self.jac_smooth.reset(seed)
            self._homed = True
        self._publish_status(force=True)
        self._trace(
            "H0-FOLLOW",
            home=self.home,
            initial=self.initial,
            actual=list(self.actual),
            note="boot_pose_none_unload",
        )

    def _jetarm_boot_probe(self):
        """On activate: read actual → LOAD → go to initial (or home) pose.

        Bypasses H1-JAC so EMA/Cartesian caps cannot stop short of the goal.
        Default goal is working initial_pose.json (not Z-line home).
        """
        self._booting = True
        try:
            time.sleep(0.3)
            self._jetarm_read_all()
            goal = clamp_joints(self._boot_goal())
            hop = "H0-INIT" if self.boot_pose != "home" else "H0-HOME"
            with self._lock:
                seed = (
                    clamp_joints(self.actual) if any(self.servo_online) else list(goal)
                )
                self.safety.reset(seed)
                self.jac_smooth.reset(seed)
                self.target = list(goal)
            self._trace(
                hop,
                phase="start",
                boot_pose=self.boot_pose,
                goal=goal,
                home=self.home,
                initial=self.initial,
                seed=seed,
                actual=list(self.actual),
                jac="off",
            )
            self._jetarm_load_all()
            old_mt = self.move_time_ms
            self.move_time_ms = max(old_mt, 1600)
            # Slew-only approach (soft-limit safe), then exact snap
            for step in range(24):
                if self._stop.is_set():
                    break
                ok = self._jetarm_send_joints(
                    goal,
                    mqtt_seq=0,
                    force=True,
                    use_jacobian=False,
                )
                with self._lock:
                    cur = list(self.target)
                self._trace(hop, step=step, ok=ok, target=cur, goal=goal, jac="off")
                if all(abs(cur[i] - goal[i]) <= 0.35 for i in range(6)):
                    break
                time.sleep(max(0.35, self.move_time_ms / 1000.0 * 0.55))
            # Exact snap: bypass Jacobian + slew so we actually arrive
            positions = joints_to_positions(goal)
            self._trace(hop, phase="exact", goal=goal, positions=positions)
            self._jetarm_write_positions(
                goal, positions, mqtt_seq=0, safety_why="%s_exact" % self.boot_pose
            )
            with self._lock:
                self.target = list(goal)
                self.safety.reset(goal)
                self.jac_smooth.reset(goal)
            self.move_time_ms = old_mt
            time.sleep(max(0.5, old_mt / 1000.0 * 0.7))
            self._jetarm_read_all()
            self._homed = True
            self._trace(
                hop,
                phase="done",
                boot_pose=self.boot_pose,
                goal=goal,
                target=list(self.target),
                actual=list(self.actual),
                jac="off",
            )
        finally:
            self._booting = False

    def _jetarm_load_all(self):
        for sid in SERVO_IDS:
            fr = pack_load(sid)
            self.link.write(fr)
            time.sleep(0.01)
        self._loaded = True
        self._trace("H2-PACK", protocol="jetarm", kind="load_all")

    def _jetarm_unload_all(self):
        """Release torque — prevents continuous hold burnout on estop/hold."""
        for sid in SERVO_IDS:
            fr = pack_unload(sid)
            self.link.write(fr)
            time.sleep(0.01)
        self._loaded = False
        seed = self.actual if any(self.servo_online) else self.target
        self.safety.reset(seed)
        self.jac_smooth.reset(seed)
        self._trace("H2-PACK", protocol="jetarm", kind="unload_all")

    def _jetarm_write_positions(
        self, safe_joints, positions, mqtt_seq=0, safety_why="ok", move_time_ms=None
    ):
        if not self._loaded:
            self._jetarm_load_all()
        ids = list(SERVO_IDS)
        pos = list(positions)
        if self.servo_online[5] is False and any(self.servo_online[:5]):
            ids = SERVO_IDS[:5]
            pos = pos[:5]
        mt = int(self.move_time_ms if move_time_ms is None else move_time_ms)
        frame = pack_set_positions(ids, pos, mt)
        self._trace(
            "H2-PACK",
            mqtt_seq=mqtt_seq,
            protocol="jetarm",
            joints=safe_joints,
            positions=pos,
            move_time_ms=mt,
            safety=safety_why,
            hex=hex_frame(frame),
        )
        t0 = time.time()
        ok, err = self.link.write(frame)
        dt = (time.time() - t0) * 1000.0
        if ok:
            self.tx_uart += 1
            self.target = list(safe_joints)
            self._pending_rtt = (self.uart_seq, t0, list(safe_joints))
            self._trace(
                "H3-UART",
                ok=True,
                protocol="jetarm",
                bytes=len(frame),
                sink=self.link.mode,
                dt_ms=round(dt, 2),
                tx_ok=self.link.tx_ok,
            )
            if self.echo_sim:
                self.actual = list(safe_joints)
                self.pose = fk(self.actual)
                self.servo_online = [True] * 6
                self.stm32_online = True
                self._publish_status(force=True)
            else:
                threading.Thread(
                    target=self._delayed_read_all, args=(0.15,), daemon=True
                ).start()
        else:
            self._trace(
                "H3-UART",
                ok=False,
                protocol="jetarm",
                err=err,
                sink=self.link.mode,
                dt_ms=round(dt, 2),
            )
        return ok

    def _jetarm_send_joints(self, joints, mqtt_seq=0, force=False, use_jacobian=True):
        # Jacobian path: Δq → JΔq → limit TCP → DLS Δq' (+ EMA / anti-chatter)
        # Also adapts move_time_ms from Cartesian step + singularity (half-speed base).
        # Homing / exact snaps set use_jacobian=False so we fully reach the target.
        want = clamp_joints(joints)
        jac_why = "jac:bypass"
        mt = int(self.move_time_ms)
        if use_jacobian:
            with self._lock:
                # Prefer live actual for singularity scoring (target can lag / be clamped)
                if any(self.servo_online[:5]):
                    seed = list(self.actual)
                else:
                    seed = list(self.target)
            want, jac_why, mt = self.jac_smooth.step(
                seed, want, move_time_ms=self.move_time_ms
            )
            self._trace(
                "H1-JAC",
                why=jac_why,
                seed=seed,
                want=list(joints) if joints is not None else None,
                smooth=want,
                move_time_ms=mt,
                sing=round(getattr(self.jac_smooth, "last_sing", 0.0), 3),
                mqtt_seq=mqtt_seq,
            )
        else:
            self._trace(
                "H1-JAC",
                why=jac_why,
                want=list(joints) if joints is not None else None,
                move_time_ms=mt,
                mqtt_seq=mqtt_seq,
            )
        allow, safe_joints, positions, why = self.safety.verify(
            want, move_time_ms=mt, force=force
        )
        self._trace(
            "H1-SAFE",
            ok=allow,
            why=why,
            joints=safe_joints,
            positions=positions,
            move_time_ms=mt,
            mqtt_seq=mqtt_seq,
        )
        if not allow:
            return False
        return self._jetarm_write_positions(
            safe_joints,
            positions,
            mqtt_seq=mqtt_seq,
            safety_why="%s|%s" % (jac_why, why),
            move_time_ms=mt,
        )

    def _delayed_read_all(self, delay):
        time.sleep(delay)
        self._jetarm_read_all()

    def _jetarm_read_all(self):
        if self._poll_busy:
            return
        self._poll_busy = True
        self._batch_status = True
        try:
            # Skip offline gripper (id 6) when known dead — saves ~1 RTT per cycle
            ids = list(SERVO_IDS)
            if self.servo_online[5] is False and any(self.servo_online[:5]):
                ids = SERVO_IDS[:5]
            for sid in ids:
                fr = pack_read_position(sid)
                self._pending_read[sid] = time.time()
                ok, err = self.link.write(fr)
                if not ok:
                    self._trace(
                        "H3-UART", ok=False, protocol="jetarm", kind="read", id=sid, err=err
                    )
                # Typical RTT ~3–8 ms; keep short wait to raise scan rate
                deadline = time.time() + 0.018
                got = False
                while time.time() < deadline:
                    data = self.link.read(64, timeout_ms=5)
                    if data:
                        self._handle_rx_bytes(data, source="usb")
                        got = True
                        break
                    time.sleep(0.001)
                if not got:
                    time.sleep(0.002)
        finally:
            self._batch_status = False
            self._poll_busy = False
            self._publish_status(force=True)

    def _forward_uart(self, joints, estop=False, hold=False, mqtt_seq=0):
        self.uart_seq = (self.uart_seq + 1) & 0xFF
        ok_any = False
        t0 = time.time()

        if self.drive == "jetarm":
            if estop or hold:
                self._jetarm_unload_all()
                self._trace(
                    "H2-PACK",
                    protocol="jetarm",
                    kind="estop" if estop else "hold",
                    note="unload_torque",
                )
                return True
            return self._jetarm_send_joints(joints, mqtt_seq=mqtt_seq)

        flags = 0
        cmd = CMD_JOINT
        if estop:
            flags |= FLAG_ESTOP
            cmd = CMD_ESTOP
        elif hold:
            flags |= FLAG_HOLD
            cmd = CMD_HOLD

        if self.drive in ("aa55", "both") and not estop:
            frame = pack_aa55(cmd, self.uart_seq, joints, flags)
            self._trace(
                "H2-PACK",
                mqtt_seq=mqtt_seq,
                uart_seq=self.uart_seq,
                cmd=cmd,
                flags=flags,
                joints=joints,
                protocol="aa55",
                hex=hex_aa55(frame),
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
            frame = pack_aa55(CMD_ESTOP, self.uart_seq, joints, FLAG_ESTOP)
            ok, err = self.link.write(frame)
            ok_any = ok_any or ok
            self._trace("H3-UART", ok=ok, protocol="aa55", kind="estop", err=err)

        if self.drive in ("lobot", "both") and cmd == CMD_JOINT and not estop:
            with self._lock:
                seed = list(self.target)
            smooth, jac_why, mt = self.jac_smooth.step(
                seed, joints, move_time_ms=self.move_time_ms
            )
            allow, safe_joints, _pulses, why = self.safety.verify(
                smooth, move_time_ms=mt
            )
            self._trace(
                "H1-SAFE",
                ok=allow,
                why="%s|%s" % (jac_why, why),
                joints=safe_joints,
                move_time_ms=mt,
                protocol="lobot",
            )
            if not allow:
                return ok_any
            frames = pack_arm_joints_deg(safe_joints, mt)
            self._trace(
                "H2-PACK",
                mqtt_seq=mqtt_seq,
                uart_seq=self.uart_seq,
                protocol="lobot",
                joints=safe_joints,
                move_time_ms=mt,
                safety=why,
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
                self.target = list(safe_joints)
                self.actual = list(safe_joints)
                self.pose = fk(self.actual)
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
                    echo = pack_status_reply(self.uart_seq, safe_joints, moving=False)
                    self._handle_rx_bytes(echo, source="echo_sim")
                else:
                    self._publish_status(force=True)

        return ok_any

    def _handle_jetarm_frame(self, fr, source="usb"):
        self.rx_frames += 1
        self.last_rx_at = time.time()
        self.stm32_online = True
        if fr.get("function") != PACKET_FUNC_BUS_SERVO:
            self._trace(
                "H4-RX",
                ok=True,
                source=source,
                protocol="jetarm",
                function=fr.get("function"),
                hex=hex_frame(fr.get("raw") or b""),
            )
            return
        rep = parse_bus_servo_report(fr)
        if rep is None:
            return
        sid = int(rep["servo_id"])
        ok = int(rep["success"]) == 0
        idx = sid - 1
        if 0 <= idx < 6:
            self.servo_online[idx] = ok
        rtt_ms = None
        if sid in self._pending_read:
            rtt_ms = round((time.time() - self._pending_read.pop(sid)) * 1000.0, 2)
        joints_dbg = None
        if ok and rep["sub_cmd"] == SUB_READ_POSITION and len(rep["args"]) >= 2:
            pos = rep["args"][0] | (rep["args"][1] << 8)
            if 0 <= idx < 6:
                with self._lock:
                    self.actual[idx] = pos_to_deg(pos, idx)
                    self.pose = fk(self.actual)
                joints_dbg = list(self.actual)
                self.rx_status += 1
        self._trace(
            "H4-RX",
            ok=ok,
            source=source,
            protocol="jetarm",
            servo_id=sid,
            sub_cmd=rep["sub_cmd"],
            success=rep["success"],
            joints=joints_dbg,
            hex=hex_frame(rep.get("raw") or b""),
            rtt_ms=rtt_ms,
            rx_frames=self.rx_frames,
        )
        if ok and rep["sub_cmd"] == SUB_READ_POSITION and not self._batch_status:
            # During full scans, status is published once at end of _jetarm_read_all
            self._publish_status()

    def _handle_rx_bytes(self, data, source="usb"):
        if not data:
            return
        if self.drive == "jetarm":
            frames = self.parser_jetarm.feed(data)
            if not frames:
                self.rx_garbage += len(data)
                if self.rx_garbage % 200 < len(data):
                    self._trace(
                        "H4-RX",
                        ok=False,
                        source=source,
                        protocol="jetarm",
                        raw_len=len(data),
                        raw_hex=hex_frame(data[:20]),
                        note="no_valid_frame_yet",
                    )
                return
            for fr in frames:
                self._handle_jetarm_frame(fr, source=source)
            return

        before = self.rx_frames
        frames = self.parser_aa55.feed(data)
        if not frames:
            self.rx_garbage += len(data)
            if self.rx_garbage % 200 < len(data):
                self._trace(
                    "H4-RX",
                    ok=False,
                    source=source,
                    raw_len=len(data),
                    raw_hex=hex_aa55(data[:20]),
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
                hex=hex_aa55(fr["raw"]),
                rtt_ms=rtt_ms,
                rx_frames=self.rx_frames,
            )
            if fr["cmd"] == CMD_STATUS:
                self.rx_status += 1
                with self._lock:
                    self.actual = list(joints)
                    self.pose = fk(self.actual)
                self._publish_status()
                self._trace(
                    "H5-UP",
                    ok=True,
                    actual=list(joints),
                    pose=self.pose,
                    rtt_ms=rtt_ms,
                    stm32_online=True,
                    rx_status=self.rx_status,
                )
            elif fr["cmd"] in (0x82, 0x83):
                self.stm32_online = True
                self._trace(
                    "H5-UP",
                    ok=True,
                    kind="ack" if fr["cmd"] == 0x82 else "fault",
                    seq=fr["seq"],
                    flags=fr["flags"],
                )
        _ = before

    def _rx_loop(self):
        while not self._stop.is_set():
            data = self.link.read(64, timeout_ms=30)
            if data:
                self._handle_rx_bytes(data, source="usb")
            else:
                if self.stm32_online and (time.time() - self.last_rx_at) > 3.0:
                    self.stm32_online = False
                    self._trace("H4-RX", ok=False, note="stm32_timeout_3s")
                time.sleep(0.005)

    def _parse_pose_obj(self, obj):
        if not isinstance(obj, dict):
            return None
        return pose_dict(
            x=float(obj.get("x", 0.0) or 0.0),
            y=float(obj.get("y", 0.0) or 0.0),
            z=float(obj.get("z", 0.0) or 0.0),
            roll=float(obj.get("roll", 0.0) or 0.0),
            pitch=float(obj.get("pitch", 0.0) or 0.0),
            yaw=float(obj.get("yaw", 0.0) or 0.0),
        )

    def _apply_cmd_payload(self, payload):
        """Resolve joints from pose / pose_delta / target. Returns joints or None."""
        pose_abs = self._parse_pose_obj(payload.get("pose"))
        pose_delta = self._parse_pose_obj(payload.get("pose_delta"))
        gripper = payload.get("gripper", None)

        if pose_abs is not None or (
            pose_delta is not None
            and any(abs(float(pose_delta.get(k, 0.0))) > 1e-9 for k in pose_delta)
        ):
            with self._lock:
                seed = list(self.actual) if any(self.servo_online) else list(self.target)
                base_pose = dict(self.pose) if any(self.servo_online) else fk(seed)
            if pose_abs is not None:
                target_pose = pose_abs
            else:
                target_pose = apply_pose_delta(base_pose, pose_delta)
            joints, ok, why = solve_reachable(
                target_pose, seed, gripper=float(gripper) if gripper is not None else None
            )
            self.ik_ok = bool(ok)
            self._trace(
                "H1-IK",
                ok=ok,
                why=why,
                seed=seed,
                target_pose=target_pose,
                joints=joints,
            )
            # Unreachable / URDF-infeasible → hold last target (do not drive)
            if not ok or joints is None:
                return None
            return clamp_joints(joints)

        target = payload.get("target")
        if isinstance(target, list) and len(target) >= 6:
            joints = clamp_joints([float(x) for x in target[:6]])
            if gripper is not None:
                joints[5] = float(gripper)
                joints = clamp_joints(joints)
            # Joint-space: soft limits only. Floor/reach gate is for pose IK —
            # a hand-taught home can sit near the table and still be valid.
            pose = fk(joints)
            ws_ok, ws_why = pose_in_workspace(pose)
            self.ik_ok = True
            if not ws_ok:
                self._trace(
                    "H1-IK",
                    ok=True,
                    why="joint_ok_workspace_warn:%s" % ws_why,
                    joints=joints,
                    pose=pose,
                )
            return joints
        if gripper is not None:
            with self._lock:
                joints = list(self.target)
            joints[5] = float(gripper)
            self.ik_ok = True
            return clamp_joints(joints)
        return None

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
                # Do not unload while boot-to-initial/home is in progress
                hold = (not self._booting) and self.mode in ("hold", "paused", "idle")
                self._forward_uart(self.target, estop=self.estop, hold=hold)
            elif msg.topic == TOPIC_CMD:
                self.last_cmd_seq = int(payload.get("seq", 0) or 0)
                self.mode = str(payload.get("mode", self.mode))
                self.estop = bool(payload.get("estop", False))
                joints = self._apply_cmd_payload(payload)
                if joints is not None:
                    self.target = joints
                self._trace(
                    "H1-MQTT",
                    topic="cmd",
                    seq=self.last_cmd_seq,
                    mode=self.mode,
                    estop=self.estop,
                    target=self.target,
                    pose=payload.get("pose"),
                    pose_delta=payload.get("pose_delta"),
                    ik_ok=self.ik_ok,
                    age_ms=max(0, t_mqtt - int(payload.get("ts_ms", t_mqtt) or t_mqtt)),
                )
                hold = (
                    (not self.estop)
                    and (not self._booting)
                    and self.mode in ("hold", "paused", "idle")
                )
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
                "uart_baud": self.baud,
                "drive": self.drive,
                "uart_tx_ok": self.link.tx_ok,
                "uart_rx_bytes": self.link.rx_bytes,
                "rx_frames": self.rx_frames,
                "rx_status": self.rx_status,
                "stm32_online": self.stm32_online,
            },
        )

    def _publish_status(self, force=False):
        now = time.time()
        if (
            not force
            and (now - self._last_status_pub) < self._status_min_interval
        ):
            return
        self._last_status_pub = now
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
                "pose": {
                    "x": round(self.pose.get("x", 0.0), 5),
                    "y": round(self.pose.get("y", 0.0), 5),
                    "z": round(self.pose.get("z", 0.0), 5),
                    "roll": round(self.pose.get("roll", 0.0), 5),
                    "pitch": round(self.pose.get("pitch", 0.0), 5),
                    "yaw": round(self.pose.get("yaw", 0.0), 5),
                },
                "ik_ok": bool(self.ik_ok),
                "servo_online": list(self.servo_online),
                "fault": "" if self.link.mode != "none" else "uart_down",
                "estop": self.estop,
                "carrier": self.carrier,
                "uart_mode": self.link.mode,
                "uart_baud": self.baud,
                "drive": self.drive,
                "uart_tx_ok": self.link.tx_ok,
                "uart_rx_bytes": self.link.rx_bytes,
                "rx_frames": self.rx_frames,
                "rx_status": self.rx_status,
                "rx_garbage": self.rx_garbage,
                "last_hop": self.last_hop.get("hop", ""),
            }
        self._pub(TOPIC_STATUS, payload)

    def start(self):
        log(
            "[..] mqtt://%s:%s link=%s baud=%s echo_sim=%s drive=%s poll=%.0fms"
            % (
                self.host,
                self.port,
                self.link.mode,
                self.baud,
                self.echo_sim,
                self.drive,
                self._poll_interval * 1000.0,
            )
        )
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        rx = threading.Thread(target=self._rx_loop, name="uart-rx", daemon=True)
        rx.start()
        last_poll = 0.0
        last_hb = 0.0
        # Fast tick so joint poll is not capped by hb_interval (was 1s → ~1 Hz lag)
        while not self._stop.wait(self._loop_tick):
            if not self.connected:
                continue
            now = time.time()
            do_hb = (now - last_hb) >= self.hb_interval
            if do_hb:
                last_hb = now
                self._publish_hb()
            with self._lock:
                joints = list(self.target)
                estop = self.estop
            if self.drive == "jetarm":
                if (
                    (now - last_poll) >= self._poll_interval
                    and not estop
                    and not self._poll_busy
                ):
                    last_poll = now
                    threading.Thread(
                        target=self._jetarm_read_all, daemon=True, name="jetarm-poll"
                    ).start()
            elif self.drive in ("aa55", "both") and do_hb:
                self.uart_seq = (self.uart_seq + 1) & 0xFF
                cmd = CMD_ESTOP if estop else CMD_HEARTBEAT
                flags = FLAG_ESTOP if estop else 0
                frame = pack_aa55(cmd, self.uart_seq, joints, flags)
                ok, err = self.link.write(frame)
                if not ok:
                    self._trace(
                        "H3-UART",
                        ok=False,
                        kind="heartbeat",
                        protocol="aa55",
                        err=err,
                    )

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
        help="simulate STATUS / FK locally (path self-test)",
    )
    ap.add_argument(
        "--drive",
        default="jetarm",
        choices=["jetarm", "aa55", "lobot", "both"],
        help="jetarm=商家USART1@1Mbps(默认); aa55=旧20B; lobot=直驱调试",
    )
    ap.add_argument("--baud", type=int, default=0, help="0=auto by drive")
    ap.add_argument(
        "--move-time-ms",
        type=int,
        default=2000,
        help="base move duration ms (2000≈half of prior 1000; Jacobian adapts further)",
    )
    ap.add_argument(
        "--boot-pose",
        choices=["initial", "home", "none"],
        default="initial",
        help="on start: move to initial_pose (default), Z-line home, or none (follow/unload)",
    )
    ap.add_argument(
        "--no-boot-home",
        action="store_true",
        help="alias for --boot-pose none (follow actual, unload)",
    )
    ap.add_argument(
        "--poll-interval",
        type=float,
        default=0.12,
        help="joint telemetry poll period seconds (default 0.12 ≈ 8 Hz)",
    )
    args = ap.parse_args()
    baud = args.baud if args.baud > 0 else None
    boot_pose = "none" if args.no_boot_home else args.boot_pose
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
        baud,
        boot_home=(boot_pose != "none"),
        poll_interval=args.poll_interval,
        boot_pose=boot_pose,
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
