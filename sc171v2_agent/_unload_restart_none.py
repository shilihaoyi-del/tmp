#!/usr/bin/env python3
"""Restart bridge with --boot-pose none (unload torque for free-move)."""
from __future__ import annotations

import json
import time
import urllib.request

import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "192.168.42.4",
    username="aidlux",
    password="aidlux",
    timeout=15,
    allow_agent=False,
    look_for_keys=False,
)
_, o, e = c.exec_command(
    "echo aidlux | sudo -S -p '' bash -lc '"
    "pkill -9 -f sc171v2_servo_bridge.py || true; sleep 2; "
    ": > /tmp/sc171v2_servo_bridge.log; "
    "cd /home/aidlux/Desktop/sc171v2_jetarm; "
    "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
    "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
    "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
    "--drive jetarm --move-time-ms 2000 --poll-interval 0.12 --boot-pose none "
    ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo $! > /tmp/sc171v2_servo_bridge.pid; "
    "sleep 4; pgrep -af sc171v2_servo_bridge | head -3; "
    "grep -E \"H0-FOLLOW|unload|H0-READY|FATAL|boot_pose|H2-PACK\" /tmp/sc171v2_servo_bridge.log | head -30'",
    timeout=60,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()

time.sleep(1)
try:
    req = urllib.request.Request(
        "http://121.41.67.80:8000/api/control/reset",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    print("HTTP", urllib.request.urlopen(req, timeout=8).read().decode()[:220])
except Exception as ex:
    print("HTTP_FAIL", ex)

st = json.loads(
    urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8).read()
)
print(
    "online=",
    st.get("device_online"),
    "mode=",
    st.get("mode"),
    "actual=",
    st.get("actual"),
)
