#!/usr/bin/env python3
import os
import tarfile
import tempfile
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

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
    for name in ("home_pose.json", "joint_protection.py"):
        sftp.put(os.path.join(HERE, name), f"{d}/{name}")
sftp.close()
a.close()

dist = os.path.join(ROOT, "frontend", "dist")
archive = os.path.join(tempfile.gettempdir(), "hr-home-fe.tgz")
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
sftp.put(archive, "/tmp/hr-home-fe.tgz")
sftp.close()
_i, o, e = c.exec_command(
    "rm -rf /opt/hand-recognition/frontend/dist; "
    "tar -xzf /tmp/hr-home-fe.tgz -C /opt/hand-recognition/frontend; "
    "curl -sS -X POST http://127.0.0.1:8000/api/control/reset "
    "-H 'Content-Type: application/json' -d '{}' | head -c 180; echo",
    timeout=40,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()

st = urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8).read()
print(st.decode()[:280])
