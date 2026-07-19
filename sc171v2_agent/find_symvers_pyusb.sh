#!/usr/bin/env bash
set +e
echo "=== search Module.symvers / vmlinux ==="
find / -name 'Module.symvers*' 2>/dev/null | head -20
find / -name 'vmlinux*' 2>/dev/null | head -20
find /vendor /system /lib/modules /opt /home/aidlux -iname '*cdc*acm*' 2>/dev/null | head
ls /vendor/lib/modules 2>/dev/null | head -30
ls /lib/modules 2>/dev/null
echo "=== pyusb ==="
python3 -c 'import usb.core; print("pyusb ok")' 2>&1
pip3 show pyusb 2>&1 | head -3
echo "=== libusb ==="
ls /usr/lib/*/libusb* 2>/dev/null | head
dpkg -l | grep -i libusb | head
