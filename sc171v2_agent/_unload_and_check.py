#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.request

import paramiko

# fix cloud if 502
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
_, o, e = c.exec_command(
    "systemctl restart arm-backend; sleep 2; "
    "curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health; echo; "
    "curl -sS -X POST http://127.0.0.1:8000/api/control/reset -H 'Content-Type: application/json' -d '{}'; "
    "head -c 200; echo",
    timeout=40,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()

# also ask AidLux to publish unload via mqtt if needed
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
_, o, e = a.exec_command(
    "grep -E 'unload|H0-FOLLOW|poll=' /tmp/sc171v2_servo_bridge.log | tail -15; "
    "echo ---; ps -p $(cat /tmp/sc171v2_servo_bridge.pid 2>/dev/null) -o pid,etime,cmd 2>/dev/null || "
    "pgrep -af 'python.*sc171v2_servo_bridge'",
    timeout=20,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
a.close()

time.sleep(0.5)
# public unload
for i in range(3):
    try:
        req = urllib.request.Request(
            "http://121.41.67.80:8000/api/control/reset",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        print("RESET", urllib.request.urlopen(req, timeout=8).read().decode()[:180])
        break
    except Exception as ex:
        print("retry", i, ex)
        time.sleep(1.5)

# rate via hb_age freshness over samples
ages = []
t0 = time.time()
while time.time() - t0 < 2.5:
    st = json.loads(
        urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5).read()
    )
    ages.append(st.get("hb_age_ms"))
    time.sleep(0.15)
print(
    "online",
    st.get("device_online"),
    "min_hb_age",
    min(ages),
    "max_hb_age",
    max(ages),
    "actual",
    st.get("actual"),
)
