#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
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
sftp = c.open_sftp()
for d in ("/home/aidlux/sc171v2_agent", "/home/aidlux/Desktop/sc171v2_jetarm"):
    sftp.put(os.path.join(HERE, "sc171v2_servo_bridge.py"), f"{d}/sc171v2_servo_bridge.py")
sftp.close()


def run(cmd, timeout=90):
    _i, o, e = c.exec_command(cmd, timeout=timeout)
    print((o.read() + e.read()).decode("utf-8", "replace"))


run(
    "echo aidlux | sudo -S -p '' bash -lc '"
    "pkill -9 -f sc171v2_servo_bridge.py || true; sleep 2; "
    ": > /tmp/sc171v2_servo_bridge.log; "
    "cd /home/aidlux/Desktop/sc171v2_jetarm; "
    "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
    "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
    "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
    "--drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 "
    ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo PID=$!; sleep 4; "
    "pgrep -af sc171v2_servo_bridge.py; "
    "grep -E \"poll=|H0-FOLLOW|FATAL|Error\" /tmp/sc171v2_servo_bridge.log | head -20; "
    "echo ---; wc -l /tmp/sc171v2_servo_bridge.log'"
)
time.sleep(1)
req = urllib.request.Request(
    "http://121.41.67.80:8000/api/control/reset",
    method="POST",
    data=b"{}",
    headers={"Content-Type": "application/json"},
)
print("RESET", urllib.request.urlopen(req, timeout=8).read().decode()[:160])

# count status publishes via seq on device topic indirectly: hb_age + changing ts
st0 = json.loads(urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5).read())
time.sleep(2.0)
st1 = json.loads(urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5).read())
print(
    "online",
    st1.get("device_online"),
    "hb_age",
    st1.get("hb_age_ms"),
    "actual0",
    st0.get("actual"),
    "actual1",
    st1.get("actual"),
)
c.close()
