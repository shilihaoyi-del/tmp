#!/usr/bin/env python3
"""Re-sample actual a few times, lock median as home, sync + unload + restart follow."""
from __future__ import annotations

import json
import os
import re
import statistics
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLOUD = "http://121.41.67.80:8000"


def get_status():
    with urllib.request.urlopen(f"{CLOUD}/api/status", timeout=8) as r:
        return json.loads(r.read().decode())


def main() -> int:
    samples = []
    for _ in range(5):
        st = get_status()
        a = st.get("actual")
        if isinstance(a, list) and len(a) >= 5:
            samples.append([float(x) for x in a[:6]])
        time.sleep(0.2)
    if not samples:
        print("FAIL no samples")
        return 1

    # median per joint
    home = []
    for i in range(6):
        col = [s[i] if i < len(s) else 45.0 for s in samples]
        while len(col[0:1]) and len(col) < len(samples):
            pass
        vals = [s[i] if i < len(s) else 45.0 for s in samples]
        home.append(round(statistics.median(vals), 3))
    if abs(home[5]) < 1e-6:
        home[5] = 45.0
    off = [round(-home[i], 3) for i in range(5)] + [0.0]

    open(os.path.join(HERE, "home_pose.json"), "w", encoding="utf-8").write(
        json.dumps(
            {"joints_deg": home, "note": "user taught initial/home pose"},
            indent=2,
        )
        + "\n"
    )

    kin = os.path.join(ROOT, "frontend", "src", "lib", "kinematics.ts")
    ktxt = open(kin, encoding="utf-8").read()
    ktxt = re.sub(
        r"export const VIEW_HOME_JOINTS_DEG = \[[^\]]*\] as const",
        "export const VIEW_HOME_JOINTS_DEG = [%s] as const"
        % ", ".join(str(x) for x in home),
        ktxt,
        count=1,
    )
    ktxt = re.sub(
        r"export const VIEW_JOINT_OFFSET_DEG = \[[^\]]*\] as const",
        "export const VIEW_JOINT_OFFSET_DEG = [%s] as const"
        % ", ".join(str(x) for x in off),
        ktxt,
        count=1,
    )
    open(kin, "w", encoding="utf-8").write(ktxt)

    as_path = os.path.join(ROOT, "backend", "app", "services", "arm_state.py")
    atxt = open(as_path, encoding="utf-8").read()
    atxt2 = re.sub(
        r"self\.target = \[[^\]]*\]",
        "self.target = [%s]" % ", ".join(str(x) for x in home),
        atxt,
        count=1,
    )
    open(as_path, "w", encoding="utf-8").write(atxt2)

    print("RECORDED_HOME", home)

    # AidLux: push home + restart follow (sets in-memory home from actual, unload)
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
        sftp.put(os.path.join(HERE, "home_pose.json"), f"{d}/home_pose.json")
        sftp.put(
            os.path.join(HERE, "sc171v2_servo_bridge.py"),
            f"{d}/sc171v2_servo_bridge.py",
        )
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
        "grep -E \"H0-FOLLOW|unload|poll=\" /tmp/sc171v2_servo_bridge.log | head -15'",
        timeout=60,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"))
    a.close()

    # cloud patch + unload
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
    remote = "/opt/hand-recognition/backend/app/services/arm_state.py"
    sftp = c.open_sftp()
    with sftp.open(remote, "r") as f:
        rtxt = f.read().decode("utf-8")
    rtxt2 = re.sub(
        r"self\.target = \[[^\]]*\]",
        "self.target = [%s]" % ", ".join(str(x) for x in home),
        rtxt,
        count=1,
    )
    with sftp.open(remote, "w") as f:
        f.write(rtxt2)
    sftp.close()
    _i, o, e = c.exec_command(
        "curl -sS -X POST http://127.0.0.1:8000/api/control/reset "
        "-H 'Content-Type: application/json' -d '{}' | head -c 200; echo",
        timeout=20,
    )
    print("RESET", (o.read() + e.read()).decode("utf-8", "replace"))
    c.close()

    time.sleep(1)
    st = get_status()
    print(
        "OK online=",
        st.get("device_online"),
        "actual=",
        st.get("actual"),
        "home=",
        home,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
