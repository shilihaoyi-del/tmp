"""HTTP API — cloud bridge for Fibocom SC171V2 observation console."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import (
    ControlAction,
    ControlRequest,
    GestureEvent,
    PcCommand,
    SystemStatusResponse,
)
from app.mqtt.client import mqtt_bridge
from app.services.arm_state import arm_state

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "module_id": arm_state.settings.module_id,
        "mqtt_connected": mqtt_bridge.connected,
        "mode": arm_state.mode.value,
        "sc171v2_online": arm_state.device_online,
    }


@router.get("/status", response_model=SystemStatusResponse)
async def get_status() -> SystemStatusResponse:
    """Fallback status for tooling; web console should prefer MQTT arm/web/status."""
    return arm_state.snapshot()


@router.post("/control", response_model=SystemStatusResponse)
async def post_control(req: ControlRequest) -> SystemStatusResponse:
    """Operator gate for SC171V2 run state: start | pause | estop | reset."""
    return await arm_state.handle_control(req.action)


@router.post("/control/{action}", response_model=SystemStatusResponse)
async def post_control_action(action: ControlAction) -> SystemStatusResponse:
    return await arm_state.handle_control(action)


@router.post("/cmd", response_model=SystemStatusResponse)
async def post_cmd(cmd: PcCommand) -> SystemStatusResponse:
    """Primary joint-command path (same as MQTT arm/pc/cmd)."""
    return await arm_state.handle_pc_cmd(cmd)


@router.post("/pc/heartbeat")
async def post_pc_heartbeat() -> dict:
    """Keep PC vision session alive during gesture gaps / skipped classes."""
    await arm_state.handle_pc_heartbeat()
    snap = arm_state.snapshot()
    return {"ok": True, "mode": snap.mode.value, "pc_online": snap.pc_online}


@router.post("/gesture", response_model=SystemStatusResponse)
async def post_gesture(event: GestureEvent) -> SystemStatusResponse:
    """DEBUG ONLY — server-side gesture mapping. Production PC must publish /cmd."""
    return await arm_state.handle_gesture(event)


@router.get("/topics")
async def list_topics() -> dict:
    from app.mqtt import topics

    return {
        "hero": "Fibocom SC171V2",
        "pc_cmd": topics.PC_CMD,
        "pc_control": topics.PC_CONTROL,
        "pc_heartbeat": topics.PC_HEARTBEAT,
        "pc_gesture_debug": topics.PC_GESTURE,
        "device_cmd": topics.DEVICE_CMD,
        "device_mode": topics.DEVICE_MODE,
        "device_status": topics.DEVICE_STATUS,
        "device_heartbeat": topics.DEVICE_HEARTBEAT,
        "web_status": topics.WEB_STATUS,
        "web_event": topics.WEB_EVENT,
    }
