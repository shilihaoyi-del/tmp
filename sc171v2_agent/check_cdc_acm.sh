#!/usr/bin/env bash
set +e
echo "=== built-in config ==="
zcat /proc/config.gz 2>/dev/null | grep -iE 'CONFIG_USB_ACM|CONFIG_USB_SERIAL' || echo "no /proc/config.gz match"
echo "=== driver link ==="
ls -l /sys/class/tty/ttyACM0/device/driver 2>/dev/null
ls -l /sys/class/tty/ttyUSB0/device/driver 2>/dev/null
readlink -f /sys/class/tty/ttyACM0/device/driver 2>/dev/null
readlink -f /sys/class/tty/ttyUSB0/device/driver 2>/dev/null
echo "=== usb tree ==="
lsusb -t 2>/dev/null
echo "=== dmesg USB ==="
dmesg 2>/dev/null | grep -iE '1a86|55d4|ttyACM|ttyUSB|cdc_acm|ch34|acm|usbserial' | tail -50
echo "=== id/groups ==="
id
groups
echo "=== access ==="
python3 -c '
import os
for p in ["/dev/ttyACM0","/dev/ttyUSB0"]:
  try:
    st=os.stat(p)
    print(p, "mode", oct(st.st_mode & 0o777), "uid", st.st_uid, "gid", st.st_gid, "R", os.access(p, os.R_OK), "W", os.access(p, os.W_OK))
  except Exception as e:
    print(p, e)
'
echo "=== modules on disk ==="
find /lib/modules -iname '*acm*' 2>/dev/null | head -20
find /lib/modules -iname '*ch34*' 2>/dev/null | head -20
find /lib/modules -iname '*usbserial*' 2>/dev/null | head -20
echo "=== sudo ==="
sudo -n true 2>&1
echo sudo_rc=$?
echo "=== who owns nodes ==="
ls -l /dev/ttyACM0 /dev/ttyUSB0 2>&1
echo "=== udevadm ==="
udevadm info -a -n /dev/ttyACM0 2>/dev/null | head -40
udevadm info -a -n /dev/ttyUSB0 2>/dev/null | head -40
