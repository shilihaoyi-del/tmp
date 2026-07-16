"""Pydantic request / response schemas — SC171V2-centric telemetry."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SystemMode(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ESTOP = "estop"
    HOLD = "hold"


class HandSide(str, Enum):
    LEFT = "Left"
    RIGHT = "Right"
    BOTH = "Both"


class GestureEvent(BaseModel):
    """Debug-only gesture payload (PC should normally publish arm/pc/cmd)."""

    seq: int = Field(..., description="Monotonic sequence number")
    ts_ms: int = Field(..., description="Client timestamp in milliseconds")
    gesture: str
    hand: HandSide = HandSide.RIGHT
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    left_gesture: Optional[str] = None
    right_gesture: Optional[str] = None
    left_confidence: float = 0.0
    right_confidence: float = 0.0


class JointAngles(BaseModel):
    """Six joint angles in degrees."""

    joints: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="[base, shoulder, elbow, wrist_pitch, wrist_roll, gripper]",
    )


class PcCommand(BaseModel):
    """Primary PC -> cloud joint command (forwarded to SC171V2)."""

    seq: int
    ts_ms: int
    ttl_ms: int = 500
    target: list[float] = Field(..., min_length=6, max_length=6)
    estop: bool = False


class DeviceCommand(BaseModel):
    """Command forwarded to Fibocom SC171V2."""

    seq: int
    ts_ms: int
    ttl_ms: int = 500
    mode: SystemMode
    target: list[float] = Field(..., min_length=6, max_length=6)
    estop: bool = False


class DeviceStatus(BaseModel):
    """Telemetry uploaded by Fibocom SC171V2."""

    seq: int = 0
    ts_ms: int = 0
    online: bool = True
    stm32_online: bool = False
    mode: SystemMode = SystemMode.IDLE
    target: list[float] = Field(default_factory=lambda: [0.0] * 6)
    actual: list[float] = Field(default_factory=lambda: [0.0] * 6)
    fault: str = ""
    estop: bool = False
    latency_ms: float = 0.0
    carrier: str = ""  # e.g. "5G" / "Wi-Fi" when module reports it


class ControlAction(str, Enum):
    """Operator actions exposed to the observation console / PC."""

    START = "start"
    PAUSE = "pause"
    ESTOP = "estop"
    RESET = "reset"  # clear estop latch (not on main UI)


class ControlRequest(BaseModel):
    action: ControlAction


class HeartbeatPayload(BaseModel):
    source: str
    ts_ms: int
    seq: int = 0


class SystemStatusResponse(BaseModel):
    """Aggregated web status — SC171V2 link KPIs first."""

    # Hero module identity
    module_id: str = "SC171V2"
    module_name: str = "Fibocom SC171V2"
    carrier: str = "5G/Wi-Fi"
    link: str = "down"  # up | down
    hb_age_ms: float = 0.0

    mode: SystemMode
    # device_online == SC171V2 online
    device_online: bool
    stm32_online: bool
    # Auxiliary packaging input
    pc_online: bool
    last_gesture: str = ""

    target: list[float]
    actual: list[float]
    fault: str
    estop: bool
    latency_ms: float
    control_hz: float
    seq: int
    # Data source tag for UI: live | sim | unknown
    source: str = "live"
