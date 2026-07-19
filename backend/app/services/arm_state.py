"""Cloud bridge state — forward to Fibocom SC171V2, aggregate telemetry for web."""

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
    PcCommand,
    Pose6,
    SystemMode,
    SystemStatusResponse,
)
from app.services.gesture_mapper import map_gesture_to_joints
from app.services.metrics import metrics_store
from app.services.safety import clamp_joints, is_command_expired


PublishFn = Callable[[str, dict[str, Any], bool], None]


class ArmStateService:
    """Thin cloud bridge: gate modes, clamp, forward to SC171V2, mirror web status."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.mode = SystemMode.IDLE
        # Default target = working initial; Z-line home is separate (VIEW_HOME / home_pose)
        self.target = [1.92, -89.76, -31.92, -210.0, -3.84, 45.0]
        self.actual = list(self.target)
        self.pose: Optional[Pose6] = None
        self.ik_ok = True
        self.servo_online = [False] * 6
        self._pending_pose: Optional[Pose6] = None
        self._pending_pose_delta: Optional[Pose6] = None
        self._pending_gripper: Optional[float] = None
        self.fault = ""
        self.estop = False
        self.seq = 0
        self.last_gesture = ""
        self.latency_ms = 0.0
        self.stm32_online = False
        self.carrier = self.settings.default_carrier
        self.source = "live"

        self.pc_online = False
        self.device_online = False
        self._pc_last_hb = 0.0
        self._device_last_hb = 0.0

        self._cmd_timestamps: deque[float] = deque(maxlen=100)
        self._publish: Optional[PublishFn] = None
        self._lock = asyncio.Lock()

    def set_source(self, source: str) -> None:
        self.source = source

    def set_publisher(self, fn: PublishFn) -> None:
        self._publish = fn

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def control_hz(self) -> float:
        now = time.time()
        while self._cmd_timestamps and now - self._cmd_timestamps[0] > 1.0:
            self._cmd_timestamps.popleft()
        return float(len(self._cmd_timestamps))

    def _hb_age_ms(self) -> float:
        if self._device_last_hb <= 0:
            return 0.0
        return max(0.0, (time.time() - self._device_last_hb) * 1000.0)

    def snapshot(self) -> SystemStatusResponse:
        return SystemStatusResponse(
            module_id=self.settings.module_id,
            module_name=self.settings.module_name,
            carrier=self.carrier or self.settings.default_carrier,
            link="up" if self.device_online else "down",
            hb_age_ms=self._hb_age_ms(),
            mode=self.mode,
            device_online=self.device_online,
            stm32_online=self.stm32_online,
            pc_online=self.pc_online,
            last_gesture=self.last_gesture,
            target=list(self.target),
            actual=list(self.actual),
            pose=self.pose,
            ik_ok=self.ik_ok,
            servo_online=list(self.servo_online),
            fault=self.fault,
            estop=self.estop,
            latency_ms=self.latency_ms,
            control_hz=self.control_hz(),
            seq=self.seq,
            source=self.source,
        )

    def _emit_web_status(self) -> None:
        if not self._publish:
            return
        self._publish("arm/web/status", self.snapshot().model_dump(mode="json"), False)

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
            pose=self._pending_pose,
            pose_delta=self._pending_pose_delta,
            gripper=self._pending_gripper,
            estop=self.estop,
        )
        # One-shot pose fields — clear after emit so next joint-only cmds stay clean
        self._pending_pose = None
        self._pending_pose_delta = None
        self._pending_gripper = None
        self._publish("arm/device/cmd", cmd.model_dump(mode="json", exclude_none=True), False)
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
                "module_id": self.settings.module_id,
            },
            True,
        )

    def _can_forward_motion(self) -> bool:
        return self.mode == SystemMode.RUNNING and not self.estop

    async def handle_control(self, action: ControlAction) -> SystemStatusResponse:
        async with self._lock:
            metrics_store.record_control()
            if action == ControlAction.ESTOP:
                self.estop = True
                self.mode = SystemMode.ESTOP
                self.fault = "emergency_stop"
            elif action == ControlAction.START:
                # start also clears soft pause; estop requires explicit reset first
                if self.estop:
                    return self.snapshot()
                self.mode = SystemMode.RUNNING
                self.fault = ""
            elif action == ControlAction.PAUSE:
                if self.mode == SystemMode.RUNNING:
                    self.mode = SystemMode.PAUSED
            elif action == ControlAction.RESET:
                self.estop = False
                self.fault = ""
                self.mode = SystemMode.IDLE

            self._emit_mode()
            self._emit_device_cmd()
            self._emit_web_status()
            return self.snapshot()

    async def handle_pc_cmd(self, cmd: PcCommand) -> SystemStatusResponse:
        """Primary path: PC joint targets -> clamp -> forward to SC171V2."""
        async with self._lock:
            self._pc_last_hb = time.time()
            self.pc_online = True

            if cmd.estop:
                self.estop = True
                self.mode = SystemMode.ESTOP
                self.fault = "emergency_stop"
                metrics_store.record_pc_cmd(forwarded=True)
                self._emit_mode()
                self._emit_device_cmd()
                self._emit_web_status()
                return self.snapshot()

            # Vision may run while IDLE: do NOT auto-START. Arm moves only after
            # explicit ControlAction.START (web/console) puts mode=RUNNING.
            if is_command_expired(cmd.ts_ms, self._now_ms(), cmd.ttl_ms or self.settings.command_ttl_ms):
                metrics_store.record_pc_cmd(forwarded=False)
                self._emit_web_status()
                return self.snapshot()

            if not self._can_forward_motion():
                metrics_store.record_pc_cmd(forwarded=False)
                self._emit_web_status()
                return self.snapshot()

            if cmd.target and len(cmd.target) == 6:
                self.target = clamp_joints(list(cmd.target), self.settings)
            self._pending_pose = cmd.pose
            self._pending_pose_delta = cmd.pose_delta
            self._pending_gripper = cmd.gripper
            # No real SC171V2 feedback yet: mirror target so web 3D/charts move
            if not self.device_online:
                self.actual = list(self.target)
            metrics_store.record_pc_cmd(forwarded=True)
            self._emit_device_cmd()
            self._emit_web_status()
            return self.snapshot()

    async def handle_pc_heartbeat(self, ts_ms: int = 0) -> None:
        async with self._lock:
            self._pc_last_hb = time.time()
            self.pc_online = True
            if (
                self.mode == SystemMode.HOLD
                and self.fault == "pc_timeout"
                and not self.estop
            ):
                self.mode = SystemMode.RUNNING
                self.fault = ""
                self._emit_mode()
                self._emit_web_status()

    async def handle_gesture(self, event: GestureEvent) -> SystemStatusResponse:
        """Debug bypass: map gesture on server (not the production path)."""
        async with self._lock:
            self._pc_last_hb = time.time()
            self.pc_online = True
            self.last_gesture = event.gesture

            if not self._can_forward_motion():
                self._emit_web_status()
                return self.snapshot()

            age = self._now_ms() - event.ts_ms
            if age > self.settings.command_ttl_ms * 2:
                self._emit_web_status()
                return self.snapshot()

            result = map_gesture_to_joints(event, self.target, self.settings)
            if result.applied:
                self.target = clamp_joints(result.joints, self.settings)
                if result.pose_delta:
                    self._pending_pose_delta = Pose6(**result.pose_delta)
                if result.gripper is not None:
                    self._pending_gripper = float(result.gripper)
                self._emit_device_cmd()

            self._emit_web_status()
            return self.snapshot()

    async def handle_device_status(self, status: DeviceStatus) -> None:
        async with self._lock:
            self._device_last_hb = time.time()
            self.device_online = True
            self.stm32_online = status.stm32_online
            free_move = str(status.carrier or "").upper() == "FREE_MOVE"
            if free_move:
                self.source = "free_move"
                self.last_gesture = "FREE_MOVE"
                self.mode = SystemMode.RUNNING
            if status.actual and len(status.actual) == 6:
                self.actual = list(status.actual)
                # Mirror into target so web consoles that prefer target still follow the arm
                if free_move:
                    self.target = list(status.actual)
            elif status.target and len(status.target) == 6 and free_move:
                self.target = list(status.target)
                self.actual = list(status.target)
            if status.pose is not None:
                self.pose = status.pose
            self.ik_ok = bool(status.ik_ok)
            if status.servo_online and len(status.servo_online) == 6:
                self.servo_online = list(status.servo_online)
            if status.carrier:
                self.carrier = status.carrier
            if status.estop:
                self.estop = True
                self.mode = SystemMode.ESTOP
            if status.fault:
                self.fault = status.fault
            if status.ts_ms:
                self.latency_ms = max(0.0, float(self._now_ms() - status.ts_ms))
            elif status.latency_ms:
                self.latency_ms = float(status.latency_ms)
            metrics_store.record_device_status(self.latency_ms)
            self._emit_web_status()

    async def handle_device_heartbeat(self, ts_ms: int = 0) -> None:
        async with self._lock:
            self._device_last_hb = time.time()
            self.device_online = True
            self._emit_web_status()

    async def tick_watchdog(self) -> None:
        async with self._lock:
            now = time.time()
            timeout = self.settings.heartbeat_timeout_sec

            if self.pc_online and (now - self._pc_last_hb) > timeout:
                self.pc_online = False
                if self.mode == SystemMode.RUNNING:
                    self.mode = SystemMode.HOLD
                    self.fault = "pc_timeout"
                    self._emit_mode()
                    self._emit_device_cmd()

            if self.device_online and (now - self._device_last_hb) > timeout:
                self.device_online = False
                self.stm32_online = False
                if self.mode == SystemMode.RUNNING:
                    self.mode = SystemMode.HOLD
                    self.fault = "sc171v2_timeout"
                    self._emit_mode()

            self._emit_web_status()


arm_state = ArmStateService()
