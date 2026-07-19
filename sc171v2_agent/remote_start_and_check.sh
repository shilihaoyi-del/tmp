#!/bin/bash
set -e
AGENT=/home/aidlux/sc171v2_agent
DESK=/home/aidlux/Desktop/sc171v2_jetarm
PY=$AGENT/.venv/bin/python
LOG=/tmp/sc171v2_servo_bridge.log

# keep Desktop and agent in sync
cp -f "$DESK"/*.py "$DESK"/*.sh "$DESK"/PIPELINE.md "$DESK"/README.md "$AGENT"/ 2>/dev/null || true
chmod +x "$AGENT"/start_servo_bridge.sh || true

echo aidlux | sudo -S -p '' true
echo aidlux | sudo -S -p '' pkill -f sc171v2_servo_bridge.py || true
echo aidlux | sudo -S -p '' pkill -f sc171v2_mqtt_agent.py || true
sleep 1

echo "=== start bridge ==="
echo aidlux | sudo -S -p '' bash -c "PYTHONUNBUFFERED=1 nohup $PY -u $AGENT/sc171v2_servo_bridge.py --host 121.41.67.80 --port 1883 --uart pyusb --carrier Wi-Fi --drive jetarm >$LOG 2>&1 & echo PID=\$!"
sleep 4
echo "=== log head ==="
tail -n 40 "$LOG" || true
echo "=== mqtt quick listen 5s ==="
$PY - <<'PY'
import json, time
try:
    import paho.mqtt.client as mqtt
except Exception as e:
    print("no paho", e); raise SystemExit(0)
got={"hb":None,"st":None}
def on_msg(c,u,m):
    try:
        d=json.loads(m.payload.decode())
    except Exception:
        d={"raw":m.payload.decode(errors="ignore")}
    if m.topic.endswith("heartbeat"):
        got["hb"]=d
    if m.topic.endswith("status"):
        got["st"]=d
    print("[MQTT]", m.topic, json.dumps(d, ensure_ascii=False)[:300])
c=mqtt.Client(client_id="desk-check", protocol=mqtt.MQTTv311, clean_session=True)
c.on_message=on_msg
c.connect("121.41.67.80", 1883, 30)
c.subscribe([("arm/device/heartbeat",0),("arm/device/status",0)])
c.loop_start()
t0=time.time()
while time.time()-t0 < 6:
    time.sleep(0.2)
c.loop_stop(); c.disconnect()
print("HAS_HB", got["hb"] is not None, "HAS_STATUS", got["st"] is not None)
if got["st"]:
    print("stm32_online", got["st"].get("stm32_online"), "actual", got["st"].get("actual"), "pose", got["st"].get("pose"))
PY
