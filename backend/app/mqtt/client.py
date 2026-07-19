"""Async MQTT bridge — cloud mailbox for Fibocom SC171V2."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from app.config import Settings, get_settings
from app.models.schemas import ControlRequest, DeviceStatus, GestureEvent, PcCommand
from app.mqtt import topics
from app.services.arm_state import ArmStateService, arm_state
from app.services.metrics import metrics_store

logger = logging.getLogger(__name__)


class MqttBridge:
    def __init__(
        self,
        state: Optional[ArmStateService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.state = state or arm_state
        self.settings = settings or get_settings()
        self._client: Any = None
        self._task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self.state.set_publisher(self.publish)
        self._task = asyncio.create_task(self._run_loop(), name="mqtt-bridge")
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="mqtt-watchdog")

    async def stop(self) -> None:
        for t in (self._task, self._watchdog_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._connected = False

    def publish(self, topic: str, payload: dict[str, Any], retain: bool = False) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running loop; drop publish to %s", topic)
            return
        loop.create_task(self._publish_async(topic, payload, retain))

    async def _publish_async(self, topic: str, payload: dict[str, Any], retain: bool) -> None:
        if not self._client:
            return
        data = json.dumps(payload, ensure_ascii=False)
        # High-rate telemetry: qos0 reduces ACK latency; commands stay qos1
        qos = 0 if topic in (topics.WEB_STATUS, topics.DEVICE_STATUS) else 1
        try:
            await self._client.publish(topic, data.encode("utf-8"), qos=qos, retain=retain)
            metrics_store.record_mqtt_publish(True)
        except Exception:
            metrics_store.record_mqtt_publish(False)
            logger.exception("MQTT publish failed: %s", topic)

    async def _watchdog_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(1.0)
                await self.state.tick_watchdog()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watchdog tick failed")

    async def _run_loop(self) -> None:
        import aiomqtt

        host = self.settings.mqtt_host
        port = self.settings.mqtt_port
        backoff = 1.0

        while True:
            try:
                kwargs: dict[str, Any] = {
                    "hostname": host,
                    "port": port,
                    "identifier": self.settings.mqtt_client_id,
                    "keepalive": self.settings.mqtt_keepalive,
                }
                if self.settings.mqtt_username:
                    kwargs["username"] = self.settings.mqtt_username
                    kwargs["password"] = self.settings.mqtt_password or None

                async with aiomqtt.Client(**kwargs) as client:
                    self._client = client
                    self._connected = True
                    backoff = 1.0
                    logger.info("MQTT connected to %s:%s (SC171V2 bridge)", host, port)

                    for t in topics.BACKEND_SUBSCRIPTIONS:
                        await client.subscribe(t, qos=1)
                        logger.info("Subscribed: %s", t)

                    async for message in client.messages:
                        await self._on_message(str(message.topic), message.payload)

            except asyncio.CancelledError:
                self._connected = False
                self._client = None
                raise
            except Exception as exc:
                self._connected = False
                self._client = None
                logger.warning("MQTT disconnected (%s); retry in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    async def _on_message(self, topic: str, payload: bytes) -> None:
        try:
            text = payload.decode("utf-8")
            data = json.loads(text) if text else {}
        except Exception:
            logger.warning("Bad MQTT payload on %s", topic)
            return

        try:
            if topic == topics.PC_CMD:
                cmd = PcCommand.model_validate(data)
                await self.state.handle_pc_cmd(cmd)
            elif topic == topics.PC_CONTROL:
                req = ControlRequest.model_validate(data)
                await self.state.handle_control(req.action)
            elif topic == topics.PC_HEARTBEAT:
                await self.state.handle_pc_heartbeat(int(data.get("ts_ms", 0)))
            elif topic == topics.PC_GESTURE:
                # debug bypass
                event = GestureEvent.model_validate(data)
                await self.state.handle_gesture(event)
            elif topic == topics.DEVICE_STATUS:
                status = DeviceStatus.model_validate(data)
                await self.state.handle_device_status(status)
            elif topic == topics.DEVICE_HEARTBEAT:
                await self.state.handle_device_heartbeat(int(data.get("ts_ms", 0)))
        except Exception:
            logger.exception("Failed handling MQTT topic %s", topic)


mqtt_bridge = MqttBridge()
