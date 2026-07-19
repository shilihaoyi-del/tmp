#!/usr/bin/env bash
set -euo pipefail
HDR=/usr/src/header
SRC=/home/aidlux/cdc_acm_build
KVER=$(uname -r)

echo aidlux | sudo -S -p '' bash -c "
set -e
cd $HDR
# rebuild modpost host tool
cd scripts/mod
gcc -Wall -Wmissing-prototypes -Wstrict-prototypes -O2 -fomit-frame-pointer -std=gnu89 -c -o modpost.o modpost.c
gcc -Wall -Wmissing-prototypes -Wstrict-prototypes -O2 -fomit-frame-pointer -std=gnu89 -c -o file2alias.o file2alias.c
gcc -Wall -Wmissing-prototypes -Wstrict-prototypes -O2 -fomit-frame-pointer -std=gnu89 -c -o sumversion.o sumversion.c
gcc -o modpost modpost.o file2alias.o sumversion.o
ls -la modpost

cd $HDR
# match running kernel release string
cp -a include/generated/utsrelease.h include/generated/utsrelease.h.bak.\$\$
printf '#define UTS_RELEASE \"%s\"\n' '$KVER' > include/generated/utsrelease.h
cat include/generated/utsrelease.h

# ensure build symlink
mkdir -p /lib/modules/$KVER
ln -sfn $HDR /lib/modules/$KVER/build
"

cd "$SRC"
make clean >/dev/null 2>&1 || true
make -j2 2>&1
echo '=== modinfo ==='
modinfo ./cdc-acm.ko || true

echo aidlux | sudo -S -p '' bash -c "
set +e
rm -f /dev/ttyACM0 /dev/ttyUSB0
rmmod cdc_acm 2>/dev/null
insmod $SRC/cdc-acm.ko
echo insmod_rc=\$?
sleep 1
lsmod | grep -i acm
lsusb -t
ls -l /sys/bus/usb/devices/2-2:1.*/driver 2>&1
ls -l /dev/ttyACM* 2>&1
chmod 666 /dev/ttyACM* 2>/dev/null
dmesg | tail -40
"
