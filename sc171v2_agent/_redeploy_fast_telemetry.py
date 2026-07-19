#!/usr/bin/env python3
"""Push faster telemetry bridge + FE + cloud mqtt qos tweak; keep unloaded follow."""
from __future__ import annotations

import json
import os
import tarfile
import tempfile
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "frontend", "dist")


def main() -> int:
    # --- AidLux bridge ---
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

    def arun(cmd, timeout=90):
        _i, o, e = a.exec_command(cmd, timeout=timeout)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(out)
        return out

    sftp = a.open_sftp()
    for d in ("/home/aidlux/sc171v2_agent", "/home/aidlux/Desktop/sc171v2_jetarm"):
        sftp.put(
            os.path.join(HERE, "sc171v2_servo_bridge.py"),
            f"{d}/sc171v2_servo_bridge.py",
        )
    sftp.close()

    print("=== RESTART BRIDGE (fast poll, no-boot-home) ===")
    arun(
        "echo aidlux | sudo -S -p '' bash -c '"
        "pkill -9 -f sc171v2_servo_bridge.py || true; "
        "sleep 2; "
        ": > /tmp/sc171v2_servo_bridge.log; "
        "cd /home/aidlux/Desktop/sc171v2_jetarm; "
        "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
        "[ -x $PY ] || PY=python3; "
        "PYTHONUNBUFFERED=1 nohup $PY -u ./sc171v2_servo_bridge.py "
        "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
        "--drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 "
        ">>/tmp/sc171v2_servo_bridge.log 2>&1 & echo PID=$!; "
        "sleep 5; "
        "pgrep -af sc171v2_servo_bridge.py || echo STILL_NO; "
        "grep -E \"poll=|H0-FOLLOW|H0-READY|FATAL\" /tmp/sc171v2_servo_bridge.log | tail -20'"
    )

    # unload again for free-move test
    time.sleep(1.0)
    try:
        req = urllib.request.Request(
            "http://121.41.67.80:8000/api/control/reset",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        print("UNLOAD", urllib.request.urlopen(req, timeout=8).read().decode()[:180])
    except Exception as ex:
        print("UNLOAD_FAIL", ex)

    # --- Cloud backend mqtt client + frontend ---
    archive = os.path.join(tempfile.gettempdir(), "hr-fe-fast.tgz")
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

    def crun(cmd, timeout=120):
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(out)
        return out

    sftp = c.open_sftp()
    sftp.put(archive, "/tmp/hr-fe-fast.tgz")
    sftp.put(
        os.path.join(ROOT, "backend", "app", "mqtt", "client.py"),
        "/opt/hand-recognition/backend/app/mqtt/client.py",
    )
    sftp.close()
    crun(
        "set -e; "
        "rm -rf /opt/hand-recognition/frontend/dist; "
        "tar -xzf /tmp/hr-fe-fast.tgz -C /opt/hand-recognition/frontend; "
        "systemctl restart arm-backend || true; "
        "sleep 2; "
        "curl -sS http://127.0.0.1:8000/api/status | head -c 280; echo"
    )
    c.close()
    a.close()

    # measure status update rate ~3s
    seqs = []
    t0 = time.time()
    while time.time() - t0 < 3.0:
        st = json.loads(
            urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5)
            .read()
            .decode()
        )
        seqs.append(st.get("seq"))
        time.sleep(0.15)
    uniq = len(set(seqs))
    print(
        "RATE_CHECK samples=%s unique_seq=%s hz~%.1f online=%s actual=%s"
        % (
            len(seqs),
            uniq,
            (uniq - 1) / 3.0 if uniq > 1 else 0.0,
            st.get("device_online"),
            st.get("actual"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
