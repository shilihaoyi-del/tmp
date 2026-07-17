#!/usr/bin/env bash
set -eu
echo '=== health ==='
curl -s http://127.0.0.1:8000/api/health
echo
echo '=== publish device cmd ==='
mosquitto_pub -h 127.0.0.1 -t 'arm/device/cmd' -q 1 -m '{"seq":9001,"ts_ms":1,"ttl_ms":5000,"mode":"running","target":[11,22,-15,0,5,40],"estop":false}'
echo '=== publish via api/cmd (PC path) ==='
curl -s -X POST http://127.0.0.1:8000/api/control -H 'Content-Type: application/json' -d '{"action":"reset"}'
echo
curl -s -X POST http://127.0.0.1:8000/api/control -H 'Content-Type: application/json' -d '{"action":"start"}'
echo
curl -s -X POST http://127.0.0.1:8000/api/cmd -H 'Content-Type: application/json' -d '{"seq":42,"ts_ms":'"$(($(date +%s%3N)))"',"ttl_ms":5000,"target":[11,22,-15,0,5,40],"estop":false}'
echo
sleep 2
echo '=== status ==='
curl -s http://127.0.0.1:8000/api/status
echo
