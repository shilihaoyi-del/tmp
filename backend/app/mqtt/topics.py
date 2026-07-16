"""MQTT topic definitions for the arm control system."""

# PC (vision / gesture) -> broker
PC_GESTURE = "arm/pc/gesture"
PC_CONTROL = "arm/pc/control"
PC_HEARTBEAT = "arm/pc/heartbeat"

# Broker / backend -> SC171V2
DEVICE_CMD = "arm/device/cmd"
DEVICE_MODE = "arm/device/mode"

# SC171V2 -> broker
DEVICE_STATUS = "arm/device/status"
DEVICE_HEARTBEAT = "arm/device/heartbeat"

# Broker -> web / dashboard clients
WEB_STATUS = "arm/web/status"
WEB_EVENT = "arm/web/event"

# Backend internal subscriptions
BACKEND_SUBSCRIPTIONS = [
    PC_GESTURE,
    PC_CONTROL,
    PC_HEARTBEAT,
    DEVICE_STATUS,
    DEVICE_HEARTBEAT,
]
