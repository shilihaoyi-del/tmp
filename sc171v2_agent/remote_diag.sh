#!/bin/bash
echo "=== lsusb ==="
lsusb
echo "=== tty ==="
ls -l /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/* 2>&1 || true
echo "=== dmesg usb/ch34 ==="
dmesg | grep -iE 'ttyUSB|ch34|1a86|cdc_acm|ttyACM' | tail -40
echo "=== modules ==="
lsmod | grep -iE 'ch34|usbserial|cdc_acm' || true
echo "=== try modprobe ==="
modprobe ch341 2>&1 || modprobe ch340 2>&1 || true
modprobe usbserial 2>&1 || true
sleep 1
ls -l /dev/ttyUSB* /dev/ttyACM* 2>&1 || true
echo "=== python open acm ==="
python3 - <<'PY'
import os, traceback
print('exists acm', os.path.exists('/dev/ttyACM0'))
print('exists usb0', os.path.exists('/dev/ttyUSB0'))
try:
    import serial
    s = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.2)
    print('opened', s.port, s.baudrate)
    s.write(bytes.fromhex('AA55050205016F'))
    s.flush()
    import time; time.sleep(0.2)
    data = s.read(64)
    print('rx', data.hex() if data else 'empty')
    s.close()
except Exception:
    traceback.print_exc()
PY
