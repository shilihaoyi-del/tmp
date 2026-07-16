"""Smoke-test full HTTP flow against a running backend (simulator expected)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def main() -> int:
    print(f"==> smoke against {BASE}")
    code, health = call("GET", "/api/health")
    assert code == 200 and health.get("ok"), health
    print("OK health", health)

    # wait for simulator ticks
    deadline = time.time() + 8
    status = {}
    while time.time() < deadline:
        code, status = call("GET", "/api/status")
        assert code == 200, status
        if status.get("device_online") and status.get("control_hz", 0) > 0:
            break
        time.sleep(0.4)
    else:
        print("FAIL status never became live:", status)
        return 1

    print(
        "OK status",
        {
            "source": status.get("source"),
            "mode": status.get("mode"),
            "device_online": status.get("device_online"),
            "stm32_online": status.get("stm32_online"),
            "pc_online": status.get("pc_online"),
            "latency_ms": status.get("latency_ms"),
            "control_hz": status.get("control_hz"),
            "carrier": status.get("carrier"),
            "target0": (status.get("target") or [None])[0],
        },
    )

    code, paused = call("POST", "/api/control", {"action": "pause"})
    assert code == 200 and paused.get("mode") == "paused", paused
    print("OK pause")

    code, running = call("POST", "/api/control", {"action": "start"})
    assert code == 200 and running.get("mode") == "running", running
    print("OK start")

    code, estop = call("POST", "/api/control", {"action": "estop"})
    assert code == 200 and estop.get("estop") is True, estop
    print("OK estop")

    code, reset = call("POST", "/api/control", {"action": "reset"})
    assert code == 200 and reset.get("estop") is False, reset
    print("OK reset")

    code, started = call("POST", "/api/control", {"action": "start"})
    assert code == 200, started

    code, metrics = call("GET", "/api/metrics")
    assert code == 200 and "traffic" in metrics, metrics
    print(
        "OK metrics",
        {
            "forward_hz": metrics["traffic"].get("forward_hz"),
            "pc_cmd_forwarded": metrics["traffic"].get("pc_cmd_forwarded"),
            "ready_for": metrics.get("ready_for"),
        },
    )

    code, scenarios = call("GET", "/api/metrics/scenarios")
    assert code == 200 and scenarios.get("scenarios"), scenarios
    print("OK scenarios", len(scenarios["scenarios"]))

    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
