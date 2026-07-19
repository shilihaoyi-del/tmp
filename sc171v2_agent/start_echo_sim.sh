#!/usr/bin/env bash
set +e
echo aidlux | sudo -S -p '' pkill -9 -f '.venv/bin/python -u /home/aidlux/sc171v2_agent/sc171v2_servo_bridge' || true
sleep 2
export ECHO_SIM=--echo-sim
bash /home/aidlux/sc171v2_agent/start_servo_bridge.sh
sleep 2
tail -n 25 /tmp/sc171v2_servo_bridge.log
