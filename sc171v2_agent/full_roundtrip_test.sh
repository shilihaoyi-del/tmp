#!/usr/bin/env bash
# Full round-trip test for JOINT downlink + STATUS uplink
set -euo pipefail
OUT=/tmp/rt_full.log
rm -f "$OUT"
timeout 10 mosquitto_sub -h 127.0.0.1 -t 'arm/device/trace' -t 'arm/device/status' -v >"$OUT" &
SPID=$!
sleep 1
TS=$(date +%s%3N)
echo "PUBLISH JOINT seq=9920"
mosquitto_pub -h 127.0.0.1 -t 'arm/device/cmd' -q 1 -m "{\"seq\":9920,\"ts_ms\":$TS,\"ttl_ms\":5000,\"mode\":\"running\",\"target\":[12,18,-12,2,6,35],\"estop\":false}"
sleep 4
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true

echo "========== TRACE =========="
grep -E 'H1-MQTT|H2-PACK|H3-UART|H4-RX|H5-UP' "$OUT" | head -50
echo
echo "========== VERDICT =========="
python3 - <<'PY'
import json
h1=h2=h3=h4=h5=False
status_cmd=False
actual=None
rtt=None
for ln in open('/tmp/rt_full.log'):
    if 'arm/device/trace ' not in ln:
        continue
    d=json.loads(ln.split(' ',1)[1])
    hop=d.get('hop')
    if hop=='H1-MQTT' and d.get('seq')==9920: h1=True
    if hop=='H2-PACK' and d.get('cmd')==1: h2=True
    if hop=='H3-UART' and d.get('ok'): h3=True
    if hop=='H4-RX' and d.get('ok') and d.get('cmd')==129:
        h4=True; status_cmd=True; rtt=d.get('rtt_ms')
    if hop=='H5-UP' and d.get('ok') and d.get('actual'):
        h5=True; actual=d.get('actual')
print('H1 downlink MQTT :', 'PASS' if h1 else 'FAIL')
print('H2 pack JOINT    :', 'PASS' if h2 else 'FAIL')
print('H3 UART TX       :', 'PASS' if h3 else 'FAIL')
print('H4 STATUS RX 0x81:', 'PASS' if h4 else 'FAIL', '(rtt_ms=%s)'%rtt if rtt is not None else '')
print('H5 upload cloud  :', 'PASS' if h5 else 'FAIL', 'actual=%s'%actual if actual else '')
ok = h1 and h2 and h3 and h4 and h5
print('ROUNDTRIP        :', 'PASS' if ok else 'FAIL')
PY
echo
curl -s http://127.0.0.1:8000/api/health; echo
