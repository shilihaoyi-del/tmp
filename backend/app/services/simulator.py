"""In-process hardware simulator for Fibocom SC171V2 + PC vision packaging.

Runs without Mosquitto / real module. Injects:
  - PC heartbeats + joint commands (arm/pc/cmd path via ArmStateService)
  - SC171V2 heartbeats + device status (actual lagging target)
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Optional

from app.config import Settings, get_settings
from app.models.schemas import ControlAction, DeviceStatus, PcCommand, SystemMode
from app.services.arm_state import ArmStateService, arm_state

logger = logging.getLogger(__name__)


class HardwareSimulator:
    def __init__(
        self,
        state: Optional[ArmStateService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.state = state or arm_state
        self.settings = settings or get_settings()
        self._task: Optional[asyncio.Task] = None
        self._t0 = time.time()
        self._seq = 0
        self._actual = [0.0] * 6
        self._started = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._t0 = time.time()
        self._task = asyncio.create_task(self._loop(), name="hardware-simulator")
        logger.info("Hardware simulator started (SC171V2 + PC mock)")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Hardware simulator stopped")

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _wave_targets(self, t: float) -> list[float]:
        return [
            math.sin(t * 0.7) * 40.0,
            math.sin(t * 0.55 + 0.4) * 28.0,
            math.cos(t * 0.65) * 32.0,
            math.sin(t * 0.9 + 1.0) * 22.0,
            math.cos(t * 0.45) * 45.0,
            (math.sin(t * 0.35) * 0.5 + 0.5) * 85.0,
        ]

    def _smooth_actual(self, target: list[float], alpha: float = 0.18) -> list[float]:
        out: list[float] = []
        for i, v in enumerate(target):
            self._actual[i] += (v - self._actual[i]) * alpha
            # small sensor noise
            noise = math.sin(time.time() * 8.0 + i) * 0.35
            out.append(self._actual[i] + noise)
        return out

    async def _loop(self) -> None:
        # Auto-arm the session once for demo convenience
        await self.state.handle_control(ControlAction.START)
        self._started = True
        tick = 0
        hz = max(5, min(30, self.settings.control_hz_target))
        period = 1.0 / hz

        while True:
            try:
                t = time.time() - self._t0
                self._seq += 1
                tick += 1

                # PC side packaging: heartbeat + joint cmd
                await self.state.handle_pc_heartbeat(self._now_ms())
                if self.state.mode == SystemMode.RUNNING and not self.state.estop:
                    targets = self._wave_targets(t)
                    await self.state.handle_pc_cmd(
                        PcCommand(
                            seq=self._seq,
                            ts_ms=self._now_ms(),
                            ttl_ms=self.settings.command_ttl_ms,
                            target=targets,
                            estop=False,
                        )
                    )
                    # Remember last "gesture" label for packaging UI
                    gestures = ["Swipe Right", "Swipe Up", "Swipe Left", "Pinch", "Expand", "Swipe V"]
                    self.state.last_gesture = gestures[tick % len(gestures)]

                # SC171V2 hero: heartbeat + telemetry
                await self.state.handle_device_heartbeat(self._now_ms())
                actual = self._smooth_actual(list(self.state.target))
                # Simulate network RTT ~12-28ms stamped in the past
                rtt = 12.0 + 8.0 * (0.5 + 0.5 * math.sin(t * 1.3))
                status = DeviceStatus(
                    seq=self._seq,
                    ts_ms=self._now_ms() - int(rtt),
                    online=True,
                    stm32_online=True,
                    mode=self.state.mode,
                    target=list(self.state.target),
                    actual=actual,
                    fault="" if not self.state.estop else "emergency_stop",
                    estop=self.state.estop,
                    latency_ms=rtt,
                    carrier="5G-SIM",
                )
                await self.state.handle_device_status(status)

                await asyncio.sleep(period)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("simulator tick failed")
                await asyncio.sleep(0.5)


hardware_simulator = HardwareSimulator()
