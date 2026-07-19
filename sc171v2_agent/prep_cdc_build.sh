#!/usr/bin/env bash
set -e
echo aidlux | sudo -S -p '' bash -c '
set -e
KVER=$(uname -r)
HDR=/usr/src/header
echo "KVER=$KVER"
echo "=== check cdc-acm source ==="
ls -la $HDR/drivers/usb/class/cdc-acm.c $HDR/drivers/usb/class/cdc-acm.h 2>&1
grep -n CONFIG_USB_ACM $HDR/.config | head
echo "=== prepare modules tree ==="
mkdir -p /lib/modules/$KVER
ln -sfn $HDR /lib/modules/$KVER/build
ln -sfn $HDR /lib/modules/$KVER/source
# Module.symvers already in header
ls -la /lib/modules/$KVER/build/Module.symvers
echo "=== uname release vs header ==="
head -5 $HDR/include/generated/utsrelease.h 2>/dev/null || true
grep UTS_RELEASE $HDR/include/generated/utsrelease.h 2>/dev/null || true
'
