#!/bin/bash
AGENT=/home/aidlux/sc171v2_agent
PY=$AGENT/.venv/bin/python
pkill -f sc171v2_servo_bridge.py || true
sleep 1
echo "=== probe CH340 pyusb 1Mbps ==="
$PY $AGENT/probe_read_positions.py --baud 1000000
echo "=== probe CH340 pyusb 115200 ==="
$PY $AGENT/probe_read_positions.py --baud 115200
