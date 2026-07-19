#!/usr/bin/env python3
"""Upload and run remote unload script on AidLux."""
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = "/tmp/_do_unload.sh"

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
# ensure free_move_read exists on desktop copy
for name in ("free_move_read.py", "jetarm_packet.py", "joint_protection.py"):
    local = os.path.join(HERE, name)
    if os.path.isfile(local):
        sftp.put(local, f"/home/aidlux/Desktop/sc171v2_jetarm/{name}")
        sftp.put(local, f"/home/aidlux/sc171v2_agent/{name}")
sftp.put(os.path.join(HERE, "_do_unload.sh"), REMOTE)
sftp.close()

_, o, e = c.exec_command(
    f"chmod +x {REMOTE}; echo aidlux | sudo -S -p '' bash {REMOTE}",
    timeout=90,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()

time.sleep(1)
try:
    st = json.loads(
        urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8).read()
    )
    print(
        "online=",
        st.get("device_online"),
        "mode=",
        st.get("mode"),
        "actual=",
        st.get("actual"),
    )
except Exception as ex:
    print("STATUS_FAIL", ex)
