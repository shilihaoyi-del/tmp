#!/bin/bash
set -e
cd /home/aidlux/sc171v2_agent
echo "=== devices ==="
ls -l /dev/ttyUSB* /dev/ttyACM* 2>&1 || true
lsusb || true
echo "=== kill old bridge ==="
pkill -f sc171v2_servo_bridge.py || true
sleep 1
echo "=== probe ttyUSB0 1Mbps ==="
python3 probe_read_positions.py --port /dev/ttyUSB0 --baud 1000000 || true
echo "=== probe ttyACM0 1Mbps ==="
python3 probe_read_positions.py --port /dev/ttyACM0 --baud 1000000 || true
echo "=== probe ttyUSB0 115200 ==="
python3 probe_read_positions.py --port /dev/ttyUSB0 --baud 115200 || true
echo "=== probe ttyACM0 115200 ==="
python3 probe_read_positions.py --port /dev/ttyACM0 --baud 115200 || true
echo "=== done ==="
