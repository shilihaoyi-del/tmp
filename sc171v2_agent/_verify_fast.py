#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.request

import paramiko

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
_, o, e = c.exec_command(
    "pgrep -af sc171v2_servo_bridge.py || echo NO_BRIDGE; echo ===; "
    "tail -n 40 /tmp/sc171v2_servo_bridge.log",
    timeout=25,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()

last = None
seqs = []
t0 = time.time()
while time.time() - t0 < 4.0:
    st = json.loads(
        urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5)
        .read()
        .decode()
    )
    last = st
    seqs.append(st.get("seq"))
    time.sleep(0.12)

uniq = sorted(set(s for s in seqs if s is not None))
print(
    "online=%s mode=%s unique_seq=%s (~%.1fHz) actual=%s"
    % (
        last.get("device_online") or last.get("stm32_online"),
        last.get("mode"),
        len(uniq),
        (len(uniq) - 1) / 4.0 if len(uniq) > 1 else 0.0,
        last.get("actual"),
    )
)
