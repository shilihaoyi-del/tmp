"""Runtime metrics collector — reserved for stress / perf / soak monitoring."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Deque, Optional


@dataclass
class LatencySample:
    ts_ms: int
    latency_ms: float
    path: str  # pc_cmd | device_status | http_control | ...


@dataclass
class MetricsStore:
    """In-memory counters + ring buffers. Swap to Redis/Prometheus later."""

    started_at: float = field(default_factory=time.time)
    lock: Lock = field(default_factory=Lock)

    # Counters
    pc_cmd_total: int = 0
    pc_cmd_forwarded: int = 0
    pc_cmd_dropped: int = 0
    device_status_total: int = 0
    control_total: int = 0
    mqtt_publish_total: int = 0
    mqtt_error_total: int = 0
    http_request_total: int = 0

    # Rolling windows
    latencies: Deque[LatencySample] = field(default_factory=lambda: deque(maxlen=600))
    cmd_hz_marks: Deque[float] = field(default_factory=lambda: deque(maxlen=200))

    # Bench / stress harness reservation
    bench_active: bool = False
    bench_id: Optional[str] = None
    bench_started_at: Optional[float] = None
    bench_target_hz: int = 0
    bench_notes: str = ""

    def record_pc_cmd(self, *, forwarded: bool) -> None:
        with self.lock:
            self.pc_cmd_total += 1
            if forwarded:
                self.pc_cmd_forwarded += 1
                self.cmd_hz_marks.append(time.time())
            else:
                self.pc_cmd_dropped += 1

    def record_device_status(self, latency_ms: float) -> None:
        with self.lock:
            self.device_status_total += 1
            self.latencies.append(
                LatencySample(
                    ts_ms=int(time.time() * 1000),
                    latency_ms=float(latency_ms),
                    path="device_status",
                )
            )

    def record_control(self) -> None:
        with self.lock:
            self.control_total += 1

    def record_mqtt_publish(self, ok: bool = True) -> None:
        with self.lock:
            self.mqtt_publish_total += 1
            if not ok:
                self.mqtt_error_total += 1

    def record_http(self) -> None:
        with self.lock:
            self.http_request_total += 1

    def record_latency(self, latency_ms: float, path: str) -> None:
        with self.lock:
            self.latencies.append(
                LatencySample(
                    ts_ms=int(time.time() * 1000),
                    latency_ms=float(latency_ms),
                    path=path,
                )
            )

    def _cmd_hz(self) -> float:
        now = time.time()
        while self.cmd_hz_marks and now - self.cmd_hz_marks[0] > 1.0:
            self.cmd_hz_marks.popleft()
        return float(len(self.cmd_hz_marks))

    def _latency_stats(self) -> dict[str, float]:
        vals = [s.latency_ms for s in self.latencies]
        if not vals:
            return {"count": 0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(vals)
        n = len(ordered)

        def pct(p: float) -> float:
            idx = min(n - 1, max(0, int(round((p / 100.0) * (n - 1)))))
            return float(ordered[idx])

        return {
            "count": float(n),
            "avg_ms": float(sum(ordered) / n),
            "p50_ms": pct(50),
            "p95_ms": pct(95),
            "max_ms": float(ordered[-1]),
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            uptime = time.time() - self.started_at
            return {
                "module_id": "SC171V2",
                "uptime_sec": round(uptime, 1),
                "ready_for": ["stress_test", "perf_test", "soak_test", "link_monitor"],
                "traffic": {
                    "pc_cmd_total": self.pc_cmd_total,
                    "pc_cmd_forwarded": self.pc_cmd_forwarded,
                    "pc_cmd_dropped": self.pc_cmd_dropped,
                    "device_status_total": self.device_status_total,
                    "control_total": self.control_total,
                    "mqtt_publish_total": self.mqtt_publish_total,
                    "mqtt_error_total": self.mqtt_error_total,
                    "http_request_total": self.http_request_total,
                    "forward_hz": self._cmd_hz(),
                },
                "latency": self._latency_stats(),
                "bench": {
                    "active": self.bench_active,
                    "bench_id": self.bench_id,
                    "started_at": self.bench_started_at,
                    "target_hz": self.bench_target_hz,
                    "notes": self.bench_notes,
                    "reserved": True,
                },
            }

    def history(self, limit: int = 120) -> dict[str, Any]:
        with self.lock:
            items = list(self.latencies)[-limit:]
            return {
                "points": [
                    {"ts_ms": s.ts_ms, "latency_ms": s.latency_ms, "path": s.path}
                    for s in items
                ],
                "reserved_series": [
                    "rtt_pc_to_module_ms",
                    "rtt_module_to_stm32_ms",
                    "cmd_drop_rate",
                    "mqtt_reconnect_count",
                ],
            }

    def start_bench(self, bench_id: str, target_hz: int = 25, notes: str = "") -> dict[str, Any]:
        with self.lock:
            self.bench_active = True
            self.bench_id = bench_id
            self.bench_started_at = time.time()
            self.bench_target_hz = target_hz
            self.bench_notes = notes or "reserved harness — inject load from external runner"
            return self.snapshot()["bench"]

    def stop_bench(self) -> dict[str, Any]:
        with self.lock:
            self.bench_active = False
            result = {
                "active": False,
                "bench_id": self.bench_id,
                "started_at": self.bench_started_at,
                "stopped_at": time.time(),
                "target_hz": self.bench_target_hz,
                "notes": self.bench_notes,
                "reserved": True,
            }
            self.bench_id = None
            self.bench_started_at = None
            self.bench_target_hz = 0
            self.bench_notes = ""
            return result


# Application scenarios (product narrative + future test matrix)
APPLICATION_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "remote_embodied_demo",
        "name": "远程体感跟随演示",
        "summary": "比赛/展会现场：PC 手势意图经公网到达 SC171V2，驱动机械臂同步跟随。",
        "module_value": ["5G/Wi-Fi 公网接入", "低时延指令通道", "边缘安全保持"],
        "metrics_focus": ["latency_ms", "forward_hz", "hb_age_ms"],
    },
    {
        "id": "industrial_teleop",
        "name": "工业远程遥操作",
        "summary": "产线/危化场景：操作员异地遥操作，模组保障链路可靠与断线保持。",
        "module_value": ["多模网络冗余", "TTL/心跳失效保护", "状态遥测回传"],
        "metrics_focus": ["pc_cmd_dropped", "p95_ms", "sc171v2_timeout"],
    },
    {
        "id": "cloud_robot_link",
        "name": "云边机器人接入",
        "summary": "把机器人执行体快速挂上云控：SC171V2 作为边缘控制面接入 MQTT。",
        "module_value": ["边缘智能模组", "MQTT 会话", "执行器下游桥接"],
        "metrics_focus": ["device_status_total", "mqtt_error_total", "link"],
    },
    {
        "id": "soak_and_stress",
        "name": "长稳 / 压力验证（预留）",
        "summary": "后续对 20–30Hz 指令流、并发观摩端、弱网做压测与性能基线。",
        "module_value": ["链路容量验证", "抖动与丢包可视", "模组在线率"],
        "metrics_focus": ["forward_hz", "p95_ms", "cmd_drop_rate"],
        "bench_ready": True,
    },
]


metrics_store = MetricsStore()
