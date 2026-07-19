#!/usr/bin/env python3
"""Local unit checks for jetarm_packet + arm_kinematics (no hardware)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jetarm_packet import self_test as packet_test
from arm_kinematics import self_test as kin_test
from joint_protection import (
    JMAX,
    JMIN,
    PULSE_SOFT_MAX,
    PULSE_SOFT_MIN,
    ServoSafetyGate,
    clamp_joints_deg,
    deg_to_pos,
    load_home_joints,
    pos_to_deg,
    slew_limit_joints,
    verify_servo_command,
)


def protection_test() -> None:
    c = clamp_joints_deg([999, -999, 0, 0, 0, 200])
    assert c[0] == JMAX[0] and c[1] == JMIN[1] and c[5] == JMAX[5]
    assert abs(pos_to_deg(500, 0) - 0.0) < 1e-6
    assert abs(pos_to_deg(500, 1) - (-90.0)) < 1e-6
    assert deg_to_pos(0.0, 0) == 500
    assert deg_to_pos(-90.0, 1) == 500
    # Soft limit then map: shoulder cannot go above soft max
    assert deg_to_pos(90.0, 1) == deg_to_pos(JMAX[1], 1)
    # Pulse soft band
    assert PULSE_SOFT_MIN <= deg_to_pos(JMIN[0], 0) <= PULSE_SOFT_MAX
    assert PULSE_SOFT_MIN <= deg_to_pos(JMAX[0], 0) <= PULSE_SOFT_MAX

    seed = [0.0, -90.0, 0.0, -90.0, 0.0, 45.0]
    huge = [70.0, -25.0, 70.0, -35.0, 70.0, 75.0]
    stepped, limited = slew_limit_joints(huge, seed, 1000)
    assert limited
    assert abs(stepped[0] - seed[0]) <= 32.0 + 1e-6

    allow, safe, pulses, why = verify_servo_command(
        seed, last_joints=seed, last_write_ts=0.0, now_ts=10.0, move_time_ms=1000
    )
    assert not allow and why.startswith("skip:")

    allow2, safe2, pulses2, why2 = verify_servo_command(
        huge,
        last_joints=seed,
        last_write_ts=0.0,
        now_ts=10.0,
        move_time_ms=1000,
    )
    assert allow2 and why2.startswith("ok")
    assert PULSE_SOFT_MIN <= min(pulses2) and max(pulses2) <= PULSE_SOFT_MAX

    gate = ServoSafetyGate(move_time_ms=1000)
    gate.reset(seed)
    a1, _, _, r1 = gate.verify(huge, now_ts=100.0)
    assert a1 and r1.startswith("ok")
    # write pacing ~0.45 * move_time → reject immediate rewrite
    a2, _, _, r2 = gate.verify(huge, now_ts=100.1)
    assert not a2 and "min_interval" in r2

    home = load_home_joints()
    assert len(home) == 6
    assert all(JMIN[i] - 1e-6 <= home[i] <= JMAX[i] + 1e-6 for i in range(6))

    print("joint_protection self_test OK limits=%s..%s" % (JMIN, JMAX))


def main() -> int:
    packet_test()
    kin_test()
    protection_test()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
