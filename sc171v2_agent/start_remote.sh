#!/usr/bin/env bash
set -eu
cd /home/aidlux/sc171v2_agent
LOG=/tmp/sc171v2_mqtt.log

if pgrep -f 'sc171v2_mqtt_agent.py' >/dev/null 2>&1; then
  pkill -f 'sc171v2_mqtt_agent.py' || true
  sleep 1
fi

export PYTHONUNBUFFERED=1
nohup /home/aidlux/sc171v2_agent/.venv/bin/python -u \
  /home/aidlux/sc171v2_agent/sc171v2_mqtt_agent.py \
  --host 121.41.67.80 \
  --port 1883 \
  --carrier Wi-Fi \
  >"$LOG" 2>&1 &

echo "PID=$!"
sleep 3
echo '===== log ====='
cat "$LOG"
