#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
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
        sftp.put(
            os.path.join(HERE, "sc171v2_servo_bridge.py"),
            f"{d}/sc171v2_servo_bridge.py",
        )
    sftp.close()

    # Write a small launcher on device to avoid nested-quote hell
    launcher = """#!/bin/bash
set -e
pkill -9 -f sc171v2_servo_bridge.py || true
sleep 2
: > /tmp/sc171v2_servo_bridge.log
cd /home/aidlux/Desktop/sc171v2_jetarm
PY=/home/aidlux/sc171v2_agent/.venv/bin/python
[ -x "$PY" ] || PY=python3
export PYTHONUNBUFFERED=1
nohup "$PY" -u ./sc171v2_servo_bridge.py \\
  --host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi \\
  --drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 \\
  >>/tmp/sc171v2_servo_bridge.log 2>&1 &
echo PID=$!
sleep 4
pgrep -af sc171v2_servo_bridge.py || echo STILL_NO
echo '---LOG---'
head -n 30 /tmp/sc171v2_servo_bridge.log
echo '---TAIL---'
tail -n 20 /tmp/sc171v2_servo_bridge.log
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/start_fast_bridge.sh", "w") as f:
        f.write(launcher)
    sftp.close()

    _i, o, e = c.exec_command(
        "echo aidlux | sudo -S -p '' bash /tmp/start_fast_bridge.sh",
        timeout=60,
    )
    print((o.read() + e.read()).decode("utf-8", "replace"))
    c.close()

    time.sleep(2)
    try:
        req = urllib.request.Request(
            "http://121.41.67.80:8000/api/control/reset",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        print("RESET", urllib.request.urlopen(req, timeout=8).read().decode()[:200])
    except Exception as ex:
        print("RESET_FAIL", ex)

    seqs = []
    last = None
    t0 = time.time()
    while time.time() - t0 < 4.0:
        last = json.loads(
            urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5)
            .read()
            .decode()
        )
        seqs.append(last.get("seq"))
        time.sleep(0.12)
    uniq = sorted(set(s for s in seqs if s is not None))
    print(
        "online=%s unique_seq=%s hz~%.1f actual=%s"
        % (
            last.get("device_online") or last.get("stm32_online"),
            len(uniq),
            (len(uniq) - 1) / 4.0 if len(uniq) > 1 else 0.0,
            last.get("actual"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
