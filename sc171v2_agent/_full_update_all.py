#!/usr/bin/env python3
"""Full sync: AidLux bridge + Desktop launcher + cloud FE/backend + restart follow."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

AIDLUX_FILES = [
    "sc171v2_servo_bridge.py",
    "jetarm_packet.py",
    "joint_protection.py",
    "arm_kinematics.py",
    "ch340_pyusb.py",
    "hiwonder_servo.py",
    "uart_protocol.py",
    "home_pose.json",
    "base_limit_cal.json",
    "nonbase_limit_cal.json",
    "start_gesture_bridge.sh",
    "一键启动桥接.sh",
    "start_servo_bridge.sh",
    "keepalive.sh",
    "restart_bridge_safe.sh",
    "free_move_cloud.py",
    "free_move_read.py",
    "sc171v2_mqtt_agent.py",
]

CLOUD_PY = [
    ("backend/app/mqtt/client.py", "/opt/hand-recognition/backend/app/mqtt/client.py"),
    ("backend/app/services/arm_state.py", "/opt/hand-recognition/backend/app/services/arm_state.py"),
    ("backend/app/models/schemas.py", "/opt/hand-recognition/backend/app/models/schemas.py"),
]


def ssh_connect(host, user, password):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        host,
        username=user,
        password=password,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c, cmd, timeout=90):
    _i, o, e = c.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    print(out)
    return out


def main() -> int:
    # 1) build frontend
    print("=== BUILD FRONTEND ===")
    fe = os.path.join(ROOT, "frontend")
    r = subprocess.run(
        ["npm", "run", "build"],
        cwd=fe,
        shell=True,
        capture_output=True,
        text=True,
    )
    print(r.stdout[-800:] if r.stdout else "")
    if r.returncode != 0:
        print(r.stderr)
        return 1

    # 2) AidLux sync
    print("=== SYNC AIDLUX ===")
    a = ssh_connect("192.168.42.4", "aidlux", "aidlux")
    sftp = a.open_sftp()
    for d in ("/home/aidlux/sc171v2_agent", "/home/aidlux/Desktop/sc171v2_jetarm"):
        try:
            sftp.stat(d)
        except OSError:
            run(a, f"mkdir -p {d}")
        for name in AIDLUX_FILES:
            local = os.path.join(HERE, name)
            if not os.path.isfile(local):
                print("skip missing", name)
                continue
            remote = f"{d}/{name}"
            sftp.put(local, remote)
            print("put", remote)
    sftp.close()

    run(
        a,
        r"""
chmod +x /home/aidlux/sc171v2_agent/*.sh /home/aidlux/Desktop/sc171v2_jetarm/*.sh 2>/dev/null || true
cat > /home/aidlux/Desktop/bridge <<'EOF'
#!/usr/bin/env bash
exec bash /home/aidlux/sc171v2_agent/start_gesture_bridge.sh "$@"
EOF
chmod +x /home/aidlux/Desktop/bridge
echo DESKTOP_BRIDGE_OK
""",
    )

    # 3) restart bridge follow mode
    print("=== RESTART BRIDGE ===")
    run(
        a,
        "echo aidlux | sudo -S -p '' bash -lc '"
        "pkill -9 -f sc171v2_servo_bridge.py || true; "
        "pkill -9 -f free_move_cloud.py || true; "
        "pkill -9 -f sc171v2_mqtt_agent.py || true; "
        "sleep 2; "
        ": > /tmp/sc171v2_servo_bridge.log; "
        "cd /home/aidlux/Desktop/sc171v2_jetarm; "
        "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
        "[ -x $PY ] || PY=python3; "
        "nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py "
        "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
        "--drive jetarm --move-time-ms 1000 --no-boot-home --poll-interval 0.12 "
        ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo $! > /tmp/sc171v2_servo_bridge.pid; "
        "echo PID=$(cat /tmp/sc171v2_servo_bridge.pid); sleep 4; "
        "ps -p $(cat /tmp/sc171v2_servo_bridge.pid) -o pid,cmd; "
        "grep -E \"poll=|H0-FOLLOW|H0-READY|FATAL|Error\" /tmp/sc171v2_servo_bridge.log | head -25'",
    )
    a.close()

    # 4) cloud FE + backend files
    print("=== DEPLOY CLOUD ===")
    dist = os.path.join(ROOT, "frontend", "dist")
    archive = os.path.join(tempfile.gettempdir(), "hr-full-fe.tgz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(dist, arcname="dist")

    cloud = ssh_connect("121.41.67.80", "root", "Slhy060922")
    sftp = cloud.open_sftp()
    sftp.put(archive, "/tmp/hr-full-fe.tgz")
    for rel, remote in CLOUD_PY:
        local = os.path.join(ROOT, *rel.split("/"))
        if os.path.isfile(local):
            sftp.put(local, remote)
            print("put cloud", remote)
    sftp.close()
    run(
        cloud,
        "set -e; "
        "rm -rf /opt/hand-recognition/frontend/dist; "
        "tar -xzf /tmp/hr-full-fe.tgz -C /opt/hand-recognition/frontend; "
        "systemctl restart arm-backend || true; "
        "sleep 2; "
        "curl -sS -o /dev/null -w 'health=%{http_code}\\n' http://127.0.0.1:8000/api/health; "
        "curl -sS -X POST http://127.0.0.1:8000/api/control/reset "
        "-H 'Content-Type: application/json' -d '{}' | head -c 220; echo",
        timeout=60,
    )
    cloud.close()

    # 5) verify
    print("=== VERIFY ===")
    time.sleep(1.5)
    st = None
    for i in range(8):
        try:
            st = json.loads(
                urllib.request.urlopen(
                    "http://121.41.67.80:8000/api/status", timeout=6
                ).read()
            )
            if st.get("device_online") or st.get("stm32_online"):
                break
        except Exception as ex:
            print("poll", i, ex)
        time.sleep(1)
    if not st:
        print("VERIFY_FAIL no status")
        return 1
    print(
        "online=",
        st.get("device_online") or st.get("stm32_online"),
        "mode=",
        st.get("mode"),
        "hb_age=",
        st.get("hb_age_ms"),
        "actual=",
        st.get("actual"),
    )
    print("DONE: Desktop/bridge + cloud FE updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
