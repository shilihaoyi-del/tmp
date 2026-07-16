"""MQTT topic definitions — Fibocom SC171V2 is the control-plane hero."""

# PC (auxiliary input packaging) -> broker
PC_CMD = "arm/pc/cmd"              # primary: six-joint targets from PC
PC_CONTROL = "arm/pc/control"      # start | pause | estop
PC_HEARTBEAT = "arm/pc/heartbeat"
PC_GESTURE = "arm/pc/gesture"      # debug only: server-side mapping bypass

# Broker / backend -> Fibocom SC171V2 (hero)
DEVICE_CMD = "arm/device/cmd"
DEVICE_MODE = "arm/device/mode"

# SC171V2 -> broker
DEVICE_STATUS = "arm/device/status"
DEVICE_HEARTBEAT = "arm/device/heartbeat"

# Broker -> web observation console
WEB_STATUS = "arm/web/status"
WEB_EVENT = "arm/web/event"

BACKEND_SUBSCRIPTIONS = [
    PC_CMD,
    PC_CONTROL,
    PC_HEARTBEAT,
    PC_GESTURE,
    DEVICE_STATUS,
    DEVICE_HEARTBEAT,
]
