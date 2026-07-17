#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fibocom SC171V2 MQTT agent — recv cloud cmds, upload heartbeat/status."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from typing import Any, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: pip install paho-mqtt", file=sys.stderr, flush=True)
    sys.exit(1)

TOPIC_CMD = "arm/device/cmd"
TOPIC_MODE = "arm/device/mode"
TOPIC_STATUS = "arm/device/status"
TOPIC_HB = "arm/device/heartbeat"

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


class Sc171v2Agent(object):
    def __init__(self, host, port, client_id, carrier, hb_interval, username="", password=""):
        self.host = host
        self.port = port
        self.carrier = carrier
        self.hb_interval = hb_interval
        self._stop = threading.Event()
        self._lock = threading.RLock()

        self.connected = False
        self.seq = 0
        self.mode = "idle"
        self.estop = False
        self.target = [0.0] * 6
        self.actual = [0.0] * 6
        self.last_cmd_seq = 0
        self.recv_count = 0
        self.send_count = 0
        self.last_cmd_at = 0.0

        # paho-mqtt 1.x API (AidLux Python 3.8)
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311, clean_session=True)
        if username:
            self.client.username_pw_set(username, password or None)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe([(TOPIC_CMD, 1), (TOPIC_MODE, 1)])
            log("[OK] connected %s:%s, subscribed %s, %s" % (self.host, self.port, TOPIC_CMD, TOPIC_MODE))
            self._publish_hb()
            self._publish_status(force=True)
        else:
            self.connected = False
            log("[ERR] connect failed rc=%s" % rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        log("[WARN] disconnected rc=%s" % rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            log("[ERR] bad json on %s: %s" % (msg.topic, exc))
            return

        with self._lock:
            self.recv_count += 1
            self.last_cmd_at = time.time()

            if msg.topic == TOPIC_MODE:
                self.mode = str(payload.get("mode", self.mode))
                self.estop = bool(payload.get("estop", self.estop))
                log("[RX mode] mode=%s estop=%s" % (self.mode, self.estop))
            elif msg.topic == TOPIC_CMD:
                self.last_cmd_seq = int(payload.get("seq", 0) or 0)
                self.mode = str(payload.get("mode", self.mode))
                self.estop = bool(payload.get("estop", False))
                target = payload.get("target")
                if isinstance(target, list) and len(target) >= 6:
                    self.target = clamp_joints([float(x) for x in target[:6]])
                    self.actual = list(self.target)
                log(
                    "[RX cmd] seq=%s mode=%s estop=%s target=%s"
                    % (self.last_cmd_seq, self.mode, self.estop, self.target)
                )
            else:
                log("[RX %s] %s" % (msg.topic, payload))

        self._publish_status()

    def _publish(self, topic, data, qos=0):
        if not self.connected:
            return
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        info = self.client.publish(topic, body, qos=qos)
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            self.send_count += 1
        else:
            log("[ERR] publish %s rc=%s" % (topic, info.rc))

    def _publish_hb(self):
        self._publish(
            TOPIC_HB,
            {
                "ts_ms": now_ms(),
                "online": True,
                "module_id": "SC171V2",
                "carrier": self.carrier,
            },
            qos=0,
        )

    def _publish_status(self, force=False):
        with self._lock:
            self.seq += 1
            payload = {
                "seq": self.seq,
                "ts_ms": now_ms(),
                "online": True,
                "stm32_online": False,
                "mode": self.mode,
                "target": list(self.target),
                "actual": list(self.actual),
                "fault": "",
                "estop": self.estop,
                "carrier": self.carrier,
            }
        self._publish(TOPIC_STATUS, payload, qos=0)
        if force:
            log("[TX status] seq=%s target=%s" % (payload["seq"], payload["target"]))

    def start(self):
        log("[..] connecting mqtt://%s:%s ..." % (self.host, self.port))
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()

        while not self._stop.wait(self.hb_interval):
            if self.connected:
                self._publish_hb()
                age = time.time() - self.last_cmd_at if self.last_cmd_at else 999.0
                if age > 2.0:
                    self._publish_status()

    def stop(self):
        self._stop.set()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        log("[STOP] recv=%s send=%s last_cmd_seq=%s" % (self.recv_count, self.send_count, self.last_cmd_seq))


def main():
    p = argparse.ArgumentParser(description="SC171V2 MQTT cloud agent")
    p.add_argument("--host", default="121.41.67.80")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--client-id", default="sc171v2-aidlux")
    p.add_argument("--carrier", default="Wi-Fi")
    p.add_argument("--hb-interval", type=float, default=1.0)
    p.add_argument("--username", default="")
    p.add_argument("--password", default="")
    args = p.parse_args()

    agent = Sc171v2Agent(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        carrier=args.carrier,
        hb_interval=args.hb_interval,
        username=args.username,
        password=args.password,
    )

    def _sig(signum, frame):
        agent.stop()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()
    except Exception as exc:
        log("[FATAL] %s" % exc)
        agent.stop()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
