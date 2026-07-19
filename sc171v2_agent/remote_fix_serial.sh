#!/bin/bash
AGENT=/home/aidlux/sc171v2_agent
PY=$AGENT/.venv/bin/python
echo "=== find ch341 ==="
find /home /vendor /system /lib /lib/modules /opt -iname '*ch341*' 2>/dev/null | head -40
echo "=== usb sysfs ==="
ls -l /sys/bus/usb/devices/2-2/ 2>&1 | head -30
cat /sys/bus/usb/devices/2-2/uevent 2>&1 || true
ls /sys/bus/usb/devices/2-2:*/ 2>&1 | head
echo "=== try raw open acm ==="
$PY - <<'PY'
import os, errno, traceback
path='/dev/ttyACM0'
print('exists', os.path.exists(path), 'access R', os.access(path, os.R_OK), 'W', os.access(path, os.W_OK))
try:
    fd=os.open(path, os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
    print('os.open ok', fd)
    os.close(fd)
except Exception as e:
    print('os.open fail', e)
try:
    import serial
    print('serial module', serial.__file__)
    s=serial.Serial()
    s.port=path
    s.baudrate=1000000
    s.timeout=0.2
    s.open()
    print('serial open ok')
    s.close()
except Exception as e:
    traceback.print_exc()
# try pyusb enumerate 1a86
try:
    import usb.core, usb.util
    for d in usb.core.find(find_all=True, idVendor=0x1A86):
        print('usb device', hex(d.idVendor), hex(d.idProduct), d)
        try:
            print(' configs', d.bNumConfigurations)
            for cfg in d:
                for intf in cfg:
                    print(' intf', intf.bInterfaceNumber, 'class', intf.bInterfaceClass, 'eps', [hex(e.bEndpointAddress) for e in intf])
        except Exception as e:
            print(' cfg err', e)
except Exception as e:
    traceback.print_exc()
PY
