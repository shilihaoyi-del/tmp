#!/usr/bin/env python3
"""Sync bridge py + start script to AidLux Desktop launcher."""
from __future__ import annotations

import os

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "sc171v2_servo_bridge.py",
    "start_gesture_bridge.sh",
    "一键启动桥接.sh",
    "home_pose.json",
    "joint_protection.py",
    "arm_kinematics.py",
    "jetarm_packet.py",
]

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
sftp.close()

# Refresh Desktop/bridge wrapper if present
_, o, e = c.exec_command(
    r"""
set -e
chmod +x /home/aidlux/sc171v2_agent/start_gesture_bridge.sh \
  /home/aidlux/Desktop/sc171v2_jetarm/start_gesture_bridge.sh \
  /home/aidlux/sc171v2_agent/一键启动桥接.sh 2>/dev/null || true
# Desktop/bridge: rewrite to call updated script
if [ -e /home/aidlux/Desktop/bridge ] || [ -L /home/aidlux/Desktop/bridge ]; then
  cat > /home/aidlux/Desktop/bridge <<'EOF'
#!/usr/bin/env bash
exec bash /home/aidlux/sc171v2_agent/start_gesture_bridge.sh "$@"
EOF
  chmod +x /home/aidlux/Desktop/bridge
  echo DESKTOP_BRIDGE_UPDATED
else
  cat > /home/aidlux/Desktop/bridge <<'EOF'
#!/usr/bin/env bash
exec bash /home/aidlux/sc171v2_agent/start_gesture_bridge.sh "$@"
EOF
  chmod +x /home/aidlux/Desktop/bridge
  echo DESKTOP_BRIDGE_CREATED
fi
head -n 5 /home/aidlux/Desktop/bridge
grep -n "no-boot-home\|poll-interval\|BOOT_HOME" /home/aidlux/sc171v2_agent/start_gesture_bridge.sh | head
""",
    timeout=30,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()
