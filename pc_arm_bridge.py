"""
PC-side bridge: gesture -> pose_delta (+ gripper) -> local FastAPI / MQTT.

Self-contained (no backend package import) so vision venv can use it alone.
SC171 runs IK on pose_delta.
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

STEP_XY = 0.02
STEP_Z = 0.02
STEP_PITCH = 0.08
STEP_ROLL = 0.10
GRIPPER_OPEN = 0.0
GRIPPER_CLOSE = 90.0

# Soft limits — JetArm jetarm_6dof_params.py (tune later on bench)
JOINT_MIN = [-120.2, -180.2, -120.2, -200.2, -120.2, 0.0]
JOINT_MAX = [120.2, 0.2, 120.2, 20.2, 120.2, 90.0]


def clamp_joints(joints: list[float]) -> list[float]:
    return [max(JOINT_MIN[i], min(JOINT_MAX[i], float(joints[i]))) for i in range(6)]


def _empty_delta() -> dict:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}


@dataclass
class MapResult:
    joints: list[float]
    applied: bool
    reason: str
    pose_delta: Optional[dict] = None
    gripper: Optional[float] = None


def map_gestures(
    *,
    left_g: Optional[str],
    right_g: Optional[str],
    left_c: float,
    right_c: float,
    current: list[float],
) -> MapResult:
    joints = list(current) if len(current) == 6 else [0.0] * 6

    if (
        left_g in ("Swipe Up", "Swipe Down")
        and right_g in ("Swipe Up", "Swipe Down")
        and left_c >= CONF_THRESHOLD
        and right_c >= CONF_THRESHOLD
    ):
        d = _empty_delta()
        d["pitch"] = STEP_PITCH if right_g == "Swipe Up" else -STEP_PITCH
        return MapResult(clamp_joints(joints), True, "pitch:both", pose_delta=d)

    applied = False
    reasons: list[str] = []
    merged = _empty_delta()
    gripper: Optional[float] = None

    if right_g and right_c >= CONF_THRESHOLD and right_g in HANDLED:
        r = _apply_single(right_g, "Right", joints)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)
            if r.pose_delta:
                for k in merged:
                    merged[k] += float(r.pose_delta.get(k, 0.0))
            if r.gripper is not None:
                gripper = r.gripper

    if left_g and left_c >= CONF_THRESHOLD and left_g in HANDLED:
        r = _apply_single(left_g, "Left", joints)
        joints = r.joints
        if r.applied:
            applied = True
            reasons.append(r.reason)
            if r.pose_delta:
                for k in merged:
                    merged[k] += float(r.pose_delta.get(k, 0.0))
            if r.gripper is not None:
                gripper = r.gripper

    pose_delta = merged if any(abs(v) > 1e-12 for v in merged.values()) else None
    return MapResult(
        clamp_joints(joints),
        applied,
        ",".join(reasons) if reasons else "no_action",
        pose_delta=pose_delta,
        gripper=gripper,
    )


def _apply_single(gesture: str, hand: str, joints: list[float]) -> MapResult:
    if gesture in ("Pinch", "Grab"):
        joints[5] = GRIPPER_CLOSE
        return MapResult(joints, True, "gripper:close", gripper=GRIPPER_CLOSE)
    if gesture == "Expand":
        joints[5] = GRIPPER_OPEN
        return MapResult(joints, True, "gripper:open", gripper=GRIPPER_OPEN)
    d = _empty_delta()
    if gesture == "Swipe Right":
        d["y"] = STEP_XY
        return MapResult(joints, True, "pose:y+", pose_delta=d)
    if gesture == "Swipe Left":
        d["y"] = -STEP_XY
        return MapResult(joints, True, "pose:y-", pose_delta=d)
    if gesture == "Swipe V":
        if hand == "Left":
            d["roll"] = STEP_ROLL
            return MapResult(joints, True, "pose:roll+", pose_delta=d)
        return MapResult(joints, False, "swipe_v:right_ignored")
    if gesture == "Swipe Up":
        if hand == "Right":
            d["z"] = STEP_Z
            return MapResult(joints, True, "pose:z+", pose_delta=d)
        if hand == "Left":
            d["x"] = STEP_XY
            return MapResult(joints, True, "pose:x+", pose_delta=d)
    if gesture == "Swipe Down":
        if hand == "Right":
            d["z"] = -STEP_Z
            return MapResult(joints, True, "pose:z-", pose_delta=d)
        if hand == "Left":
            d["x"] = -STEP_XY
            return MapResult(joints, True, "pose:x-", pose_delta=d)
    return MapResult(joints, False, f"unmapped:{gesture}/{hand}")


class ArmBridge:
    """Publish pose_delta / joint targets to local FastAPI and/or MQTT broker."""

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
        self.last_pose_delta: Optional[dict] = None
        self.last_gripper: Optional[float] = None
        self.http_ok = False
        self.mqtt_ok = False
        self._mqtt: Optional[object] = None
        # Motion publish allowed only when cloud mode=running (after START)
        self.drive_enabled = False
        self._drive_check_ms = 0

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

    def _http_get_json(self, path: str) -> Optional[dict]:
        req = urllib.request.Request(f"{self.api_base}{path}", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                self.http_ok = 200 <= resp.status < 300
                if not self.http_ok:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            self.http_ok = False
            return None

    def refresh_drive_gate(self, *, force: bool = False) -> bool:
        """Allow motion publish only when backend mode is running (not estop)."""
        now = self._now_ms()
        if not force and (now - self._drive_check_ms) < 400:
            return self.drive_enabled
        self._drive_check_ms = now
        st = self._http_get_json("/api/status") if self.use_http else None
        if not st:
            self.drive_enabled = False
            return False
        mode = str(st.get("mode", "idle")).lower()
        estop = bool(st.get("estop", False))
        self.drive_enabled = mode == "running" and not estop
        return self.drive_enabled

    def start_session(self) -> None:
        """Clear estop if needed and enter running mode (explicit arm enable)."""
        self._http_json("POST", "/api/control", {"action": "reset"})
        ok = self._http_json("POST", "/api/control", {"action": "start"})
        if self.use_mqtt and self._mqtt:
            try:
                self._mqtt.publish("arm/pc/control", json.dumps({"action": "start"}), qos=1)
            except Exception:
                pass
        self.refresh_drive_gate(force=True)
        print(
            f"[bridge] session START via HTTP={'ok' if ok else 'fail'} "
            f"drive={self.drive_enabled} api={self.api_base}"
        )
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
            self.last_apply_ms = now
            return result

        # Vision-only until START: recognize but do not drive the arm
        if not self.refresh_drive_gate():
            if verbose:
                print(
                    f"[armed-wait] L={lg} R={rg} -> {result.reason} "
                    f"(press 's' or web START to enable arm)"
                )
            self.last_apply_ms = now
            self.last_reason = "armed_wait_start"
            return MapResult(
                list(self.target),
                False,
                "armed_wait_start",
                pose_delta=None,
                gripper=None,
            )

        self.target = result.joints
        self.last_pose_delta = result.pose_delta
        self.last_gripper = result.gripper
        self.last_reason = result.reason
        self.last_apply_ms = now
        self.last_signature = f"{lg}|{rg}|{result.reason}"
        self.seq += 1
        ok = self._publish_cmd()
        if verbose:
            print(
                f"[publish #{self.seq}] {result.reason} "
                f"L={lg}({left_c:.0%}) R={rg}({right_c:.0%}) "
                f"pose_delta={result.pose_delta} gripper={result.gripper} "
                f"http={'ok' if ok else 'FAIL'}"
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
        if self.last_pose_delta:
            payload["pose_delta"] = {
                k: round(float(v), 5) for k, v in self.last_pose_delta.items()
            }
        if self.last_gripper is not None:
            payload["gripper"] = float(self.last_gripper)
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
