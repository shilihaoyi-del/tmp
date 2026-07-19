#!/usr/bin/env python3
import os
import tarfile
import tempfile

import paramiko

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "frontend", "dist")
archive = os.path.join(tempfile.gettempdir(), "hr-fe-model.tgz")
with tarfile.open(archive, "w:gz") as tar:
    tar.add(DIST, arcname="dist")

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
sftp.put(archive, "/tmp/hr-fe-model.tgz")
sftp.close()
_, o, e = c.exec_command(
    "rm -rf /opt/hand-recognition/frontend/dist && "
    "tar -xzf /tmp/hr-fe-model.tgz -C /opt/hand-recognition/frontend && "
    "ls -la /opt/hand-recognition/frontend/dist/assets | head -10 && "
    "echo OK",
    timeout=60,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()
