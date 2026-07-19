#!/bin/bash
set -e
pkill -9 -f sc171v2_servo_bridge.py || true
sleep 2
: > /tmp/sc171v2_servo_bridge.log
cd /home/aidlux/Desktop/sc171v2_jetarm
PY=/home/aidlux/sc171v2_agent/.venv/bin/python
# One-shot unload over CH340
$PY -u ./free_move_read.py --once || $PY -u /home/aidlux/sc171v2_agent/free_move_read.py --once
# Keep bridge up in follow/unload mode so telemetry continues
nohup env PYTHONUNBUFFERED=1 $PY -u ./sc171v2_servo_bridge.py \
  --host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi \
  --drive jetarm --move-time-ms 2000 --poll-interval 0.12 --boot-pose none \
  >/tmp/sc171v2_servo_bridge.log 2>&1 &
echo $! > /tmp/sc171v2_servo_bridge.pid
sleep 4
pgrep -af sc171v2_servo_bridge | head -3
grep -E 'H0-FOLLOW|unload|H0-READY|FATAL|boot_pose|UNLOAD' /tmp/sc171v2_servo_bridge.log | head -30
