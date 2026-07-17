"""
PC-side bridge: gesture -> 6 joint targets -> local FastAPI / MQTT.

Self-contained (no backend package import) so vision venv can use it alone.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# Optional MQTT
try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None  # type: ignore


HANDLED = {
    "Swipe Right",
    "Swipe Left",
    "Swipe Up",
    "Swipe Down",
    "Swipe V",
    "Pinch",
    "Grab",
    "Expand",
}

CONF_THRESHOLD = 0.22

# Step sizes (degrees) — match backend defaults
STEP_BASE = 8.0
STEP_SHOULDER = 6.0
STEP_ELBOW = 6.0
STEP_WRIST_PITCH = 5.0
STEP_WRIST_ROLL = 8.0
GRIPPER_OPEN = 0.0
GRIPPER_CLOSE = 90.0

JOINT_MIN = [-180.0, -90.0, -135.0, -90.0, -180.0, 0.0]
JOINT_MAX = [180.0, 90.0, 135.0, 90.0, 180.0, 90.0]


def clamp_joints(joints: list[float]) -> list[float]:
    return [max(JOINT_MIN[i], min(JOINT_MAX[i], float(joints[i]))) for i in range(6)]


@dataclass
class MapResult:
    joints: list[float]
    applied: bool
    reason: str


def map_gestures(
    *,
    left_g: Optional[str],
    right_g: Optional[str],
    left_c: float,
    right_c: float,
    current: list[float],
) -> MapResult:
    joints = list(current) if len(current) == 6 else [0.0] * 6

    # Both hands vertical swipe -> wrist pitch
    if (
        left_g in ("Swipe Up", "Swipe Down")
        and right_g in ("Swipe Up", "Swipe Down")
        and left_c >= CONF_THRESHOLD
        and right_c >= CONF_THRESHOLD
    ):
        delta = STEP_WRIST_PITCH if right_g == "Swipe Up" else -STEP_WRIST_PITCH
        joints[3] += delta
        return MapResult(clamp_joints(joints), True, "wrist_pitch:both")

    applied = False
    reasons: list[str] = []

    if right_g and right_c >= CONF_THRESHOLD and right_g in HANDLED:
        r = _apply_single(right_g, "Right", joints)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)

    if left_g and left_c >= CONF_THRESHOLD and left_g in HANDLED:
        r = _apply_single(left_g, "Left", joints)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)

    return MapResult(
        clamp_joints(joints),
        applied,
        ",".join(reasons) if reasons else "no_action",
    )


def _apply_single(gesture: str, hand: str, joints: list[float]) -> MapResult:
    if gesture in ("Pinch", "Grab"):
        joints[5] = GRIPPER_CLOSE
        return MapResult(joints, True, "gripper:close")
    if gesture == "Expand":
        joints[5] = GRIPPER_OPEN
        return MapResult(joints, True, "gripper:open")
    if gesture == "Swipe Right":
        joints[0] += STEP_BASE
        return MapResult(joints, True, "base:+")
    if gesture == "Swipe Left":
        joints[0] -= STEP_BASE
        return MapResult(joints, True, "base:-")
    if gesture == "Swipe V":
        if hand == "Left":
            joints[4] += STEP_WRIST_ROLL
            return MapResult(joints, True, "wrist_roll:+")
        return MapResult(joints, False, "swipe_v:right_ignored")
    if gesture == "Swipe Up":
        if hand == "Right":
            joints[1] += STEP_SHOULDER
            return MapResult(joints, True, "shoulder:+")
        if hand == "Left":
            joints[2] += STEP_ELBOW
            return MapResult(joints, True, "elbow:+")
    if gesture == "Swipe Down":
        if hand == "Right":
            joints[1] -= STEP_SHOULDER
            return MapResult(joints, True, "shoulder:-")
        if hand == "Left":
            joints[2] -= STEP_ELBOW
            return MapResult(joints, True, "elbow:-")
    return MapResult(joints, False, f"unmapped:{gesture}/{hand}")


class ArmBridge:
    """Publish joint targets to local FastAPI and/or MQTT broker."""

    def __init__(
        self,
        api_base: Optional[str] = None,
        mqtt_host: Optional[str] = None,
        mqtt_port: Optional[int] = None,
        use_http: Optional[bool] = None,
        use_mqtt: Optional[bool] = None,
        apply_cooldown_ms: int = 280,
    ) -> None:
        self.api_base = (api_base or os.getenv("ARM_API_BASE", "http://127.0.0.1:8000")).rstrip("/")
        self.mqtt_host = mqtt_host or os.getenv("ARM_MQTT_HOST", "127.0.0.1")
        self.mqtt_port = int(mqtt_port or os.getenv("ARM_MQTT_PORT", "1883"))
        self.use_http = (
            use_http
            if use_http is not None
            else os.getenv("ARM_USE_HTTP", "1") not in ("0", "false", "False")
        )
        self.use_mqtt = (
            use_mqtt
            if use_mqtt is not None
            else os.getenv("ARM_USE_MQTT", "0") not in ("0", "false", "False")
        )
        self.apply_cooldown_ms = apply_cooldown_ms

        self.target = [0.0] * 6
        self.seq = 0
        self.last_reason = ""
        self.last_apply_ms = 0
        self.last_signature = ""
        self.http_ok = False
        self.mqtt_ok = False
        self._mqtt: Optional[object] = None

        if self.use_mqtt:
            self._init_mqtt()

    def _init_mqtt(self) -> None:
        if mqtt is None:
            print("[bridge] paho-mqtt not installed; MQTT disabled (pip install paho-mqtt)")
            self.use_mqtt = False
            return
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pc-vision")
        except Exception:
            client = mqtt.Client(client_id="pc-vision")
        try:
            client.connect(self.mqtt_host, self.mqtt_port, keepalive=30)
            client.loop_start()
            self._mqtt = client
            self.mqtt_ok = True
            print(f"[bridge] MQTT connected {self.mqtt_host}:{self.mqtt_port}")
        except Exception as exc:
            print(f"[bridge] MQTT connect failed: {exc} (HTTP-only mode)")
            self.use_mqtt = False
            self.mqtt_ok = False

    def _http_json(self, method: str, path: str, body: Optional[dict] = None) -> bool:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                self.http_ok = 200 <= resp.status < 300
                return self.http_ok
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.http_ok = False
            if self.seq % 40 == 1:
                print(f"[bridge] HTTP {path} failed: {exc}")
            return False

    def start_session(self) -> None:
        """Clear estop if needed and enter running mode."""
        self._http_json("POST", "/api/control", {"action": "reset"})
        ok = self._http_json("POST", "/api/control", {"action": "start"})
        if self.use_mqtt and self._mqtt:
            try:
                self._mqtt.publish("arm/pc/control", json.dumps({"action": "start"}), qos=1)
            except Exception:
                pass
        print(f"[bridge] session start via HTTP={'ok' if ok else 'fail'} api={self.api_base}")
        print("[bridge] tip: set ENABLE_SIMULATOR=false on backend when using real camera")

    def close(self) -> None:
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def heartbeat(self) -> None:
        ts = self._now_ms()
        if self.use_http:
            self._http_json("POST", "/api/pc/heartbeat", {"ts_ms": ts, "source": "pc-vision"})
        if self.use_mqtt and self._mqtt:
            try:
                self._mqtt.publish(
                    "arm/pc/heartbeat",
                    json.dumps({"source": "pc-vision", "ts_ms": ts, "seq": self.seq}),
                    qos=0,
                )
            except Exception:
                self.mqtt_ok = False

    def on_gestures(
        self,
        left_g: Optional[str],
        right_g: Optional[str],
        left_c: float,
        right_c: float,
        *,
        verbose: bool = True,
    ) -> Optional[MapResult]:
        """Map gestures and publish when cooldown allows and mapping applied."""
        # Normalize collecting / empty
        lg = left_g if left_g and left_g != "Collecting..." else None
        rg = right_g if right_g and right_g != "Collecting..." else None
        if not lg and not rg:
            return None

        now = self._now_ms()
        if (now - self.last_apply_ms) < self.apply_cooldown_ms:
            return None

        result = map_gestures(
            left_g=lg,
            right_g=rg,
            left_c=left_c,
            right_c=right_c,
            current=self.target,
        )
        if not result.applied:
            if verbose:
                print(
                    f"[skip] L={lg}({left_c:.0%}) R={rg}({right_c:.0%}) "
                    f"-> {result.reason}  (need Swipe/Pinch/Expand, conf>={CONF_THRESHOLD:.0%})"
                )
            self.last_apply_ms = now  # avoid spam every frame
            return result

        self.target = result.joints
        self.last_reason = result.reason
        self.last_apply_ms = now
        self.last_signature = f"{lg}|{rg}|{result.reason}"
        self.seq += 1
        ok = self._publish_cmd()
        if verbose:
            print(
                f"[publish #{self.seq}] {result.reason} "
                f"L={lg}({left_c:.0%}) R={rg}({right_c:.0%}) "
                f"target={[round(v, 1) for v in self.target]} http={'ok' if ok else 'FAIL'}"
            )
        return result

    def _publish_cmd(self) -> bool:
        payload = {
            "seq": self.seq,
            "ts_ms": self._now_ms(),
            "ttl_ms": 800,
            "target": [round(v, 2) for v in self.target],
            "estop": False,
        }
        ok = True
        if self.use_http:
            ok = self._http_json("POST", "/api/cmd", payload) and ok
        if self.use_mqtt and self._mqtt:
            try:
                self._mqtt.publish("arm/pc/cmd", json.dumps(payload), qos=1)
                self.mqtt_ok = True
            except Exception:
                self.mqtt_ok = False
                ok = False
        return ok
