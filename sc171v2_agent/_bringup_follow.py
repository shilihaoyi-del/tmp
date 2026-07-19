#!/usr/bin/env python3
"""Kill, start bridge --no-boot-home, sync VIEW to live actual, report."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLOUD = "http://121.41.67.80:8000"


def cloud_status():
    with urllib.request.urlopen(f"{CLOUD}/api/status", timeout=8) as r:
        return json.loads(r.read().decode())


def main() -> int:
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

    def run(cmd, timeout=90):
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(out)
        return out

    # push latest code
    sftp = c.open_sftp()
    for d in ("/home/aidlux/sc171v2_agent", "/home/aidlux/Desktop/sc171v2_jetarm"):
        for name in (
            "sc171v2_servo_bridge.py",
            "home_pose.json",
            "joint_protection.py",
            "arm_kinematics.py",
            "jetarm_packet.py",
        ):
            local = os.path.join(HERE, name)
            if os.path.isfile(local):
                try:
                    sftp.put(local, f"{d}/{name}")
                except Exception as ex:
                    print("PUT_FAIL", d, name, ex)
    sftp.close()

    print("=== STOP ===")
    run(
        "echo aidlux | sudo -S -p '' bash -c '"
        "pkill -9 -f sc171v2_servo_bridge.py || true; "
        "sleep 2; "
        "pgrep -af sc171v2_servo_bridge || echo NO_BRIDGE'"
    )

    print("=== START ===")
    run(
        "echo aidlux | sudo -S -p '' bash -c '"
        ": > /tmp/sc171v2_servo_bridge.log; "
        "cd /home/aidlux/Desktop/sc171v2_jetarm; "
        "PY=python3; "
        "[ -x /home/aidlux/sc171v2_agent/.venv/bin/python ] && "
        "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
        "echo USING=$PY; "
        "PYTHONUNBUFFERED=1 nohup $PY -u ./sc171v2_servo_bridge.py "
        "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
        "--drive jetarm --move-time-ms 1000 --no-boot-home "
        ">>/tmp/sc171v2_servo_bridge.log 2>&1 & "
        "echo PID=$!; "
        "sleep 6; "
        "pgrep -af sc171v2_servo_bridge.py || echo STILL_NO; "
        "echo ===LOG===; "
        "tail -n 60 /tmp/sc171v2_servo_bridge.log'"
    )

    # wait for MQTT status
    actual = None
    for i in range(25):
        try:
            st = cloud_status()
        except Exception as ex:
            print(f"poll{i} ERR {ex}")
            time.sleep(1.5)
            continue
        online = bool(st.get("device_online") or st.get("stm32_online"))
        actual = st.get("actual")
        print(
            f"poll{i} online={online} mode={st.get('mode')} "
            f"hz={st.get('control_hz')} actual={actual}"
        )
        if online and isinstance(actual, list) and len(actual) >= 5:
            break
        time.sleep(1.5)

    if not isinstance(actual, list) or len(actual) < 5:
        print("FAIL: bridge not publishing actual")
        c.close()
        return 1

    home = [round(float(x), 3) for x in actual[:6]]
    while len(home) < 6:
        home.append(45.0)
    if abs(home[5]) < 1e-6:
        home[5] = 45.0
    off = [round(-home[i], 3) for i in range(5)] + [0.0]

    # local home + kinematics
    open(os.path.join(HERE, "home_pose.json"), "w", encoding="utf-8").write(
        json.dumps(
            {
                "joints_deg": home,
                "note": "live actual = web Z-line; follow mode --no-boot-home",
            },
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

    # push home to aidlux
    sftp = c.open_sftp()
    for d in ("/home/aidlux/sc171v2_agent", "/home/aidlux/Desktop/sc171v2_jetarm"):
        sftp.put(os.path.join(HERE, "home_pose.json"), f"{d}/home_pose.json")
    sftp.close()
    c.close()

    print("SYNCED home=", home, "offset=", off)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
