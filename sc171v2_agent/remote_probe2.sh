#!/bin/bash
set -e
AGENT=/home/aidlux/sc171v2_agent
PY=$AGENT/.venv/bin/python
if [ ! -x "$PY" ]; then PY=python3; fi
echo "PY=$PY"
"$PY" -c "import serial; print('serial', serial.__version__)"
echo "=== usb ==="
lsusb
ls -l /dev/ttyUSB* /dev/ttyACM* 2>&1 || true
# try rebind ch341 device
for d in /sys/bus/usb/devices/*; do
  if [ -f "$d/idVendor" ] && [ "$(cat $d/idVendor)" = "1a86" ]; then
    echo "found $d pid=$(cat $d/idProduct)"
    echo "$(basename $d)" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
    sleep 0.5
    echo "$(basename $d)" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
  fi
done
sleep 1
ls -l /dev/ttyUSB* /dev/ttyACM* 2>&1 || true
dmesg | tail -20

pkill -f sc171v2_servo_bridge.py || true
sleep 1

for baud in 1000000 115200; do
  for port in /dev/ttyUSB0 /dev/ttyACM0; do
    if [ -e "$port" ]; then
      echo "===== $port @ $baud ====="
      "$PY" $AGENT/probe_read_positions.py --port "$port" --baud "$baud" || true
    fi
  done
done
