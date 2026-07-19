#!/usr/bin/env python3
"""Wait for bridge online and print actual; optionally re-sync VIEW."""
from __future__ import annotations

import json
import re
import time
import urllib.request

import paramiko

AIDLUX = dict(hostname="192.168.42.4", username="aidlux", password="aidlux", port=22)
CLOUD = "http://121.41.67.80:8000"
KT = "frontend/src/lib/kinematics.ts"
HOME = "sc171v2_agent/home_pose.json"
ROOT = r"C:\Users\shi\Desktop\hand-recognition"


def status():
    with urllib.request.urlopen(f"{CLOUD}/api/status", timeout=8) as r:
        return json.loads(r.read().decode())


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(**AIDLUX, timeout=15, allow_agent=False, look_for_keys=False)
    _, o, _ = c.exec_command(
        "pgrep -af sc171v2_servo_bridge; echo ---; tail -n 40 /tmp/servo_bridge.log",
        timeout=20,
    )
    print(o.read().decode(errors="replace"))
    c.close()

    online = False
    actual = None
    for i in range(20):
        st = status()
        online = bool(st.get("online"))
        actual = st.get("actual_joints_deg")
        print(f"poll{i} online={online} mode={st.get('mode')} actual={actual}")
        if online and actual:
            break
        time.sleep(1.5)

    if not actual:
        print("NO_ACTUAL")
        return

    path = f"{ROOT}/{KT}"
    text = open(path, encoding="utf-8").read()
    text = re.sub(
        r"export const VIEW_HOME_JOINTS_DEG = \[[^\]]+\] as const;",
        "export const VIEW_HOME_JOINTS_DEG = ["
        + ", ".join(f"{float(v):.2f}" for v in actual)
        + "] as const;",
        text,
        count=1,
    )
    offsets = [-float(v) for v in actual[:5]] + [0.0]
    text = re.sub(
        r"export const VIEW_JOINT_OFFSET_DEG = \[[^\]]+\] as const;",
        "export const VIEW_JOINT_OFFSET_DEG = ["
        + ", ".join(f"{v:.2f}" for v in offsets)
        + "] as const;",
        text,
        count=1,
    )
    open(path, "w", encoding="utf-8").write(text)
    open(f"{ROOT}/{HOME}", "w", encoding="utf-8").write(
        json.dumps(
            {
                "joints_deg": [round(float(v), 2) for v in actual],
                "note": "synced with live actual for web Z-line + follow",
            },
            indent=2,
        )
        + "\n"
    )
    print("SYNCED", actual, "offsets", offsets)


if __name__ == "__main__":
    main()
