#!/usr/bin/env bash
# Swing base joint left-right via MQTT -> SC171 -> UART
set -euo pipefail
echo "=== swing start (base L/R) ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ $((i % 2)) -eq 1 ]; then
    ANG=45
    SIDE=RIGHT
  else
    ANG=-45
    SIDE=LEFT
  fi
  TS=$(date +%s%3N)
  SEQ=$((8800 + i))
  echo "[$i] $SIDE base=$ANG"
  mosquitto_pub -h 127.0.0.1 -t 'arm/device/cmd' -q 1 -m "{\"seq\":$SEQ,\"ts_ms\":$TS,\"ttl_ms\":8000,\"mode\":\"running\",\"target\":[$ANG,0,0,0,0,0],\"estop\":false}"
  sleep 1.2
done
# center
TS=$(date +%s%3N)
mosquitto_pub -h 127.0.0.1 -t 'arm/device/cmd' -q 1 -m "{\"seq\":8899,\"ts_ms\":$TS,\"ttl_ms\":8000,\"mode\":\"running\",\"target\":[0,0,0,0,0,0],\"estop\":false}"
echo "=== swing done, back to 0 ==="
curl -s http://127.0.0.1:8000/api/status; echo
