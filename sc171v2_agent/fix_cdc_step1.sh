#!/usr/bin/env bash
set +e
echo aidlux | sudo -S -p '' bash -c '
set +e
echo "=== /usr/src ==="
ls -la /usr/src 2>&1
ls -la /usr/src/header 2>&1 | head -30
echo "=== module dir ==="
ls /lib/modules/$(uname -r)/ 2>&1
ls /lib/modules/$(uname -r)/kernel/drivers/usb/ 2>&1 | head
find /lib/modules/$(uname -r) -name "*.ko*" 2>/dev/null | grep -iE "acm|cdc|serial|ch34" | head -40
echo "=== aidlux packages ==="
which apt apt-get opkg 2>&1
apt-cache search linux-modules 2>/dev/null | head
apt-cache search cdc 2>/dev/null | head
echo "=== remove stale nodes? check ==="
ls -l /dev/ttyACM0 /dev/ttyUSB0
fuser -v /dev/ttyACM0 2>&1 | head
fuser -v /dev/ttyUSB0 2>&1 | head
echo "=== try new_id on ch341 ==="
echo "1a86 55d4" > /sys/bus/usb-serial/drivers/ch341-uart/new_id 2>&1
echo ch341_new_id_rc=$?
sleep 1
lsusb -t
ls -l /dev/ttyUSB* /dev/ttyACM* 2>&1
ls -l /sys/bus/usb/devices/2-2:1.*/driver 2>&1
echo "=== unbind/bind attempts ==="
# show modalias
cat /sys/bus/usb/devices/2-2:1.0/modalias
cat /sys/bus/usb/devices/2-2:1.1/modalias
'
