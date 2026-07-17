#!/usr/bin/env bash
# Deploy both protocol packages (downlink JOINT + uplink STATUS) and restart bridge
set -euo pipefail
AGENT=/home/aidlux/sc171v2_agent
STM32=$AGENT/stm32
LOG=/tmp/sc171v2_servo_bridge.log

mkdir -p "$STM32"

# copy from /tmp if present
for f in uart_protocol.py sc171v2_servo_bridge.py start_servo_bridge.sh UART_PROTOCOL.md; do
  if [ -f "/tmp/$f" ]; then cp -f "/tmp/$f" "$AGENT/$f"; fi
done
for f in arm_uart_protocol.h arm_uart_protocol.c arm_uart_reply.h arm_uart_reply.c stm32_reply_example.c hiwonder_servo.h hiwonder_servo.c stm32_arm_pipeline.c; do
  if [ -f "/tmp/$f" ]; then cp -f "/tmp/$f" "$STM32/$f"; fi
done
if [ -f /tmp/PIPELINE.md ]; then cp -f /tmp/PIPELINE.md "$AGENT/PIPELINE.md"; fi
if [ -f /tmp/UART_PROTOCOL.md ]; then cp -f /tmp/UART_PROTOCOL.md "$AGENT/UART_PROTOCOL.md"; fi

echo "=== deployed files ==="
ls -la "$AGENT"/uart_protocol.py "$AGENT"/sc171v2_servo_bridge.py "$AGENT"/UART_PROTOCOL.md
ls -la "$STM32"

# stop old worker safely
echo aidlux | sudo -S -p '' pkill -9 -f '.venv/bin/python -u /home/aidlux/sc171v2_agent/sc171v2_servo_bridge' || true
echo aidlux | sudo -S -p '' pkill -9 -f 'python3 -u /home/aidlux/cdc_acm_build/cdc_pty_bridge' || true
sleep 2

# self-test pack both directions locally first
PY=$AGENT/.venv/bin/python
[ -x "$PY" ] || PY=python3
echo "=== local pack JOINT ==="
"$PY" "$AGENT/uart_protocol.py" --joints "12,18,-12,2,6,35" --seq 18
echo "=== local pack STATUS reply ==="
"$PY" "$AGENT/uart_protocol.py" --as-status --joints "12,18,-12,2,6,35" --seq 18

# start bridge: real hardware path (no echo-sim)
# Set ECHO_SIM=--echo-sim only for SC171 self-test without STM32 firmware
export ECHO_SIM=${ECHO_SIM:-}
bash "$AGENT/start_servo_bridge.sh"
sleep 2
echo "=== bridge ready log ==="
tail -n 20 "$LOG"
echo
echo "NOTE: For real servo motion, flash stm32/ onto STM32 (see PIPELINE.md)."
echo "      Do NOT set ECHO_SIM when testing real servos."
