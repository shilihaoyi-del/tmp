#!/usr/bin/env python3
"""Push unload-on-follow bridge, restart, MQTT-unload, measure freshness."""
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

try:
    import paho.mqtt.publish as publish
except Exception:
    publish = None

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
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
        sftp.put(
            os.path.join(HERE, "sc171v2_servo_bridge.py"),
            f"{d}/sc171v2_servo_bridge.py",
        )
    sftp.close()

    def run(cmd, timeout=60):
        _i, o, e = a.exec_command(cmd, timeout=timeout)
        out = (o.read() + e.read()).decode("utf-8", "replace")
        print(out)
        return out

    run(
        "echo aidlux | sudo -S -p '' bash -lc '"
        "pkill -9 -f sc171v2_servo_bridge.py || true; sleep 2; "
        ": > /tmp/sc171v2_servo_bridge.log; "
        "cd /home/aidlux/Desktop/sc171v2_jetarm; "
        "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
        "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
        "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
        "--drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 "
        ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo $! > /tmp/sc171v2_servo_bridge.pid; "
        "echo PID=$(cat /tmp/sc171v2_servo_bridge.pid); sleep 4; "
        "ps -p $(cat /tmp/sc171v2_servo_bridge.pid) -o pid,cmd; "
        "grep -E \"poll=|H0-FOLLOW|unload|FATAL\" /tmp/sc171v2_servo_bridge.log | head -20'"
    )
    a.close()

    # MQTT unload (bypass HTTP if 502)
    if publish is not None:
        payload = json.dumps(
            {"mode": "idle", "estop": False, "ts_ms": int(time.time() * 1000), "seq": 1}
        )
        try:
            publish.single(
                "arm/device/mode",
                payload,
                hostname="121.41.67.80",
                port=1883,
                qos=1,
                retain=True,
            )
            print("MQTT_UNLOAD_OK")
        except Exception as ex:
            print("MQTT_UNLOAD_FAIL", ex)

    for i in range(5):
        try:
            req = urllib.request.Request(
                "http://121.41.67.80:8000/api/control/reset",
                method="POST",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            print("HTTP_RESET", urllib.request.urlopen(req, timeout=6).read().decode()[:160])
            break
        except Exception as ex:
            print("HTTP_RESET_retry", i, ex)
            time.sleep(1)

    ages = []
    st = None
    t0 = time.time()
    while time.time() - t0 < 2.5:
        try:
            st = json.loads(
                urllib.request.urlopen(
                    "http://121.41.67.80:8000/api/status", timeout=5
                ).read()
            )
            ages.append(float(st.get("hb_age_ms") or 9999))
        except Exception as ex:
            print("status_err", ex)
        time.sleep(0.15)
    if st:
        print(
            "OK online=%s min_hb=%.0f max_hb=%.0f actual=%s"
            % (
                st.get("device_online"),
                min(ages) if ages else -1,
                max(ages) if ages else -1,
                st.get("actual"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
