"""Pydantic request / response schemas."""

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


class GestureName(str, Enum):
    GRAB = "Grab"
    TAP = "Tap"
    EXPAND = "Expand"
    PINCH = "Pinch"
    ROTATION_CW = "Rotation CW"
    ROTATION_CCW = "Rotation CCW"
    SWIPE_RIGHT = "Swipe Right"
    SWIPE_LEFT = "Swipe Left"
    SWIPE_UP = "Swipe Up"
    SWIPE_DOWN = "Swipe Down"
    SWIPE_V = "Swipe V"
    SWIPE_CROSS = "Swipe Cross"
    SHAKE = "Shake"
    OTHER = "Other"


class HandSide(str, Enum):
    LEFT = "Left"
    RIGHT = "Right"
    BOTH = "Both"


# ---------------------------------------------------------------------------
# MQTT / REST payloads
# ---------------------------------------------------------------------------

class GestureEvent(BaseModel):
    """Gesture recognition result from PC vision pipeline."""

    seq: int = Field(..., description="Monotonic sequence number")
    ts_ms: int = Field(..., description="Client timestamp in milliseconds")
    gesture: str
    hand: HandSide = HandSide.RIGHT
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    # Optional: simultaneous left/right gesture for dual-hand mapping
    left_gesture: Optional[str] = None
    right_gesture: Optional[str] = None
    left_confidence: float = 0.0
    right_confidence: float = 0.0


class JointAngles(BaseModel):
    """Six joint angles in degrees: base, shoulder, elbow, wrist_pitch, wrist_roll, gripper."""

    joints: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="[base, shoulder, elbow, wrist_pitch, wrist_roll, gripper]",
    )


class DeviceCommand(BaseModel):
    """Command forwarded to SC171V2."""

    seq: int
    ts_ms: int
    ttl_ms: int = 500
    mode: SystemMode
    target: list[float] = Field(..., min_length=6, max_length=6)
    estop: bool = False


class DeviceStatus(BaseModel):
    """Status uploaded by SC171V2."""

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


class ControlAction(str, Enum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    ESTOP = "estop"
    RESET = "reset"
    HOLD = "hold"


class ControlRequest(BaseModel):
    action: ControlAction


class HeartbeatPayload(BaseModel):
    source: str
    ts_ms: int
    seq: int = 0


class SystemStatusResponse(BaseModel):
    mode: SystemMode
    pc_online: bool
    device_online: bool
    stm32_online: bool
    target: list[float]
    actual: list[float]
    fault: str
    estop: bool
    latency_ms: float
    control_hz: float
    last_gesture: str
    seq: int
