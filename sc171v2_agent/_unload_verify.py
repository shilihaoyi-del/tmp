#!/usr/bin/env python3
"""Confirm bridge received unload (H2-PACK unload_all)."""
from __future__ import annotations

import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "192.168.42.4",
    username="aidlux",
    password="aidlux",
    timeout=12,
    allow_agent=False,
    look_for_keys=False,
)
_, o, e = c.exec_command(
    "grep -E 'unload|H2-PACK|H0-FOLLOW|hold|idle' /tmp/sc171v2_servo_bridge.log | tail -30; "
    "echo ---; pgrep -af sc171v2_servo_bridge.py || echo NO_BRIDGE",
    timeout=20,
)
print((o.read() + e.read()).decode("utf-8", "replace"))
c.close()
