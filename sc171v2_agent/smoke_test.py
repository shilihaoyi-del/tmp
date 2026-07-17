#!/usr/bin/env python3
"""Quick MQTT smoke: publish heartbeat+status once, wait for one cmd."""
import json
import time
import paho.mqtt.client as mqtt

HOST = "121.41.67.80"
PORT = 1883


def main():
    got = {"n": 0}

    def on_connect(c, u, f, rc):
        print("connected rc=%s" % rc, flush=True)
        c.subscribe("arm/device/cmd", 1)
        ts = int(time.time() * 1000)
        c.publish(
            "arm/device/heartbeat",
            json.dumps({"ts_ms": ts, "online": True, "module_id": "SC171V2"}),
        )
        c.publish(
            "arm/device/status",
            json.dumps(
                {
                    "seq": 1,
                    "ts_ms": ts,
                    "online": True,
                    "stm32_online": False,
                    "mode": "idle",
                    "target": [1, 2, 3, 4, 5, 6],
                    "actual": [1, 2, 3, 4, 5, 6],
                    "fault": "",
                    "estop": False,
                    "carrier": "Wi-Fi",
                }
            ),
        )
        print("published hb+status", flush=True)

    def on_message(c, u, m):
        got["n"] += 1
        print("RX %s %s" % (m.topic, m.payload[:180]), flush=True)

    cl = mqtt.Client(client_id="sc171v2-smoke")
    cl.on_connect = on_connect
    cl.on_message = on_message
    cl.connect(HOST, PORT, 30)
    cl.loop_start()
    time.sleep(6)
    print("recv_count=%s" % got["n"], flush=True)
    cl.loop_stop()
    cl.disconnect()


if __name__ == "__main__":
    main()
