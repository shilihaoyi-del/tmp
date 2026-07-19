#!/bin/bash
set -x
PY=/home/aidlux/sc171v2_agent/.venv/bin/python
if [ ! -x "$PY" ]; then PY=python3; fi
"$PY" -c "import serial; print('serial', serial.__version__)" || pip3 install -q pyserial

echo "=== rebind ch341 ==="
# find interface for 1a86:7523
for d in /sys/bus/usb/devices/*; do
  if [ -f "$d/idVendor" ] && [ "$(cat $d/idVendor)" = "1a86" ] && [ "$(cat $d/idProduct)" = "7523" ]; then
    echo "found $d"
    for iface in "$d":*; do
      [ -d "$iface" ] || continue
      name=$(basename "$iface")
      echo "iface $name"
      if [ -e /sys/bus/usb/drivers/ch341/unbind ]; then
        echo "$name" > /sys/bus/usb/drivers/ch341/unbind 2>/dev/null || true
        sleep 0.2
        echo "$name" > /sys/bus/usb/drivers/ch341/bind 2>/dev/null || true
      fi
      if [ -e /sys/bus/usb/drivers/usbserial/unbind ]; then
        echo "$name" > /sys/bus/usb/drivers/usbserial/unbind 2>/dev/null || true
        echo "$name" > /sys/bus/usb/drivers/usbserial/bind 2>/dev/null || true
      fi
    done
  fi
done
sleep 1
ls -l /dev/ttyUSB* /dev/ttyACM* 2>&1 || true
dmesg | tail -20

echo "=== probe with venv ==="
cd /home/aidlux/sc171v2_agent
if [ -e /dev/ttyUSB0 ]; then
  "$PY" probe_read_positions.py --port /dev/ttyUSB0 --baud 1000000
  "$PY" probe_read_positions.py --port /dev/ttyUSB0 --baud 115200
else
  echo "still no ttyUSB0"
  "$PY" probe_read_positions.py --port /dev/ttyACM0 --baud 1000000 || true
fi
