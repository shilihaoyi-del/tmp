#!/usr/bin/env bash
# Server-side: publish joint cmd and watch trace topic
set -euo pipefail
echo "=== publish JOINT cmd ==="
TS=$(date +%s%3N)
mosquitto_pub -h 127.0.0.1 -t 'arm/device/cmd' -q 1 -m "{\"seq\":9901,\"ts_ms\":$TS,\"ttl_ms\":5000,\"mode\":\"running\",\"target\":[10,20,-15,0,5,40],\"estop\":false}"
echo "=== listen hops 6s ==="
timeout 6 mosquitto_sub -h 127.0.0.1 -t 'arm/device/trace' -t 'arm/device/status' -v | head -40
echo "=== health ==="
curl -s http://127.0.0.1:8000/api/health; echo
curl -s http://127.0.0.1:8000/api/status; echo
