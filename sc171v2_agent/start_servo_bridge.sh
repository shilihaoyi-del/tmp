#!/usr/bin/env bash
# Deploy + start servo bridge with hop tracing on SC171V2
set -euo pipefail
HOME_DIR=/home/aidlux
AGENT_DIR=$HOME_DIR/sc171v2_agent
CDC_DIR=$HOME_DIR/cdc_acm_build
LOG=/tmp/sc171v2_servo_bridge.log
MQTT_LOG=/tmp/sc171v2_mqtt.log

echo aidlux | sudo -S -p '' true

# stop old mqtt-only agent to avoid duplicate client fights
if pgrep -f '[s]c171v2_mqtt_agent.py' >/dev/null 2>&1; then
  echo "[..] stop old mqtt agent"
  pkill -f '[s]c171v2_mqtt_agent.py' || true
  sleep 1
fi
if pgrep -f '[s]c171v2_servo_bridge.py' >/dev/null 2>&1; then
  echo "[..] stop old servo bridge"
  echo aidlux | sudo -S -p '' pkill -f '.venv/bin/python -u /home/aidlux/sc171v2_agent/sc171v2_servo_bridge' || true
  sleep 1
fi

# Direct pyusb needs exclusive USB access — stop PTY bridge if running
if pgrep -f '[c]dc_pty_bridge.py' >/dev/null 2>&1; then
  echo "[..] stop cdc pty bridge (switch to direct pyusb)"
  echo aidlux | sudo -S -p '' pkill -f 'python3 -u /home/aidlux/cdc_acm_build/cdc_pty_bridge' || true
  sleep 1
fi
echo aidlux | sudo -S -p '' pip3 install -q -i https://pypi.tuna.tsinghua.edu.cn/simple pyusb >/dev/null || true

mkdir -p "$AGENT_DIR"
# files expected already copied to /tmp or AGENT_DIR
for f in uart_protocol.py sc171v2_servo_bridge.py hiwonder_servo.py joint_protection.py jetarm_packet.py arm_kinematics.py ch340_pyusb.py probe_read_positions.py; do
  if [ -f "/tmp/$f" ]; then
    cp -f "/tmp/$f" "$AGENT_DIR/$f"
  fi
done

# pyserial optional
"$AGENT_DIR/.venv/bin/pip" install -q -i https://pypi.tuna.tsinghua.edu.cn/simple pyserial >/dev/null 2>&1 || \
  pip3 install -q -i https://pypi.tuna.tsinghua.edu.cn/simple pyserial >/dev/null 2>&1 || true

PY=$AGENT_DIR/.venv/bin/python
if [ ! -x "$PY" ]; then PY=python3; fi

export PYTHONUNBUFFERED=1
# run as root so pyusb can claim 1a86:55d4
DRIVE_MODE=${DRIVE:-jetarm}
# Default: boot to initial pose + fast telemetry
POLL_INTERVAL="${POLL_INTERVAL:-0.12}"
MOVE_TIME_MS="${MOVE_TIME_MS:-2000}"
BOOT_POSE="${BOOT_POSE:-initial}"
if [ "${FOLLOW:-0}" = "1" ]; then BOOT_POSE="none"; fi
if [ "${BOOT_HOME:-0}" = "1" ]; then BOOT_POSE="home"; fi
EXTRA="--move-time-ms $MOVE_TIME_MS --poll-interval $POLL_INTERVAL --boot-pose $BOOT_POSE"
echo aidlux | sudo -S -p '' bash -c "PYTHONUNBUFFERED=1 nohup $PY -u $AGENT_DIR/sc171v2_servo_bridge.py --host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi --drive $DRIVE_MODE $EXTRA ${ECHO_SIM:-} >$LOG 2>&1 & echo PID=\$!"
sleep 2
echo "===== servo bridge log ====="
tail -n 50 "$LOG" || true
