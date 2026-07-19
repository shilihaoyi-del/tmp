#!/usr/bin/env bash
set +e
echo aidlux | sudo -S -p '' bash -c '
set +e
HDR=/usr/src/header
cd $HDR
echo "=== scripts/mod contents ==="
ls -la scripts/mod | head -40
echo "=== build modpost ==="
make scripts/mod/modpost 2>&1 | tail -50
ls -la scripts/mod/modpost scripts/mod/modpost.o 2>&1
echo "=== MODULE config ==="
zcat /proc/config.gz | grep -E "CONFIG_MODULES|CONFIG_MODULE_SIG|CONFIG_MODVERSIONS|FORCE_LOAD|TRIM_UNUSED"
echo "=== try make modules_prepare ==="
make modules_prepare 2>&1 | tail -60
'
