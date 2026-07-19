#!/usr/bin/env python3
"""Force unload on AidLux bridge if HTTP path is flaky."""
from __future__ import annotations

import json
import time
import urllib.request

import paramiko

try:
    import paho.mqtt.publish as publish
except Exception:
    publish = None

# MQTT idle → bridge unload
if publish is not None:
    try:
        publish.single(
            "arm/device/mode",
            json.dumps(
                {
                    "mode": "idle",
                    "estop": False,
                    "ts_ms": int(time.time() * 1000),
                    "seq": 1,
                }
            ),
            hostname="121.41.67.80",
            port=1883,
            qos=1,
            retain=True,
        )
        print("MQTT_IDLE_OK")
    except Exception as ex:
        print("MQTT_FAIL", ex)

# HTTP reset backup
try:
    req = urllib.request.Request(
        "http://121.41.67.80:8000/api/control/reset",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    print("HTTP", urllib.request.urlopen(req, timeout=8).read().decode()[:200])
except Exception as ex:
    print("HTTP_FAIL", ex)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "192.168.42.4",
    username="aidlux",
    password="aidlux",
    timeout=12,
    allow_agent=False,
    look_for_keys=False,
)
_, o, e = c.exec_command(
    "grep -E 'unload|hold|H1-MQTT' /tmp/sc171v2_servo_bridge.log | tail -12; "
    "pgrep -af 'python.*sc171v2_servo_bridge' || echo NO_BRIDGE",
    timeout=15,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()
