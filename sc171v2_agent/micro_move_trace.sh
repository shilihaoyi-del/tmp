#!/usr/bin/env bash
# Micro move + hop trace: SC171 TX -> SC171 RX
set -eu
BROKER=${1:-127.0.0.1}
ANG=${2:-8}
SEQ=$((9100 + RANDOM % 800))
TS=$(date +%s%3N)

echo "=== micro move base=$ANG seq=$SEQ ==="
TMP=/tmp/arm_trace_micro_$$.log
timeout 8 mosquitto_sub -h "$BROKER" -t arm/device/trace -v >"$TMP" &
SUB=$!
sleep 0.8

mosquitto_pub -h "$BROKER" -t arm/device/cmd -q 1 -m "{\"seq\":$SEQ,\"ts_ms\":$TS,\"ttl_ms\":8000,\"mode\":\"running\",\"target\":[$ANG,0,0,0,0,0],\"estop\":false}"

sleep 2.8
TS2=$(date +%s%3N)
mosquitto_pub -h "$BROKER" -t arm/device/cmd -q 1 -m "{\"seq\":$((SEQ+1)),\"ts_ms\":$TS2,\"ttl_ms\":8000,\"mode\":\"running\",\"target\":[0,0,0,0,0,0],\"estop\":false}"

wait $SUB 2>/dev/null || true

python3 - "$TMP" "$SEQ" <<'PY'
import json,sys
path,seq=sys.argv[1],int(sys.argv[2])
lines=open(path,encoding="utf-8",errors="ignore").read().splitlines()
hops={}
seen_h1=False
h3a=h3l=None
h4=h5=None
uart_seq=None
for ln in lines:
    if "arm/device/trace" not in ln:
        continue
    try:
        d=json.loads(ln.split(" ",1)[1])
    except Exception:
        continue
    hop=d.get("hop")
    if hop=="H1-MQTT" and d.get("seq")==seq:
        seen_h1=True
        hops["H1"]=d
    if not seen_h1:
        continue
    if hop=="H2-PACK" and d.get("mqtt_seq")==seq:
        hops["H2-%s"%d.get("protocol")]=d
        uart_seq=d.get("uart_seq")
    if hop=="H3-UART" and d.get("ok"):
        if d.get("protocol")=="aa55" and h3a is None:
            h3a=d
        if d.get("protocol")=="lobot" and h3l is None:
            h3l=d
    if hop=="H4-RX" and d.get("ok") and d.get("cmd") in (129,0x81) and h4 is None:
        if uart_seq is None or d.get("seq")==uart_seq or d.get("rtt_ms") is not None:
            h4=d
    if hop=="H5-UP" and d.get("ok") and d.get("actual") is not None and h5 is None:
        h5=d

def pr(name,d):
    if not d:
        print("%s: MISS"%name)
        return False
    keep={k:d.get(k) for k in ("ok","protocol","joints","bytes","cmd","seq","uart_seq","mqtt_seq","rtt_ms","hex","note","source","actual","stm32_online","frames") if k in d}
    print("%s: PASS %s"%(name,keep))
    return True

print("=== hop summary mqtt_seq=%s ==="%seq)
pr("H1-MQTT", hops.get("H1"))
pr("H2-PACK/aa55", hops.get("H2-aa55"))
pr("H2-PACK/lobot", hops.get("H2-lobot"))
pr("H3-UART/aa55", h3a)
pr("H3-UART/lobot", h3l)
pr("H4-RX", h4)
pr("H5-UP", h5)
tx=bool(h3a or h3l)
rx=bool(h4)
seq_match = bool(h4 and uart_seq is not None and h4.get("seq")==uart_seq)
print("---")
print("SC171V2 TX: %s"%("PASS" if tx else "FAIL"))
print("SC171V2 RX: %s"%("PASS" if rx else "FAIL"))
print("SEQ MATCH:  %s (tx_uart_seq=%s rx_seq=%s)"%("PASS" if seq_match else "FAIL", uart_seq, None if not h4 else h4.get("seq")))
print("ROUNDTRIP:  %s rtt_ms=%s"%("PASS" if (tx and rx) else "FAIL", None if not h4 else h4.get("rtt_ms")))
PY

echo "=== /api/status ==="
curl -s http://127.0.0.1:8000/api/status; echo
