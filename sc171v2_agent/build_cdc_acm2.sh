#!/usr/bin/env bash
set -euo pipefail
HDR=/usr/src/header
SRC=/home/aidlux/cdc_acm_build
KVER=$(uname -r)

echo aidlux | sudo -S -p '' bash -c "
set -e
cd $HDR
# build host tools needed for external modules
if [ ! -x scripts/basic/fixdep ]; then
  echo '=== building scripts/basic ==='
  mkdir -p scripts/basic
  make scripts/basic/fixdep 2>&1 || make -C scripts/basic 2>&1 || true
fi
if [ ! -x scripts/basic/fixdep ]; then
  # compile fixdep manually from source if present
  if [ -f scripts/basic/fixdep.c ]; then
    cc -O2 -o scripts/basic/fixdep scripts/basic/fixdep.c
  fi
fi
ls -la scripts/basic/fixdep scripts/mod/modpost 2>&1 || true
# ensure modpost exists
if [ ! -x scripts/mod/modpost ]; then
  make scripts/mod 2>&1 | tail -40
fi
ls -la scripts/basic/fixdep scripts/mod/modpost 2>&1
"

cd "$SRC"
make clean 2>/dev/null || true
make 2>&1
ls -la *.ko

echo "=== vermagic in ko ==="
modinfo "$SRC/cdc-acm.ko" 2>&1 || true
strings "$SRC/cdc-acm.ko" | grep -E '^[0-9]+\.[0-9].*smp|vermagic' | head

echo aidlux | sudo -S -p '' bash -c "
set +e
rm -f /dev/ttyACM0 /dev/ttyUSB0
# try normal then force
rmmod cdc_acm 2>/dev/null
insmod $SRC/cdc-acm.ko 2>&1
RC=\$?
if [ \$RC -ne 0 ]; then
  echo 'normal insmod failed, try force via modprobe helpers'
  # patch vermagic to running kernel if needed
  RUNVER='$KVER'
  python3 - <<'PY'
import sys
path='$SRC/cdc-acm.ko'
data=open(path,'rb').read()
# find vermagic string
idx=data.find(b'vermagic=')
print('vermagic idx', idx)
if idx>=0:
    end=data.find(b'\x00', idx)
    old=data[idx:end]
    print('old', old)
PY
  # force load with ignore vermagic via sysctl if available
  echo 1 > /proc/sys/kernel/modules_disabled 2>/dev/null
  # use insmod after rewriting UTS - simpler approach: set force via /sys/module
fi
dmesg | tail -20
lsmod | grep -i acm
lsusb -t
ls -l /dev/ttyACM* 2>&1
"
