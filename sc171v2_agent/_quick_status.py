#!/usr/bin/env python3
import json
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
cmd = r"""
pid=$(cat /tmp/sc171v2_servo_bridge.pid 2>/dev/null || true)
if [ -n "$pid" ]; then ps -p "$pid" -o pid,etime,cmd; else echo NO_PID_FILE; fi
pgrep -af 'python.*sc171v2_servo_bridge' || true
echo ---
grep -E 'poll=|H0-FOLLOW|unload' /tmp/sc171v2_servo_bridge.log | tail -20
echo ---
wc -l /tmp/sc171v2_servo_bridge.log
"""
_, o, e = c.exec_command(cmd, timeout=20)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()
st = json.loads(urllib.request.urlopen("http://121.41.67.80:8000/api/status", timeout=5).read())
print("cloud online=", st.get("device_online"), "hb=", st.get("hb_age_ms"), "actual=", st.get("actual"))
