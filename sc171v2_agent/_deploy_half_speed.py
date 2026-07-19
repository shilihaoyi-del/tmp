#!/usr/bin/env python3
"""Push half-speed + Jacobian adaptive timing; restart follow (no forced move)."""
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "sc171v2_servo_bridge.py",
    "arm_kinematics.py",
    "joint_protection.py",
    "start_gesture_bridge.sh",
    "start_servo_bridge.sh",
    "home_pose.json",
    "initial_pose.json",
    "jetarm_packet.py",
]

# sync Chinese launcher
open(os.path.join(HERE, "一键启动桥接.sh"), "wb").write(
    open(os.path.join(HERE, "start_gesture_bridge.sh"), "rb").read()
)
FILES.append("一键启动桥接.sh")

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
    for name in FILES:
        local = os.path.join(HERE, name)
        if os.path.isfile(local):
            sftp.put(local, f"{d}/{name}")
            print("put", name)
sftp.close()

_i, o, e = c.exec_command(
    "chmod +x /home/aidlux/sc171v2_agent/*.sh 2>/dev/null; "
    "echo aidlux | sudo -S -p '' bash -lc '"
    "pkill -9 -f sc171v2_servo_bridge.py || true; sleep 2; "
    ": > /tmp/sc171v2_servo_bridge.log; "
    "cd /home/aidlux/Desktop/sc171v2_jetarm; "
    "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
    "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
    "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
    "--drive jetarm --move-time-ms 2000 --poll-interval 0.12 --boot-pose none "
    ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo $! > /tmp/sc171v2_servo_bridge.pid; "
    "sleep 4; ps -p $(cat /tmp/sc171v2_servo_bridge.pid) -o pid,cmd; "
    "grep -E \"poll=|move|H0-FOLLOW|H0-READY|FATAL\" /tmp/sc171v2_servo_bridge.log | head -20'",
    timeout=60,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()

time.sleep(1)
# unload for continued free test
try:
    req = urllib.request.Request(
        "http://121.41.67.80:8000/api/control/reset",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    print("UNLOAD", urllib.request.urlopen(req, timeout=8).read().decode()[:160])
except Exception as ex:
    print("UNLOAD_FAIL", ex)

st = json.loads(
    urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8).read()
)
print("online=", st.get("device_online"), "actual=", st.get("actual"))
