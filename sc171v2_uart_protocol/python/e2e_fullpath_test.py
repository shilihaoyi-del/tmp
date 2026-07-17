#!/usr/bin/env python3
"""Full-path test: Server -> SC171V2 -> STM32 -> SC171V2 -> Server"""
from __future__ import annotations

import json
import sys
import time
import uuid

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("NEED paho-mqtt")
    sys.exit(2)

BROKER = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 1883

# Unique joints so echo can be distinguished from zero STATUS flood
TARGET = [12.0, -6.0, 3.0, 0.0, 0.0, 0.0]
SEQ = int(time.time()) % 100000
CLIENT = "e2e-%s" % uuid.uuid4().hex[:8]

traces = []
statuses = []
heartbeats = []
ready = {"ok": False}


def on_connect(c, u, f, rc):
    ready["ok"] = rc == 0
    if rc == 0:
        c.subscribe(
            [
                ("arm/device/trace", 0),
                ("arm/device/status", 0),
                ("arm/device/heartbeat", 0),
            ]
        )


def on_message(c, u, msg):
    try:
        d = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    d["_topic"] = msg.topic
    d["_t"] = time.time()
    if msg.topic.endswith("/trace"):
        traces.append(d)
    elif msg.topic.endswith("/status"):
        statuses.append(d)
    elif msg.topic.endswith("/heartbeat"):
        heartbeats.append(d)


c = mqtt.Client(client_id=CLIENT, protocol=mqtt.MQTTv311, clean_session=True)
c.on_connect = on_connect
c.on_message = on_message
c.connect(BROKER, PORT, 30)
c.loop_start()

t0 = time.time()
while time.time() - t0 < 3 and not ready["ok"]:
    time.sleep(0.05)
if not ready["ok"]:
    print("FAIL: cannot connect MQTT %s:%s" % (BROKER, PORT))
    sys.exit(1)

# wait a moment for spontaneous HB/STATUS
time.sleep(1.2)
hb_before = len(heartbeats)
st_before = len(statuses)

payload = {
    "seq": SEQ,
    "ts_ms": int(time.time() * 1000),
    "ttl_ms": 8000,
    "mode": "running",
    "target": TARGET,
    "estop": False,
}
c.publish("arm/device/cmd", json.dumps(payload), qos=1)
print("=== E2E START seq=%s target=%s ===" % (SEQ, TARGET))

# collect for 5s
deadline = time.time() + 5.0
while time.time() < deadline:
    time.sleep(0.05)

# return to zero (best effort)
c.publish(
    "arm/device/cmd",
    json.dumps(
        {
            "seq": SEQ + 1,
            "ts_ms": int(time.time() * 1000),
            "ttl_ms": 5000,
            "mode": "running",
            "target": [0, 0, 0, 0, 0, 0],
            "estop": False,
        }
    ),
    qos=1,
)
time.sleep(1.0)
c.loop_stop()
c.disconnect()


def first_after(items, pred, t_min=0):
    for d in items:
        if d.get("_t", 0) >= t_min and pred(d):
            return d
    return None


# Analyze hops after publish time (approx: last 6s of traces)
pub_t = traces[0]["_t"] if traces else time.time()
# better: find H1 with our seq
h1 = first_after(traces, lambda d: d.get("hop") == "H1-MQTT" and d.get("seq") == SEQ)
t_cmd = h1["_t"] if h1 else (time.time() - 5)

h2_aa = first_after(
    traces,
    lambda d: d.get("hop") == "H2-PACK" and d.get("mqtt_seq") == SEQ and d.get("protocol") == "aa55",
    t_cmd - 0.1,
)
h2_lb = first_after(
    traces,
    lambda d: d.get("hop") == "H2-PACK" and d.get("mqtt_seq") == SEQ and d.get("protocol") == "lobot",
    t_cmd - 0.1,
)
uart_seq = None
if h2_aa:
    uart_seq = h2_aa.get("uart_seq")
elif h2_lb:
    uart_seq = h2_lb.get("uart_seq")

# H3 after H2
h3_aa = first_after(
    traces,
    lambda d: d.get("hop") == "H3-UART" and d.get("ok") and d.get("protocol") == "aa55",
    (h2_aa or h1 or {"_t": t_cmd})["_t"] - 0.05,
)
h3_lb = first_after(
    traces,
    lambda d: d.get("hop") == "H3-UART" and d.get("ok") and d.get("protocol") == "lobot",
    (h2_lb or h1 or {"_t": t_cmd})["_t"] - 0.05,
)

# H4: prefer seq match + joint echo
h4_match = None
h4_any = None
for d in traces:
    if d.get("_t", 0) < t_cmd:
        continue
    if d.get("hop") != "H4-RX" or not d.get("ok") or d.get("cmd") not in (0x81, 129):
        continue
    if h4_any is None:
        h4_any = d
    if uart_seq is not None and d.get("seq") == uart_seq:
        h4_match = d
        break
    joints = d.get("joints") or []
    if joints and abs(float(joints[0]) - TARGET[0]) < 0.5:
        h4_match = d
        break

h5 = first_after(
    traces,
    lambda d: d.get("hop") == "H5-UP" and d.get("ok") and d.get("actual") is not None,
    t_cmd,
)

# Server-visible status after cmd
st_after = [s for s in statuses if s.get("_t", 0) >= t_cmd]
st_echo = None
for s in st_after:
    act = s.get("actual") or []
    tgt = s.get("target") or []
    if tgt and abs(float(tgt[0]) - TARGET[0]) < 0.5:
        st_echo = s
        break
    if act and abs(float(act[0]) - TARGET[0]) < 0.5:
        st_echo = s
        break
st_last = st_after[-1] if st_after else None

hb_after = [h for h in heartbeats if h.get("_t", 0) >= t_cmd - 1.5]
auto_uplink = len(hb_after) > 0 or len(st_after) > 0

results = []


def add(name, ok, detail):
    results.append((name, ok, detail))
    print("%s: %s  %s" % (name, "PASS" if ok else "FAIL", detail))


print("")
print("========== FULL PATH ==========")
add(
    "A1 Server MQTT reachable",
    True,
    "broker=%s:%s client=%s" % (BROKER, PORT, CLIENT),
)
add(
    "A2 SC171 auto uplink (HB/STATUS spontaneous)",
    auto_uplink or (len(heartbeats) > hb_before) or (len(statuses) > st_before),
    "hb=%s status=%s (window)" % (len(hb_after), len(st_after)),
)
add(
    "B1 Server -> SC171 (H1 MQTT cmd)",
    h1 is not None,
    "seq=%s joints=%s"
    % (
        None if not h1 else h1.get("seq"),
        None if not h1 else (h1.get("joints") or h1.get("target")),
    ),
)
add(
    "B2 SC171 pack AA55 (H2)",
    h2_aa is not None,
    "uart_seq=%s hex=%s" % (None if not h2_aa else h2_aa.get("uart_seq"), None if not h2_aa else h2_aa.get("hex")),
)
add(
    "B3 SC171 -> STM32 UART TX (H3 aa55)",
    h3_aa is not None,
    "bytes=%s" % (None if not h3_aa else h3_aa.get("bytes")),
)
add(
    "C1 STM32 -> SC171 any STATUS RX (H4)",
    h4_any is not None,
    "seq=%s joints=%s rtt=%s hex=%s"
    % (
        None if not h4_any else h4_any.get("seq"),
        None if not h4_any else h4_any.get("joints"),
        None if not h4_any else h4_any.get("rtt_ms"),
        None if not h4_any else h4_any.get("hex"),
    ),
)
add(
    "C2 STM32 reply matches cmd (seq/joints)",
    h4_match is not None,
    "expect uart_seq=%s target0=%s got=%s"
    % (uart_seq, TARGET[0], None if not h4_match else {"seq": h4_match.get("seq"), "joints": h4_match.get("joints")}),
)
add(
    "D1 SC171 -> Server upload (H5)",
    h5 is not None,
    "actual=%s stm32_online=%s" % (None if not h5 else h5.get("actual"), None if not h5 else h5.get("stm32_online")),
)
add(
    "D2 Server status reflects cmd/actual",
    st_echo is not None or (st_last is not None and st_last.get("stm32_online")),
    "status=%s"
    % (
        None
        if not (st_echo or st_last)
        else {
            "target": (st_echo or st_last).get("target"),
            "actual": (st_echo or st_last).get("actual"),
            "stm32_online": (st_echo or st_last).get("stm32_online"),
            "device_online": (st_echo or st_last).get("device_online")
            if "device_online" in (st_echo or st_last)
            else None,
        }
    ),
)

# Overall
critical = [
    ("Server->SC171", h1 is not None),
    ("SC171->STM32 TX", h3_aa is not None),
    ("STM32->SC171 RX", h4_any is not None),
    ("SC171->Server", h5 is not None or len(st_after) > 0),
    ("True cmd echo", h4_match is not None),
]
print("")
print("========== VERDICT ==========")
all_link = all(ok for _, ok in critical[:4])
true_echo = critical[4][1]
for name, ok in critical:
    print("%-18s %s" % (name, "PASS" if ok else "FAIL"))
print("---")
if all_link and true_echo:
    print("OVERALL: PASS (full closed loop with matching STATUS)")
elif all_link:
    print("OVERALL: PARTIAL (wire path up, but STM32 STATUS not echoing this cmd)")
else:
    print("OVERALL: FAIL")
print("traces=%s statuses=%s heartbeats=%s" % (len(traces), len(statuses), len(heartbeats)))
