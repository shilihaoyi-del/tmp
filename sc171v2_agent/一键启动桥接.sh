#!/usr/bin/env bash
# 广和通 SC171：一键启动 JetArm MQTT 舵机桥（连云端）
#
# 默认：自动桥接 + 回到初始位 (initial_pose.json)
#   bash start_gesture_bridge.sh
#   或双击桌面 bridge / bridge.desktop
#
# 可选：
#   BOOT_POSE=home   bash start_gesture_bridge.sh   # 回到 Z 轴 home
#   BOOT_POSE=none   bash start_gesture_bridge.sh   # 只跟随/不上电回位
#   FOLLOW=1         bash start_gesture_bridge.sh   # 同 BOOT_POSE=none
#
set +e
set -u

HOME_DIR="${HOME:-/home/aidlux}"
if [ -d "$HOME_DIR/Desktop/sc171v2_jetarm" ]; then
  AGENT_DIR="$HOME_DIR/Desktop/sc171v2_jetarm"
elif [ -d "$HOME_DIR/sc171v2_agent" ]; then
  AGENT_DIR="$HOME_DIR/sc171v2_agent"
else
  AGENT_DIR="$HOME_DIR/sc171v2_agent"
fi

BROKER_HOST="${MQTT_HOST:-121.41.67.80}"
BROKER_PORT="${MQTT_PORT:-1883}"
# Half of stock ~500ms pace → 2000ms; Jacobian further adapts per step
MOVE_TIME_MS="${MOVE_TIME_MS:-2000}"
POLL_INTERVAL="${POLL_INTERVAL:-0.12}"
LOG=/tmp/sc171v2_servo_bridge.log
PIDFILE=/tmp/sc171v2_servo_bridge.pid

# Default: go to working initial pose
BOOT_POSE="${BOOT_POSE:-initial}"
if [ "${FOLLOW:-0}" = "1" ] || [ "${FOLLOW:-0}" = "true" ]; then
  BOOT_POSE="none"
fi
if [ "${BOOT_HOME:-0}" = "1" ] || [ "${BOOT_HOME:-0}" = "true" ]; then
  # legacy flag → Z-line home
  BOOT_POSE="home"
fi

echo "========================================"
echo "  SC171 舵机桥一键启动"
echo "  dir=$AGENT_DIR"
echo "  mqtt=${BROKER_HOST}:${BROKER_PORT}"
echo "  boot_pose=$BOOT_POSE  poll=${POLL_INTERVAL}s  move=${MOVE_TIME_MS}ms"
echo "========================================"

# sync latest files from ~/sc171v2_agent → Desktop run dir
for f in \
  sc171v2_servo_bridge.py jetarm_packet.py joint_protection.py \
  arm_kinematics.py ch340_pyusb.py home_pose.json initial_pose.json
do
  if [ -f "$HOME_DIR/sc171v2_agent/$f" ]; then
    cp -f "$HOME_DIR/sc171v2_agent/$f" "$AGENT_DIR/$f" 2>/dev/null || true
  fi
done

if [ ! -f "$AGENT_DIR/sc171v2_servo_bridge.py" ]; then
  echo "[FAIL] 找不到 sc171v2_servo_bridge.py"
  exit 1
fi
if [ ! -f "$AGENT_DIR/initial_pose.json" ]; then
  echo "[WARN] 缺少 initial_pose.json，将用代码内默认初始位"
fi

PY=python3
if [ -x "$HOME_DIR/sc171v2_agent/.venv/bin/python" ]; then
  PY="$HOME_DIR/sc171v2_agent/.venv/bin/python"
fi

echo aidlux | sudo -S -p '' true >/dev/null 2>&1 || true
echo aidlux | sudo -S -p '' pkill -9 -f free_move_cloud.py >/dev/null 2>&1 || true
echo aidlux | sudo -S -p '' pkill -9 -f free_move_read.py >/dev/null 2>&1 || true
echo aidlux | sudo -S -p '' pkill -9 -f sc171v2_mqtt_agent.py >/dev/null 2>&1 || true
echo aidlux | sudo -S -p '' pkill -9 -f sc171v2_servo_bridge.py >/dev/null 2>&1 || true
sleep 2

: > "$LOG"
cd "$AGENT_DIR" || exit 1

# Start as root so CH340 pyusb can claim the device
BOOT_ARG="--boot-pose $BOOT_POSE"
echo aidlux | sudo -S -p '' bash -lc "
  cd '$AGENT_DIR' || exit 1
  export PYTHONUNBUFFERED=1
  nohup '$PY' -u ./sc171v2_servo_bridge.py \
    --host '$BROKER_HOST' --port '$BROKER_PORT' \
    --uart pyusb --carrier Wi-Fi --drive jetarm \
    --move-time-ms $MOVE_TIME_MS --poll-interval $POLL_INTERVAL \
    $BOOT_ARG \
    >'$LOG' 2>&1 &
  echo \$! > '$PIDFILE'
  echo PID=\$(cat '$PIDFILE')
"

sleep 3
PID="$(cat "$PIDFILE" 2>/dev/null || true)"
if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
  echo "[OK] bridge running pid=$PID"
else
  # fallback: match by process name
  PID="$(pgrep -f 'python.*sc171v2_servo_bridge.py' | head -n1 || true)"
  if [ -n "${PID:-}" ]; then
    echo "[OK] bridge running pid=$PID"
  else
    echo "[FAIL] bridge 未启动，见日志:"
    tail -n 50 "$LOG" || true
    exit 1
  fi
fi

echo "===== log ====="
grep -E 'poll=|H0-READY|H0-INIT|H0-HOME|H0-FOLLOW|FATAL|Error|CH340' "$LOG" | head -30
echo "..."
tail -n 15 "$LOG"
echo
echo "[OK] 观摩页: http://${BROKER_HOST}:8000/"
echo "     日志:   tail -f $LOG"
echo "     初始位: cat $AGENT_DIR/initial_pose.json"
echo "     仅跟随: FOLLOW=1 bash $0"
echo "     回Z线:  BOOT_POSE=home bash $0"

# keep terminal open when launched from desktop
if [ -t 0 ] && [ "${KEEP_OPEN:-1}" = "1" ]; then
  echo
  echo "按 Enter 关闭窗口（桥接继续在后台运行）..."
  read -r _ || true
fi
exit 0
