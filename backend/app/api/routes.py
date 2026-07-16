"""HTTP API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    ControlAction,
    ControlRequest,
    GestureEvent,
    JointAngles,
    SystemMode,
    SystemStatusResponse,
)
from app.mqtt.client import mqtt_bridge
from app.services.arm_state import arm_state
from app.services.safety import clamp_joints

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "mqtt_connected": mqtt_bridge.connected,
        "mode": arm_state.mode.value,
    }


@router.get("/status", response_model=SystemStatusResponse)
async def get_status() -> SystemStatusResponse:
    return arm_state.snapshot()


@router.post("/control", response_model=SystemStatusResponse)
async def post_control(req: ControlRequest) -> SystemStatusResponse:
    return await arm_state.handle_control(req.action)


@router.post("/gesture", response_model=SystemStatusResponse)
async def post_gesture(event: GestureEvent) -> SystemStatusResponse:
    """HTTP fallback for PC gesture injection (same path as MQTT arm/pc/gesture)."""
    return await arm_state.handle_gesture(event)


@router.post("/joints", response_model=SystemStatusResponse)
async def post_joints(body: JointAngles) -> SystemStatusResponse:
    """Direct joint target set (manual / debug). Only when RUNNING."""
    if arm_state.mode != SystemMode.RUNNING or arm_state.estop:
        raise HTTPException(status_code=409, detail="system not in running mode")
    async with arm_state._lock:
        arm_state.target = clamp_joints(list(body.joints), arm_state.settings)
        arm_state._emit_device_cmd()
        arm_state._emit_web_status()
        return arm_state.snapshot()


@router.get("/topics")
async def list_topics() -> dict:
    from app.mqtt import topics

    return {
        "pc_gesture": topics.PC_GESTURE,
        "pc_control": topics.PC_CONTROL,
        "pc_heartbeat": topics.PC_HEARTBEAT,
        "device_cmd": topics.DEVICE_CMD,
        "device_mode": topics.DEVICE_MODE,
        "device_status": topics.DEVICE_STATUS,
        "device_heartbeat": topics.DEVICE_HEARTBEAT,
        "web_status": topics.WEB_STATUS,
        "web_event": topics.WEB_EVENT,
    }


@router.post("/control/{action}", response_model=SystemStatusResponse)
async def post_control_action(action: ControlAction) -> SystemStatusResponse:
    return await arm_state.handle_control(action)
