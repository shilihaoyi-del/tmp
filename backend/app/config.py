"""Application configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Fibocom SC171V2 Remote Arm Bridge"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # Hero module identity (shown on web / MQTT status)
    module_id: str = "SC171V2"
    module_name: str = "Fibocom SC171V2"
    default_carrier: str = "5G/Wi-Fi"

    # MQTT Broker
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_client_id: str = "arm-backend"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_keepalive: int = 30

    # Safety / timing
    heartbeat_timeout_sec: float = 3.0
    command_ttl_ms: int = 500
    control_hz_target: int = 25

    # Joint soft limits (degrees): base, shoulder, elbow, wrist_pitch, wrist_roll, gripper
    joint_min: list[float] = Field(default_factory=lambda: [-180.0, -90.0, -135.0, -90.0, -180.0, 0.0])
    joint_max: list[float] = Field(default_factory=lambda: [180.0, 90.0, 135.0, 90.0, 180.0, 90.0])

    # Gesture -> joint step sizes (degrees per event)
    step_base: float = 8.0
    step_shoulder: float = 6.0
    step_elbow: float = 6.0
    step_wrist_pitch: float = 5.0
    step_wrist_roll: float = 8.0
    gripper_open: float = 0.0
    gripper_close: float = 90.0

    # In-process mock for PC + SC171V2 when hardware is unavailable
    enable_simulator: bool = True
    sim_source_label: str = "SIM"


@lru_cache
def get_settings() -> Settings:
    return Settings()
