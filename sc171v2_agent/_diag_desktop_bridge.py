#!/usr/bin/env python3
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
cmds = r"""
echo '=== Desktop/bridge ==='
ls -la /home/aidlux/Desktop/bridge /home/aidlux/Desktop/bridge.* 2>/dev/null || true
file /home/aidlux/Desktop/bridge 2>/dev/null || true
echo '--- content ---'
head -n 40 /home/aidlux/Desktop/bridge 2>/dev/null || true
echo '=== start scripts ==='
ls -la /home/aidlux/sc171v2_agent/start_gesture_bridge.sh /home/aidlux/Desktop/sc171v2_jetarm/start_gesture_bridge.sh 2>/dev/null
echo '=== grep key flags ==='
grep -n 'BOOT_HOME\|initial\|no-boot-home\|poll-interval\|EXTRA' /home/aidlux/sc171v2_agent/start_gesture_bridge.sh | head -40
echo '=== running ==='
pgrep -af 'python.*sc171v2_servo_bridge' || echo NO_BRIDGE
echo '=== poses ==='
python3 -c 'import json;print("home",json.load(open("/home/aidlux/sc171v2_agent/home_pose.json")));print("init",json.load(open("/home/aidlux/sc171v2_agent/initial_pose.json")))' 2>&1 | head
echo '=== desktop launcher mime/desktop files ==='
ls -la /home/aidlux/Desktop/*.desktop 2>/dev/null | head
for f in /home/aidlux/Desktop/*.desktop; do echo "== $f"; cat "$f" 2>/dev/null; done | head -80
"""
_, o, e = c.exec_command(cmds, timeout=30)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()
