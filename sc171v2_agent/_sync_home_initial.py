#!/usr/bin/env python3
"""Push home/initial split to AidLux + cloud FE/backend; restart follow unload."""
from __future__ import annotations

import json
import os
import tarfile
import tempfile
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILES = [
    "home_pose.json",
    "initial_pose.json",
    "joint_protection.py",
    "sc171v2_servo_bridge.py",
    "start_gesture_bridge.sh",
    "一键启动桥接.sh",
]


def main() -> int:
    a = paramiko.SSHClient()
    a.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    a.connect(
        "192.168.42.4",
        username="aidlux",
        password="aidlux",
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = a.open_sftp()
    for d in ("/home/aidlux/sc171v2_agent", "/home/aidlux/Desktop/sc171v2_jetarm"):
        for name in FILES:
            local = os.path.join(HERE, name)
            if os.path.isfile(local):
                sftp.put(local, f"{d}/{name}")
                print("put", d, name)
    sftp.close()
    _i, o, e = a.exec_command(
        "echo aidlux | sudo -S -p '' bash -lc '"
        "pkill -9 -f sc171v2_servo_bridge.py || true; sleep 2; "
        ": > /tmp/sc171v2_servo_bridge.log; "
        "cd /home/aidlux/Desktop/sc171v2_jetarm; "
        "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
        "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
        "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
        "--drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 "
        ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo $! > /tmp/sc171v2_servo_bridge.pid; "
        "sleep 4; ps -p $(cat /tmp/sc171v2_servo_bridge.pid) -o pid,cmd; "
        "grep -E \"H0-FOLLOW|home|initial|poll=\" /tmp/sc171v2_servo_bridge.log | head -20'",
        timeout=60,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"))
    a.close()

    dist = os.path.join(ROOT, "frontend", "dist")
    archive = os.path.join(tempfile.gettempdir(), "hr-home-init.tgz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(dist, arcname="dist")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        "121.41.67.80",
        username="root",
        password="Slhy060922",
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    sftp.put(archive, "/tmp/hr-home-init.tgz")
    sftp.put(
        os.path.join(ROOT, "backend", "app", "services", "arm_state.py"),
        "/opt/hand-recognition/backend/app/services/arm_state.py",
    )
    sftp.close()
    _i, o, e = c.exec_command(
        "rm -rf /opt/hand-recognition/frontend/dist; "
        "tar -xzf /tmp/hr-home-init.tgz -C /opt/hand-recognition/frontend; "
        "systemctl restart arm-backend || true; sleep 2; "
        "curl -sS -X POST http://127.0.0.1:8000/api/control/reset "
        "-H 'Content-Type: application/json' -d '{}' | head -c 220; echo",
        timeout=60,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"))
    c.close()

    time.sleep(1.5)
    st = json.loads(
        urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8).read()
    )
    home = json.load(open(os.path.join(HERE, "home_pose.json"), encoding="utf-8"))[
        "joints_deg"
    ]
    init = json.load(open(os.path.join(HERE, "initial_pose.json"), encoding="utf-8"))[
        "joints_deg"
    ]
    print("HOME(Z)", home)
    print("INITIAL", init)
    print(
        "cloud online=",
        st.get("device_online"),
        "actual=",
        st.get("actual"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
