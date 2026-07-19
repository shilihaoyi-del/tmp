#!/usr/bin/env bash
set +e
echo "=== bridge hops ==="
grep -E 'H1-MQTT|H2-PACK|H3-UART|9901' /tmp/sc171v2_servo_bridge.log | tail -30
echo "=== cdc TX containing aa/AA protocol? ==="
# python scan for 0xAA 0x55 in log file as escaped or raw
python3 - <<'PY'
import re
path='/tmp/cdc_pty_bridge.log'
try:
    data=open(path,'rb').read()
except Exception as e:
    print('no log', e); raise SystemExit
# look for AA 55 in binary and text forms
print('file_size', len(data))
print('raw_AA55_count', data.count(bytes([0xAA,0x55])))
text=data.decode('utf-8','replace')
# TX lines
txs=[ln for ln in text.splitlines() if '[TX]' in ln]
print('tx_lines', len(txs))
for ln in txs[-8:]:
    print(ln[:200])
# search AA 55 hex in text
hits=[ln for ln in text.splitlines() if 'AA' in ln and '55' in ln and '[TX]' in ln]
print('tx_hex_like', len(hits))
# also look for \\xaa in repr style
hits2=[ln for ln in txs if '\\xaa' in ln.lower() or 'xaa' in ln.lower() or '\\xaaU' in ln]
print('tx_bytes_repr_hits', len(hits2))
for ln in hits2[-5:]:
    print(ln[:220])
PY
echo "=== processes ==="
pgrep -af 'servo_bridge|cdc_pty|mqtt_agent' || true
echo "=== usb ==="
lsusb | grep -i 1a86 || true
