#!/usr/bin/env python3
"""Read current pose → set as home → start servo bridge (web follows actual)."""
from __future__ import annotations

import json
import os
import re
import time

import paramiko

HOST, USER, PW = "192.168.42.4", "aidlux", "aidlux"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

REMOTE_READ = r"""
import json, os, sys, time
AGENT="/home/aidlux/sc171v2_agent"
if not os.path.isdir(AGENT): AGENT="/home/aidlux/Desktop/sc171v2_jetarm"
sys.path.insert(0, AGENT); os.chdir(AGENT)
from jetarm_packet import SUB_READ_POSITION, JetArmStreamParser, pack_read_position, pack_unload, parse_bus_servo_report
from probe_read_positions import open_link
from joint_protection import clamp_joints_deg, pos_to_deg
link=open_link(None); parser=JetArmStreamParser()
for sid in range(1,7):
  try: link.write(pack_unload(sid))
  except Exception: pass
  time.sleep(0.02)
time.sleep(0.1)
def read_sid(sid):
  for _ in range(5):
    try: link.write(pack_read_position(sid))
    except Exception as e: return None, str(e)
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
          return round(pos_to_deg(p,sid-1),3), None
    time.sleep(0.03)
  return None, "timeout"
degs=[]
for sid in range(1,7):
  d,e=read_sid(sid); degs.append(d); print("READ",sid,d,e)
print("RAW="+json.dumps(degs))
try: link.close()
except Exception: pass
"""


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PW, timeout=12)

    def run(cmd: str, timeout: int = 60) -> str:
        _i, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print(
        run(
            "echo aidlux | sudo -S -p '' bash -c "
            "'pkill -f sc171v2_servo_bridge.py; "
            "pkill -f free_move_cloud.py; "
            "pkill -f free_move_read.py; true'"
        )
    )
    time.sleep(0.8)
    sftp = c.open_sftp()
    with sftp.file("/tmp/cap_home_bridge.py", "w") as f:
        f.write(REMOTE_READ)
    out = run(
        "cd /home/aidlux/sc171v2_agent && echo aidlux | sudo -S -p '' "
        "python3 /tmp/cap_home_bridge.py"
    )
    print(out)
    if "RAW=" not in out:
        sftp.close()
        c.close()
        return 1
    raw = json.loads(out.split("RAW=", 1)[1].strip().splitlines()[0])
    default = [-0.72, -87.6, -36.72, -183.0, -4.8, 45.0]
    filled = [default[i] if raw[i] is None else float(raw[i]) for i in range(6)]
    # soft clamp using local joint_protection if available
    sys_path = HERE
    import sys

    sys.path.insert(0, sys_path)
    from joint_protection import clamp_joints_deg, joints_to_positions

    home = [round(x, 3) for x in clamp_joints_deg(filled)]
    pulses = joints_to_positions(home)
    payload = {
        "name": "home",
        "joints_deg": home,
        "joints_raw_deg": [None if x is None else round(float(x), 3) for x in raw],
        "command_pulses": pulses,
        "note": "current pose = web Z-line home; bridge follow actual",
        "status": "taught_sync_now",
    }
    home_path = os.path.join(HERE, "home_pose.json")
    with open(home_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("HOME", home)

    # update DEFAULT_HOME in joint_protection.py
    jp = os.path.join(HERE, "joint_protection.py")
    with open(jp, "r", encoding="utf-8") as f:
        text = f.read()
    text2, n = re.subn(
        r"DEFAULT_HOME_JOINTS = \[[^\]]*\]",
        "DEFAULT_HOME_JOINTS = %s" % home,
        text,
        count=1,
    )
    if n:
        with open(jp, "w", encoding="utf-8") as f:
            f.write(text2)

    # update frontend VIEW_HOME + OFFSET
    kin = os.path.join(ROOT, "frontend", "src", "lib", "kinematics.ts")
    with open(kin, "r", encoding="utf-8") as f:
        ktxt = f.read()
    off = [round(-home[i], 3) for i in range(5)] + [0.0]
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
    with open(kin, "w", encoding="utf-8") as f:
        f.write(ktxt)
    print("VIEW_OFFSET", off)

    # backend default home
    arm_state = os.path.join(ROOT, "backend", "app", "services", "arm_state.py")
    with open(arm_state, "r", encoding="utf-8") as f:
        atxt = f.read()
    atxt2, n2 = re.subn(
        r"self\.target = \[[^\]]*\]\n\s*self\.actual = list\(self\.target\)",
        "self.target = %s\n        self.actual = list(self.target)" % home,
        atxt,
        count=1,
    )
    if n2:
        with open(arm_state, "w", encoding="utf-8") as f:
            f.write(atxt2)

    # sync agent files to AidLux
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
            local = os.path.join(HERE, name)
            if os.path.isfile(local):
                sftp.put(local, d + "/" + name)
                print("PUT", d, name)
    sftp.close()

    # start bridge in background
    start = (
        "echo aidlux | sudo -S -p '' bash -c '"
        "pkill -f sc171v2_servo_bridge.py || true; "
        "sleep 1; "
        "cd /home/aidlux/Desktop/sc171v2_jetarm || cd /home/aidlux/sc171v2_agent; "
        "PY=python3; "
        "if [ -x /home/aidlux/sc171v2_agent/.venv/bin/python ]; then "
        "PY=/home/aidlux/sc171v2_agent/.venv/bin/python; fi; "
        "PYTHONUNBUFFERED=1 nohup $PY -u sc171v2_servo_bridge.py "
        "--host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi "
        "--drive jetarm --move-time-ms 1000 "
        ">/tmp/sc171v2_servo_bridge.log 2>&1 & echo PID=$!'"
    )
    print(run(start))
    time.sleep(4)
    print(run("tail -n 35 /tmp/sc171v2_servo_bridge.log"))
    c.close()
    print("HOME_SET=" + json.dumps(home))
    print("NEXT: build/deploy frontend + restart cloud; web should follow actual")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
