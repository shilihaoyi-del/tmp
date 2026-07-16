"""Central arm / system state store."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Callable, Optional

from app.config import Settings, get_settings
from app.models.schemas import (
    ControlAction,
    DeviceCommand,
    DeviceStatus,
    GestureEvent,
    SystemMode,
    SystemStatusResponse,
)
from app.services.gesture_mapper import map_gesture_to_joints
from app.services.safety import clamp_joints


PublishFn = Callable[[str, dict[str, Any], bool], None]


class ArmStateService:
    """Thread-safe-ish state managed from the asyncio event loop."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.mode = SystemMode.IDLE
        self.target = [0.0] * 6
        self.actual = [0.0] * 6
        self.fault = ""
        self.estop = False
        self.seq = 0
        self.last_gesture = ""
        self.latency_ms = 0.0
        self.stm32_online = False

        self.pc_online = False
        self.device_online = False
        self._pc_last_hb = 0.0
        self._device_last_hb = 0.0

        self._cmd_timestamps: deque[float] = deque(maxlen=100)
        self._publish: Optional[PublishFn] = None
        self._lock = asyncio.Lock()

    def set_publisher(self, fn: PublishFn) -> None:
        self._publish = fn

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def control_hz(self) -> float:
        now = time.time()
        # Drop old samples
        while self._cmd_timestamps and now - self._cmd_timestamps[0] > 1.0:
            self._cmd_timestamps.popleft()
        return float(len(self._cmd_timestamps))

    def snapshot(self) -> SystemStatusResponse:
        return SystemStatusResponse(
            mode=self.mode,
            pc_online=self.pc_online,
            device_online=self.device_online,
            stm32_online=self.stm32_online,
            target=list(self.target),
            actual=list(self.actual),
            fault=self.fault,
            estop=self.estop,
            latency_ms=self.latency_ms,
            control_hz=self.control_hz(),
            last_gesture=self.last_gesture,
            seq=self.seq,
        )

    def _emit_web_status(self) -> None:
        if not self._publish:
            return
        snap = self.snapshot()
        self._publish("arm/web/status", snap.model_dump(), False)

    def _emit_device_cmd(self) -> None:
        if not self._publish:
            return
        self.seq += 1
        cmd = DeviceCommand(
            seq=self.seq,
            ts_ms=self._now_ms(),
            ttl_ms=self.settings.command_ttl_ms,
            mode=self.mode,
            target=list(self.target),
            estop=self.estop,
        )
        self._publish("arm/device/cmd", cmd.model_dump(), False)
        self._cmd_timestamps.append(time.time())

    def _emit_mode(self) -> None:
        if not self._publish:
            return
        self._publish(
            "arm/device/mode",
            {
                "mode": self.mode.value,
                "estop": self.estop,
                "ts_ms": self._now_ms(),
                "seq": self.seq,
            },
            True,
        )

    async def handle_control(self, action: ControlAction) -> SystemStatusResponse:
        async with self._lock:
            if action == ControlAction.ESTOP:
                self.estop = True
                self.mode = SystemMode.ESTOP
                self.fault = "emergency_stop"
            elif action == ControlAction.START:
                if self.estop:
                    return self.snapshot()
                self.mode = SystemMode.RUNNING
                self.fault = ""
            elif action == ControlAction.PAUSE:
                if self.mode == SystemMode.RUNNING:
                    self.mode = SystemMode.PAUSED
            elif action == ControlAction.RESUME:
                if self.mode == SystemMode.PAUSED and not self.estop:
                    self.mode = SystemMode.RUNNING
            elif action == ControlAction.HOLD:
                self.mode = SystemMode.HOLD
            elif action == ControlAction.RESET:
                self.estop = False
                self.fault = ""
                self.mode = SystemMode.IDLE
                self.target = [0.0] * 6

            self._emit_mode()
            self._emit_device_cmd()
            self._emit_web_status()
            return self.snapshot()

    async def handle_gesture(self, event: GestureEvent) -> SystemStatusResponse:
        async with self._lock:
            self._pc_last_hb = time.time()
            self.pc_online = True
            self.last_gesture = event.gesture

            if self.mode != SystemMode.RUNNING or self.estop:
                self._emit_web_status()
                return self.snapshot()

            # TTL check on incoming gesture
            age = self._now_ms() - event.ts_ms
            if age > self.settings.command_ttl_ms * 2:
                self._emit_web_status()
                return self.snapshot()

            result = map_gesture_to_joints(event, self.target, self.settings)
            if result.applied:
                self.target = clamp_joints(result.joints, self.settings)
                self._emit_device_cmd()

            self._emit_web_status()
            return self.snapshot()

    async def handle_device_status(self, status: DeviceStatus) -> None:
        async with self._lock:
            self._device_last_hb = time.time()
            self.device_online = True
            self.stm32_online = status.stm32_online
            self.actual = list(status.actual) if status.actual else self.actual
            if status.target and len(status.target) == 6:
                # Device may echo target; keep ours as source of truth when running
                pass
            if status.estop:
                self.estop = True
                self.mode = SystemMode.ESTOP
            if status.fault:
                self.fault = status.fault
            if status.ts_ms:
                self.latency_ms = max(0.0, float(self._now_ms() - status.ts_ms))
            self._emit_web_status()

    async def handle_pc_heartbeat(self, ts_ms: int = 0) -> None:
        async with self._lock:
            self._pc_last_hb = time.time()
            self.pc_online = True

    async def handle_device_heartbeat(self, ts_ms: int = 0) -> None:
        async with self._lock:
            self._device_last_hb = time.time()
            self.device_online = True

    async def tick_watchdog(self) -> None:
        """Periodic online / timeout check."""
        async with self._lock:
            now = time.time()
            timeout = self.settings.heartbeat_timeout_sec

            if self.pc_online and (now - self._pc_last_hb) > timeout:
                self.pc_online = False
                if self.mode == SystemMode.RUNNING:
                    # PC lost -> hold position
                    self.mode = SystemMode.HOLD
                    self.fault = "pc_timeout"
                    self._emit_mode()
                    self._emit_device_cmd()

            if self.device_online and (now - self._device_last_hb) > timeout:
                self.device_online = False
                self.stm32_online = False
                if self.mode == SystemMode.RUNNING:
                    self.mode = SystemMode.HOLD
                    self.fault = "device_timeout"
                    self._emit_mode()

            self._emit_web_status()


# Singleton used by API + MQTT
arm_state = ArmStateService()
