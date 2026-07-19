#!/usr/bin/env python3
"""Deploy fixed desktop bridge launcher + boot-to-initial, then start it."""
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "sc171v2_servo_bridge.py",
    "joint_protection.py",
    "home_pose.json",
    "initial_pose.json",
    "start_gesture_bridge.sh",
    "一键启动桥接.sh",
    "jetarm_packet.py",
    "arm_kinematics.py",
    "ch340_pyusb.py",
]


def main() -> int:
    # keep Chinese launcher in sync
    src = os.path.join(HERE, "start_gesture_bridge.sh")
    dst = os.path.join(HERE, "一键启动桥接.sh")
    open(dst, "wb").write(open(src, "rb").read())

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
                print("put", d, name)
    # desktop wrappers
    sftp.put(os.path.join(HERE, "bridge.desktop"), "/home/aidlux/Desktop/bridge.desktop")
    sftp.close()

    def run(cmd, timeout=120):
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(out)
        return out

    run(
        r"""
chmod +x /home/aidlux/sc171v2_agent/start_gesture_bridge.sh \
  /home/aidlux/Desktop/sc171v2_jetarm/start_gesture_bridge.sh \
  /home/aidlux/Desktop/bridge.desktop 2>/dev/null || true
# mark desktop trusted if possible
gio set /home/aidlux/Desktop/bridge.desktop metadata::trusted true 2>/dev/null || true
# simple Desktop/bridge wrapper
cat > /home/aidlux/Desktop/bridge <<'EOF'
#!/usr/bin/env bash
# Auto bridge + go to initial pose
export KEEP_OPEN=1
exec bash /home/aidlux/sc171v2_agent/start_gesture_bridge.sh "$@"
EOF
chmod +x /home/aidlux/Desktop/bridge
echo WRAPPER_OK
head -n 5 /home/aidlux/Desktop/bridge
grep -n 'boot-pose\|BOOT_POSE\|initial' /home/aidlux/sc171v2_agent/start_gesture_bridge.sh | head
"""
    )

    print("=== RUN LAUNCHER (boot initial) ===")
    # non-interactive run
    run(
        "export KEEP_OPEN=0; bash /home/aidlux/sc171v2_agent/start_gesture_bridge.sh",
        timeout=90,
    )
    c.close()

    time.sleep(8)
    st = json.loads(
        urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8).read()
    )
    init = json.load(open(os.path.join(HERE, "initial_pose.json"), encoding="utf-8"))[
        "joints_deg"
    ]
    print("TARGET_INITIAL", init)
    print(
        "cloud online=",
        st.get("device_online"),
        "actual=",
        st.get("actual"),
        "mode=",
        st.get("mode"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
