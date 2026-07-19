#!/usr/bin/env bash
# Enable CDC serial path on AidLux SC171V2 for WCH 1a86:55d4
# Kernel CONFIG_USB_ACM is disabled; Module.symvers mismatch blocks cdc-acm.ko.
# This starts a userspace CDC<->PTY bridge instead.
set -euo pipefail
DIR=/home/aidlux/cdc_acm_build
LOG=/tmp/cdc_pty_bridge.log
LINK=/tmp/ttyACM_sc171

mkdir -p "$DIR"
cp -f /tmp/cdc_pty_bridge.py "$DIR/cdc_pty_bridge.py" 2>/dev/null || true
cp -f /tmp/cdc_userspace_tx.py "$DIR/cdc_userspace_tx.py" 2>/dev/null || true

if pgrep -f 'cdc_pty_bridge.py' >/dev/null 2>&1; then
  echo "[..] stopping old bridge"
  echo aidlux | sudo -S -p '' pkill -f cdc_pty_bridge.py || true
  sleep 1
fi

echo aidlux | sudo -S -p '' pip3 install -q -i https://pypi.tuna.tsinghua.edu.cn/simple pyusb >/dev/null

# quick TX smoke
echo "[..] smoke TX"
echo aidlux | sudo -S -p '' python3 "$DIR/cdc_userspace_tx.py"

echo "[..] start PTY bridge"
echo aidlux | sudo -S -p '' bash -c "nohup python3 -u $DIR/cdc_pty_bridge.py --link $LINK >$LOG 2>&1 & echo PID=\$!"
sleep 1
echo "===== log ====="
cat "$LOG" || true
echo "===== link ====="
ls -l "$LINK" 2>&1 || true
echo
echo "Serial path: $LINK"
echo "Test write:  echo hello | sudo tee $LINK"
echo "Follow log:  tail -f $LOG"
