#!/usr/bin/env python3
"""Set home=current pose, deploy view map, start bridge with --no-boot-home."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AIDLUX = ("192.168.42.4", "aidlux", "aidlux")
CLOUD = ("121.41.67.80", "root", "Slhy060922")

REMOTE_READ = r"""
import json, os, sys, time
AGENT="/home/aidlux/sc171v2_agent"
if not os.path.isdir(AGENT): AGENT="/home/aidlux/Desktop/sc171v2_jetarm"
sys.path.insert(0, AGENT); os.chdir(AGENT)
from jetarm_packet import SUB_READ_POSITION, JetArmStreamParser, pack_read_position, pack_unload, parse_bus_servo_report
from probe_read_positions import open_link
from joint_protection import pos_to_deg
link=open_link(None); parser=JetArmStreamParser()
for sid in range(1,7):
  try: link.write(pack_unload(sid))
  except Exception: pass
  time.sleep(0.02)
time.sleep(0.1)
def read_sid(sid):
  for _ in range(5):
    try: link.write(pack_read_position(sid))
    except Exception as e: return None
    deadline=time.time()+0.15
    while time.time()<deadline:
      chunk=link.read(64,timeout_ms=20)
      if not chunk: continue
      for fr in parser.feed(chunk):
        rep=parse_bus_servo_report(fr)
        if not rep or int(rep["servo_id"])!=sid: continue
        if int(rep["sub_cmd"])!=SUB_READ_POSITION: continue
        if int(rep["success"])==0 and len(rep["args"])>=2:
          p=rep["args"][0]|(rep["args"][1]<<8)
          return round(pos_to_deg(p,sid-1),3)
    time.sleep(0.03)
  return None
degs=[read_sid(i) for i in range(1,7)]
print("RAW="+json.dumps(degs))
try: link.close()
except Exception: pass
"""


def main() -> int:
    import sys

    sys.path.insert(0, HERE)
    from joint_protection import clamp_joints_deg, joints_to_positions

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(AIDLUX[0], username=AIDLUX[1], password=AIDLUX[2], timeout=12)

    def run(cmd, timeout=60):
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print(
        run(
            "echo aidlux | sudo -S -p '' bash -c "
            "'pkill -f sc171v2_servo_bridge.py; true'"
        )
    )
    time.sleep(1.0)
    sftp = c.open_sftp()
    with sftp.file("/tmp/follow_read.py", "w") as f:
        f.write(REMOTE_READ)
    out = run(
        "cd /home/aidlux/sc171v2_agent && echo aidlux | sudo -S -p '' "
        "python3 /tmp/follow_read.py"
    )
    print(out)
    raw = json.loads(out.split("RAW=", 1)[1].strip().splitlines()[0])
    default = [-0.48, -88.0, -37.0, -183.0, -4.8, 45.0]
    filled = [default[i] if raw[i] is None else float(raw[i]) for i in range(6)]
    home = [round(x, 3) for x in clamp_joints_deg(filled)]
    print("HOME_NOW", home)

    payload = {
        "name": "home",
        "joints_deg": home,
        "note": "sync follow: current pose = web Z-line; bridge --no-boot-home",
        "status": "follow_sync",
        "command_pulses": joints_to_positions(home),
    }
    with open(os.path.join(HERE, "home_pose.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    jp = open(os.path.join(HERE, "joint_protection.py"), encoding="utf-8").read()
    jp = re.sub(
        r"DEFAULT_HOME_JOINTS = \[[^\]]*\]",
        "DEFAULT_HOME_JOINTS = %s" % home,
        jp,
        count=1,
    )
    open(os.path.join(HERE, "joint_protection.py"), "w", encoding="utf-8").write(jp)

    off = [round(-home[i], 3) for i in range(5)] + [0.0]
    kin_path = os.path.join(ROOT, "frontend", "src", "lib", "kinematics.ts")
    ktxt = open(kin_path, encoding="utf-8").read()
    ktxt = re.sub(
        r"export const VIEW_HOME_JOINTS_DEG = \[[^\]]*\] as const",
        "export const VIEW_HOME_JOINTS_DEG = [%s] as const"
        % ", ".join(str(x) for x in home),
        ktxt,
        count=1,
    )
    ktxt = re.sub(
        r"export const VIEW_JOINT_OFFSET_DEG = \[[^\]]*\] as const",
        "export const VIEW_JOINT_OFFSET_DEG = [%s] as const"
        % ", ".join(str(x) for x in off),
        ktxt,
        count=1,
    )
    open(kin_path, "w", encoding="utf-8").write(ktxt)

    as_path = os.path.join(ROOT, "backend", "app", "services", "arm_state.py")
    atxt = open(as_path, encoding="utf-8").read()
    atxt2, n = re.subn(
        r"self\.target = \[[^\]]*\]\n\s*self\.actual = list\(self\.target\)",
        "self.target = %s\n        self.actual = list(self.target)" % home,
        atxt,
        count=1,
    )
    if n:
        open(as_path, "w", encoding="utf-8").write(atxt2)

    for d in (
        "/home/aidlux/sc171v2_agent",
        "/home/aidlux/Desktop/sc171v2_jetarm",
    ):
        try:
            sftp.stat(d)
        except IOError:
            continue
        for name in (
            "home_pose.json",
            "joint_protection.py",
            "sc171v2_servo_bridge.py",
            "arm_kinematics.py",
        ):
            sftp.put(os.path.join(HERE, name), d + "/" + name)
            print("PUT", d, name)
    sftp.close()

    print(
        run(
            "echo aidlux | sudo -S -p '' bash -c '"
            "pkill -f sc171v2_servo_bridge.py || true; sleep 1; "
            "cd /home/aidlux/Desktop/sc171v2_jetarm || cd /home/aidlux/sc171v2_agent; "
            "PY=python3; "
            "[ -x /home/aidlux/sc171v2_agent/.venv/bin/python ] && "
            "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; "
            "rm -f /tmp/sc171v2_servo_bridge.log; "
            "PYTHONUNBUFFERED=1 nohup $PY -u sc171v2_servo_bridge.py "
            "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
            "--drive jetarm --move-time-ms 1000 --no-boot-home "
            ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo PID=$!'"
        )
    )
    time.sleep(5)
    log = run("tail -n 40 /tmp/sc171v2_servo_bridge.log")
    print(log)
    c.close()

    # deploy cloud FE+backend after local npm build — caller builds FE
    print("HOME=" + json.dumps(home))
    print("NEED_FE_DEPLOY=1")
    return 0 if "H0-FOLLOW" in log or "H0-READY" in log or "mqtt" in log.lower() else 1


if __name__ == "__main__":
    raise SystemExit(main())
