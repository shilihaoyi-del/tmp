#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Free-move arm → read joints → MQTT upload (cloud FK pose + web 3D follow).

Use this to check whether the web model axes match the real JetArm:
  1. Stop servo bridge (exclusive USB)
  2. On AidLux:
       sudo python3 free_move_cloud.py --hz 5
  3. Open the observation web console — source=free_move, model follows hand moves
  4. Compare each joint visually vs printed deg/pulse/pose

Publishes:
  arm/device/heartbeat
  arm/device/status   (carrier=FREE_MOVE, actual=target=measured, pose=FK)

Ctrl+C exits (servos stay unloaded unless --reload).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[FAIL] need paho-mqtt: pip3 install paho-mqtt")
    sys.exit(2)

from arm_kinematics import fk  # noqa: E402
from free_move_read import (  # noqa: E402
    JOINT_NAMES,
    _read_one,
    format_row,
    load_all,
    print_header,
    unload_all,
)
from jetarm_packet import JetArmStreamParser  # noqa: E402
from joint_protection import JMAX, JMIN  # noqa: E402
from probe_read_positions import open_link  # noqa: E402

TOPIC_STATUS = "arm/device/status"
TOPIC_HB = "arm/device/heartbeat"
TOPIC_TRACE = "arm/device/trace"
TOPIC_WEB = "arm/web/status"


def now_ms():
    return int(time.time() * 1000)


def results_to_joints(results, hold):
    """Build 6-vector; keep last good value per joint if a read fails."""
    out = list(hold)
    online = [False] * 6
    pulses = [None] * 6
    for sid in range(1, 7):
        r = results.get(sid) or {}
        if r.get("ok") and r.get("deg") is not None:
            out[sid - 1] = float(r["deg"])
            online[sid - 1] = True
            pulses[sid - 1] = r.get("pulse")
    return out, online, pulses


def connect_mqtt(host, port, client_id):
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311, clean_session=True)
    client.connect(host, int(port), keepalive=30)
    client.loop_start()
    return client


def publish(client, topic, payload, qos=0):
    body = json.dumps(payload, separators=(",", ":"))
    info = client.publish(topic, body, qos=qos)
    return info.rc == mqtt.MQTT_ERR_SUCCESS


def main():
    ap = argparse.ArgumentParser(description="Free-move + cloud status upload for map check")
    ap.add_argument("--port", default="", help="serial; empty = auto CH340/tty*")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--hz", type=float, default=12.0)
    ap.add_argument("--host", default="121.41.67.80", help="MQTT broker")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--client-id", default="sc171-free-move")
    ap.add_argument("--ids", default="1,2,3,4,5,6")
    ap.add_argument("--no-unload", action="store_true")
    ap.add_argument("--reload", action="store_true", help="LOAD then exit")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    period = 1.0 / max(0.5, float(args.hz))

    try:
        link = open_link(args.port, args.baud)
    except Exception as e:
        print("[FAIL] open uart:", e)
        return 1

    try:
        client = connect_mqtt(args.host, args.mqtt_port, args.client_id)
    except Exception as e:
        link.close()
        print("[FAIL] mqtt:", e)
        return 1

    parser = JetArmStreamParser()
    hold = [0.0, -90.0, 60.0, -90.0, 0.0, 45.0]
    seq = 0
    last_hb = 0.0

    try:
        if args.reload:
            load_all(link, ids)
            args.once = True
        elif not args.no_unload:
            unload_all(link, ids)

        print_header()
        print(
            "cloud map-check: MQTT %s:%s  topics %s + %s"
            % (args.host, args.mqtt_port, TOPIC_STATUS, TOPIC_HB)
        )
        print(
            "web axes: j1=Y(base) j2..j5=Z  gripper=spread from deg/90  | "
            "soft=[%s]"
            % ", ".join("%s:[%.0f..%.0f]" % (JOINT_NAMES[i], JMIN[i], JMAX[i]) for i in range(6))
        )
        print("Open web console — expect source=free_move; move arm by hand and compare.\n")

        while True:
            t0 = time.time()
            results = {}
            for sid in ids:
                # Skip long waits on known-offline gripper (id6)
                results[sid] = _read_one(
                    link, parser, sid, timeout_s=0.08 if sid != 6 else 0.05
                )

            joints, online, pulses = results_to_joints(results, hold)
            hold = list(joints)
            pose = fk(joints)
            seq += 1
            ts = now_ms()

            joints_r = [round(v, 2) for v in joints]
            pose_r = {
                "x": round(pose["x"], 5),
                "y": round(pose["y"], 5),
                "z": round(pose["z"], 5),
                "roll": round(pose["roll"], 5),
                "pitch": round(pose["pitch"], 5),
                "yaw": round(pose["yaw"], 5),
            }
            status = {
                "seq": seq,
                "ts_ms": ts,
                "online": True,
                "stm32_online": any(online),
                "mode": "running",
                "target": joints_r,
                "actual": joints_r,
                "pose": pose_r,
                "ik_ok": True,
                "servo_online": online,
                "fault": "",
                "estop": False,
                "carrier": "FREE_MOVE",
                "drive": "jetarm-free-move",
            }
            # Full web snapshot — works even if cloud backend is not yet redeployed
            # (MQTT arm/web/status). HTTP /api/status may still show LIVE until backend update.
            web = {
                "module_id": "SC171V2",
                "module_name": "Fibocom SC171V2",
                "carrier": "FREE_MOVE",
                "link": "up",
                "hb_age_ms": 0,
                "mode": "running",
                "device_online": True,
                "stm32_online": any(online),
                "pc_online": False,
                "last_gesture": "FREE_MOVE",
                "target": joints_r,
                "actual": joints_r,
                "pose": pose_r,
                "ik_ok": True,
                "servo_online": online,
                "fault": "",
                "estop": False,
                "latency_ms": 0,
                "control_hz": float(args.hz),
                "seq": seq,
                "source": "free_move",
            }
            ok_st = publish(client, TOPIC_STATUS, status)
            ok_web = publish(client, TOPIC_WEB, web)
            if t0 - last_hb >= 1.0:
                publish(
                    client,
                    TOPIC_HB,
                    {
                        "ts_ms": ts,
                        "online": True,
                        "module_id": "SC171V2",
                        "carrier": "FREE_MOVE",
                        "uart_mode": "free_move",
                    },
                )
                last_hb = t0

            print(
                "[%s] mqtt=%s web=%s %s"
                % (
                    time.strftime("%H:%M:%S"),
                    "ok" if ok_st else "FAIL",
                    "ok" if ok_web else "FAIL",
                    format_row(results),
                )
            )
            print(
                "      deg=%s  pose xyz=(%.3f,%.3f,%.3f)"
                % (
                    "[" + ", ".join("%.1f" % v for v in joints) + "]",
                    pose["x"],
                    pose["y"],
                    pose["z"],
                )
            )
            print(
                "      pulse=%s"
                % ("[" + ", ".join("-" if p is None else str(p) for p in pulses) + "]")
            )

            if args.once:
                break
            dt = time.time() - t0
            time.sleep(max(0.0, period - dt))
    except KeyboardInterrupt:
        print("\n[STOP] free_move_cloud stopped (servos still unloaded unless --reload)")
        publish(
            client,
            TOPIC_TRACE,
            {"hop": "FREE_MOVE", "ok": True, "msg": "stopped", "ts_ms": now_ms()},
        )
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
