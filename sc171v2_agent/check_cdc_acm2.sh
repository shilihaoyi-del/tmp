#!/usr/bin/env bash
set +e
echo "=== tty sysfs ==="
ls -la /sys/class/tty/ttyACM0 /sys/class/tty/ttyUSB0 2>&1
ls -la /sys/class/tty/ttyACM0/device 2>&1
ls -la /sys/class/tty/ttyUSB0/device 2>&1
echo "=== usb device detail ==="
for d in /sys/bus/usb/devices/*; do
  if [ -f "$d/idVendor" ]; then
    v=$(cat "$d/idVendor" 2>/dev/null)
    p=$(cat "$d/idProduct" 2>/dev/null)
    if [ "$v" = "1a86" ]; then
      echo "FOUND $d vendor=$v product=$p"
      cat "$d/product" 2>/dev/null
      ls -la "$d/" 2>/dev/null | head -30
      for i in "$d":*; do
        [ -e "$i" ] || continue
        echo " iface $i"
        cat "$i/bInterfaceClass" 2>/dev/null; echo
        ls -la "$i/driver" 2>/dev/null
        ls "$i" 2>/dev/null | head
      done
    fi
  fi
done
echo "=== kernel headers / build ==="
ls /lib/modules/$(uname -r)/build 2>&1 | head
ls /usr/src 2>&1 | head
which make gcc 2>&1
echo "=== apt/cdc packages ==="
dpkg -l 2>/dev/null | grep -iE 'linux-modules|cdc|usb-serial|headers' | head -20
apt-cache search cdc-acm 2>/dev/null | head
echo "=== try sudo with pass ==="
echo aidlux | sudo -S -p '' id
echo "=== drivers available in /sys ==="
ls /sys/bus/usb/drivers/ 2>/dev/null
ls /sys/bus/usb-serial/drivers/ 2>/dev/null
echo "=== major minors ==="
cat /proc/tty/drivers | head -40
ls -l /dev/ttyACM* /dev/ttyUSB* 2>&1
