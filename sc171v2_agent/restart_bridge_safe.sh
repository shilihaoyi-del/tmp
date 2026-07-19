#!/usr/bin/env bash
set +e
echo aidlux | sudo -S -p '' true
# kill only python workers (avoid matching this script cmdline)
echo aidlux | sudo -S -p '' pkill -9 -f '.venv/bin/python -u /home/aidlux/sc171v2_agent/sc171v2_servo_bridge' || true
echo aidlux | sudo -S -p '' pkill -9 -f 'python3 -u /home/aidlux/cdc_acm_build/cdc_pty_bridge' || true
sleep 2
echo "after kill:"
pgrep -af 'servo_bridge|cdc_pty' || echo none
bash /home/aidlux/sc171v2_agent/start_servo_bridge.sh
