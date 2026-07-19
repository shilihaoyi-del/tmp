#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))

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
    sftp.put(os.path.join(HERE, "sc171v2_servo_bridge.py"), f"{d}/sc171v2_servo_bridge.py")
sftp.close()


def run(cmd, timeout=90):
    _i, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    print(out)
    return out


print("=== KILL ===")
run(
    "echo aidlux | sudo -S -p '' bash -c 'pkill -9 -f sc171v2_servo_bridge.py || true; sleep 2; "
    "pgrep -af sc171v2_servo_bridge.py || echo NO_BRIDGE'"
)

print("=== SYNTAX ===")
run(
    "/home/aidlux/sc171v2_agent/.venv/bin/python -m py_compile "
    "/home/aidlux/Desktop/sc171v2_jetarm/sc171v2_servo_bridge.py && echo SYNTAX_OK"
)

print("=== START ===")
# Use a login-like env; write pid explicitly
run(
    "echo aidlux | sudo -S -p '' bash -lc '"
    "set -e; "
    ": > /tmp/sc171v2_servo_bridge.log; "
    "cd /home/aidlux/Desktop/sc171v2_jetarm; "
    "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
    "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
    "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
    "--drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 "
    ">/tmp/sc171v2_servo_bridge.log 2>&1 & "
    "echo $! > /tmp/sc171v2_servo_bridge.pid; "
    "echo STARTED_PID=$(cat /tmp/sc171v2_servo_bridge.pid); "
    "sleep 4; "
    "ps -p $(cat /tmp/sc171v2_servo_bridge.pid) -o pid,cmd || echo DEAD; "
    "echo ===LOG===; "
    "head -n 40 /tmp/sc171v2_servo_bridge.log; "
    "echo ===TAIL===; "
    "tail -n 15 /tmp/sc171v2_servo_bridge.log'"
)

time.sleep(2)
# unload
try:
    req = urllib.request.Request(
        "http://121.41.67.80:8000/api/control/reset",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=8).read()
except Exception as ex:
    print("reset_fail", ex)

seqs = []
st = None
t0 = time.time()
while time.time() - t0 < 4.0:
    st = json.loads(
        urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5)
        .read()
        .decode()
    )
    seqs.append(st.get("seq"))
    time.sleep(0.12)
uniq = len(set(seqs))
print(
    "RATE unique_seq=%s hz~%.1f online=%s actual=%s"
    % (
        uniq,
        (uniq - 1) / 4.0 if uniq > 1 else 0.0,
        st.get("device_online") if st else None,
        st.get("actual") if st else None,
    )
)
c.close()
