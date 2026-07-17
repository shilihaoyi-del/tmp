#!/usr/bin/env bash
# Keep SC171V2 MQTT agent running (call from crontab every minute)
set -eu
if pgrep -f 'sc171v2_mqtt_agent.py' >/dev/null 2>&1; then
  exit 0
fi
bash /home/aidlux/sc171v2_agent/start_remote.sh >/tmp/sc171v2_keepalive.log 2>&1
