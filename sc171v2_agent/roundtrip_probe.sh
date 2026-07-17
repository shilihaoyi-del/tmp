#!/usr/bin/env bash
# Round-trip probe: cloud -> SC171 -> UART TX -> (STM32) -> UART RX -> cloud
set -euo pipefail
echo "=== clear listen ==="
timeout 8 mosquitto_sub -h 127.0.0.1 -t 'arm/device/trace' -v > /tmp/rt_trace.log &
SPID=$!
sleep 1
TS=$(date +%s%3N)
echo "=== publish JOINT ==="
mosquitto_pub -h 127.0.0.1 -t 'arm/device/cmd' -q 1 -m "{\"seq\":9910,\"ts_ms\":$TS,\"ttl_ms\":5000,\"mode\":\"running\",\"target\":[12,18,-12,2,6,35],\"estop\":false}"
sleep 5
kill $SPID 2>/dev/null || true
wait $SPID 2>/dev/null || true
echo "=== hops seen ==="
grep -E 'H1-MQTT|H2-PACK|H3-UART|H4-RX|H5-UP' /tmp/rt_trace.log | head -40
echo
echo "=== verdict ==="
python3 - <<'PY'
import json
hops=set(); h4_ok=False; h5_ok=False; h3_ok=False
for ln in open('/tmp/rt_trace.log'):
    if 'arm/device/trace' not in ln: continue
    try:
        js=ln.split(' ',1)[1]
        d=json.loads(js)
    except Exception:
        continue
    hops.add(d.get('hop'))
    if d.get('hop')=='H3-UART' and d.get('ok'): h3_ok=True
    if d.get('hop')=='H4-RX' and d.get('ok'): h4_ok=True
    if d.get('hop')=='H5-UP' and d.get('ok'): h5_ok=True
print('hops:', sorted(hops))
print('TX_to_servo(H3):', 'PASS' if h3_ok else 'FAIL')
print('RX_from_servo(H4):', 'PASS' if h4_ok else 'FAIL')
print('UP_to_cloud(H5):', 'PASS' if h5_ok else 'FAIL')
if h3_ok and h4_ok and h5_ok:
    print('ROUNDTRIP: PASS')
elif h3_ok and not h4_ok:
    print('ROUNDTRIP: BLOCKED_AT_STM32_REPLY (SC171 TX ok, no valid STATUS frame back)')
else:
    print('ROUNDTRIP: FAIL_BEFORE_STM32')
PY
echo "=== /api/status ==="
curl -s http://127.0.0.1:8000/api/status; echo
