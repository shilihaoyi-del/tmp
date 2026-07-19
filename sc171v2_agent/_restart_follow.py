#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.42.4", username="aidlux", password="aidlux", timeout=12)

    def run(cmd, timeout=60):
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    # ensure latest bridge on both dirs
    sftp = c.open_sftp()
    for d in (
        "/home/aidlux/sc171v2_agent",
        "/home/aidlux/Desktop/sc171v2_jetarm",
    ):
        sftp.put(
            os.path.join(HERE, "sc171v2_servo_bridge.py"),
            d + "/sc171v2_servo_bridge.py",
        )
        sftp.put(os.path.join(HERE, "home_pose.json"), d + "/home_pose.json")
        sftp.put(
            os.path.join(HERE, "joint_protection.py"), d + "/joint_protection.py"
        )
    sftp.close()

    print(
        run(
            "echo aidlux | sudo -S -p '' bash -c '"
            "pkill -9 -f sc171v2_servo_bridge.py || true; "
            "sleep 2; "
            "pgrep -af sc171v2_servo_bridge || echo NO_BRIDGE; "
            ": > /tmp/sc171v2_servo_bridge.log; "
            "cd /home/aidlux/Desktop/sc171v2_jetarm; "
            "PY=python3; "
            "[ -x /home/aidlux/sc171v2_agent/.venv/bin/python ] && "
            "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
            "PYTHONUNBUFFERED=1 nohup $PY -u ./sc171v2_servo_bridge.py "
            "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
            "--drive jetarm --move-time-ms 1000 --no-boot-home "
            ">>/tmp/sc171v2_servo_bridge.log 2>&1 & echo PID=$!; "
            "sleep 5; "
            "pgrep -af sc171v2_servo_bridge || echo STILL_NO; "
            "grep -E \"H0-FOLLOW|H0-READY|ERR|FATAL|no_boot\" /tmp/sc171v2_servo_bridge.log | tail -20; "
            "tail -n 15 /tmp/sc171v2_servo_bridge.log'"
        )
    )
    c.close()

    time.sleep(2)
    try:
        with urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5) as r:
            st = json.loads(r.read().decode())
        print(
            "CLOUD",
            "online=",
            st.get("device_online") or st.get("stm32_online"),
            "actual=",
            st.get("actual"),
        )
        actual = st.get("actual")
        if isinstance(actual, list) and len(actual) >= 6:
            home = [round(float(x), 3) for x in actual[:6]]
            if abs(home[5]) < 1e-6:
                home[5] = 45.0
            # refresh view home to live actual
            off = [round(-home[i], 3) for i in range(5)] + [0.0]
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
            print("VIEW_HOME_UPDATED", home, "OFFSET", off)
    except Exception as e:
        print("CLOUD_FAIL", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
