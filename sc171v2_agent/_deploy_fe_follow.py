#!/usr/bin/env python3
"""Upload frontend/dist + sync arm_state defaults; restart arm-backend lightly."""
from __future__ import annotations

import json
import os
import tarfile
import tempfile
import time
import urllib.request

import paramiko

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "frontend", "dist")
CLOUD = dict(hostname="121.41.67.80", username="root", password="Slhy060922", port=22)
HOME = [-0.48, -87.12, 3.12, -154.8, -4.08, 45.0]


def main() -> int:
    if not os.path.isdir(DIST):
        raise SystemExit("missing frontend/dist — run npm run build first")

    archive = os.path.join(tempfile.gettempdir(), "hr-frontend-dist.tgz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(DIST, arcname="dist")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(**CLOUD, timeout=20, allow_agent=False, look_for_keys=False)

    def run(cmd, timeout=120):
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(out)
        return out

    sftp = c.open_sftp()
    sftp.put(archive, "/tmp/hr-frontend-dist.tgz")
    # patch arm_state defaults if present
    remote_as = "/opt/hand-recognition/backend/app/services/arm_state.py"
    try:
        with sftp.open(remote_as, "r") as f:
            txt = f.read().decode("utf-8")
        import re

        txt2 = re.sub(
            r"self\.target = \[[^\]]*\]",
            "self.target = [%s]" % ", ".join(str(x) for x in HOME),
            txt,
            count=1,
        )
        if "self.actual" in txt2:
            txt2 = re.sub(
                r"self\.actual = \[[^\]]*\]",
                "self.actual = [%s]" % ", ".join(str(x) for x in HOME),
                txt2,
                count=1,
            )
        if txt2 != txt:
            with sftp.open(remote_as, "w") as f:
                f.write(txt2)
            print("arm_state defaults patched")
        else:
            print("arm_state already ok / no patch needed")
    except Exception as ex:
        print("arm_state patch skip:", ex)
    sftp.close()

    run(
        "set -e; "
        "mkdir -p /opt/hand-recognition/frontend; "
        "rm -rf /opt/hand-recognition/frontend/dist; "
        "tar -xzf /tmp/hr-frontend-dist.tgz -C /opt/hand-recognition/frontend; "
        "systemctl restart arm-backend || "
        "(cd /opt/hand-recognition/backend && "
        " pkill -f 'uvicorn app.main' || true; "
        " sleep 1; "
        " nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 "
        " >/tmp/arm-backend.log 2>&1 &); "
        "sleep 2; "
        "curl -sS http://127.0.0.1:8000/api/status | head -c 400; echo"
    )
    c.close()

    time.sleep(1)
    with urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=8) as r:
        st = json.loads(r.read().decode())
    print(
        "PUBLIC",
        "online=",
        st.get("device_online") or st.get("stm32_online"),
        "actual=",
        st.get("actual"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
