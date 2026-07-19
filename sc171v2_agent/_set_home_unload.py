#!/usr/bin/env python3
"""Capture live actual as home, sync view map, unload torque for teaching."""
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


def status():
    with urllib.request.urlopen(f"{CLOUD}/api/status", timeout=8) as r:
        return json.loads(r.read().decode())


def main() -> int:
    st = status()
    actual = st.get("actual")
    if not isinstance(actual, list) or len(actual) < 5:
        print("FAIL no actual", st)
        return 1

    home = [round(float(x), 3) for x in actual[:6]]
    while len(home) < 6:
        home.append(45.0)
    if abs(home[5]) < 1e-6:
        home[5] = 45.0
    off = [round(-home[i], 3) for i in range(5)] + [0.0]

    # local home_pose
    home_path = os.path.join(HERE, "home_pose.json")
    open(home_path, "w", encoding="utf-8").write(
        json.dumps(
            {
                "joints_deg": home,
                "note": "taught as current pose; unload for free-move calibrate",
            },
            indent=2,
        )
        + "\n"
    )

    # view map so this pose = Z-line
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
    # refresh comment home line if present
    ktxt = re.sub(
        r" \* home ≈ \[[^\]]*\]  → viewport",
        " * home ≈ [%s]  → viewport"
        % ", ".join(str(x) for x in home),
        ktxt,
        count=1,
    )
    open(kin, "w", encoding="utf-8").write(ktxt)

    # backend default
    as_path = os.path.join(ROOT, "backend", "app", "services", "arm_state.py")
    atxt = open(as_path, encoding="utf-8").read()
    atxt2 = re.sub(
        r"self\.target = \[[^\]]*\]",
        "self.target = [%s]" % ", ".join(str(x) for x in home),
        atxt,
        count=1,
    )
    if atxt2 != atxt:
        open(as_path, "w", encoding="utf-8").write(atxt2)

    print("HOME", home)
    print("OFFSET", off)

    # push to AidLux + unload via MQTT mode idle
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
        sftp.put(home_path, f"{d}/home_pose.json")
    sftp.close()
    # Ask running bridge to unload (idle/hold)
    _i, o, e = a.exec_command(
        "grep -E 'H0-FOLLOW|unload|poll=' /tmp/sc171v2_servo_bridge.log | tail -8; "
        "pgrep -af 'python.*sc171v2_servo_bridge' || echo NO_BRIDGE",
        timeout=15,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"))
    a.close()

    # HTTP reset → emit idle → unload
    for i in range(4):
        try:
            req = urllib.request.Request(
                f"{CLOUD}/api/control/reset",
                method="POST",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            body = urllib.request.urlopen(req, timeout=8).read().decode()
            print("UNLOAD", body[:200])
            break
        except Exception as ex:
            print("unload_retry", i, ex)
            time.sleep(1.2)

    # patch cloud arm_state defaults live
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
    if rtxt2 != rtxt:
        with sftp.open(remote, "w") as f:
            f.write(rtxt2)
        print("cloud arm_state patched")
    sftp.close()
    # no need full restart for unload; status already updated
    c.close()

    st2 = status()
    print(
        "DONE online=",
        st2.get("device_online"),
        "mode=",
        st2.get("mode"),
        "actual=",
        st2.get("actual"),
        "home_saved=",
        home,
    )
    print("You can now freely move the arm to teach a new initial pose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
