#!/usr/bin/env bash
set -euo pipefail
KVER=$(uname -r)
HDR=/usr/src/header
SRC=/home/aidlux/cdc_acm_build

echo aidlux | sudo -S -p '' bash -c "mkdir -p /lib/modules/$KVER; ln -sfn $HDR /lib/modules/$KVER/build; ln -sfn $HDR /lib/modules/$KVER/source"
echo "utsrelease:"; cat "$HDR/include/generated/utsrelease.h" || true
echo "running: $(uname -r)"

cd "$SRC"
echo "=== files ==="
ls -la
echo "=== make ==="
make 2>&1
echo "=== load ==="
echo aidlux | sudo -S -p '' bash -c '
set -e
# remove stale fake nodes
rm -f /dev/ttyACM0 /dev/ttyUSB0
insmod /home/aidlux/cdc_acm_build/cdc-acm.ko || modprobe cdc-acm || true
sleep 1
lsmod | grep acm || true
dmesg | tail -30
lsusb -t
ls -l /dev/ttyACM* 2>&1 || true
# permissions for aidlux
if ls /dev/ttyACM* >/dev/null 2>&1; then
  chmod 666 /dev/ttyACM*
  ls -l /dev/ttyACM*
fi
'
