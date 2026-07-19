# 真机闭环：SC171V2 → JetArm USART1 → 舵机 → FK 姿态 → 云端

## 目标数据流

```
云 MQTT arm/device/cmd  (target / pose / pose_delta)
    → SC171V2 IK（若有 pose*）
    → JetArm AA55 BUS_SERVO @ 1 Mbps（USB Type-C = STM32 USART1）
    → 商家固件驱幻尔总线舵机
    → 读位置回包
    → SC171V2 FK → pose
    → MQTT arm/device/status（actual + pose + servo_online）
```

## 分工

| 设备 | 职责 |
|------|------|
| **云服务器** | 转发 cmd、汇总 status |
| **SC171V2** | JetArm 协议解析、FK/IK、MQTT 桥 |
| **STM32（商家 JetArm 固件）** | USART1 packet → 总线舵机 |
| **幻尔舵机** | ID 1–6 |

## 线协议（商家）

- 波特率 **1000000** 8N1
- 帧：`AA 55 | func | len | data | CRC8`
- 总线舵机 `func=0x05`：写位置 `0x01`、读位置 `0x05`、LOAD `0x0C`

## SC171V2 关键文件

- `jetarm_packet.py` — 解析/组帧
- `arm_kinematics.py` — FK / 数值 IK
- `sc171v2_servo_bridge.py` — MQTT ↔ UART
- `hiwonder_servo.py` — 度 ↔ 0..1000 脉冲

## 启动

```bash
# 默认 --drive jetarm @ 1Mbps
bash ~/sc171v2_agent/start_servo_bridge.sh
tail -f /tmp/sc171v2_servo_bridge.log
```

成功标志：

```
[H0-OPEN] CDC line_coding=1000000
[H0-READY] drive=jetarm
[H4-RX] protocol=jetarm success=0   # 读位置成功
[H5-UP] pose={...} actual=[...]
```

调试旧 20 字节协议：`DRIVE=aa55 bash start_servo_bridge.sh`

## 关节软保护（实测收紧）

见 `joint_protection.py`：脉冲↔角度仍用 JetArm `angle_transform`；**软限位偏保守（危险/易烧）**，命令脉冲限制在 **100～900**。

| 关节 | 软限位 (deg) | 备注 |
|------|----------------|------|
| base | -70 ~ 70 | 远离实测止点约 +107° |
| shoulder | -140 ~ -25 | 机械上端约 +18°@50 |
| elbow | -70 ~ 70 | 机械约 ±120° |
| wrist_pitch | -170 ~ -35 | 实测约 -210～-50 |
| wrist_roll | -70 ~ 70 | 机械约 ±120° |
| gripper | 15 ~ 75 | 避开开合两端 |

位姿控制走 `solve_reachable()`：URDF 工作空间门控 + IK + FK 回验，失败则**保持上一目标不驱动**。

UART 写前：`H1-JAC` 雅可比平滑（Δq→JΔq→限 TCP→DLS 回关节 + EMA/抗反转）再过 `H1-SAFE`（软限位、写间隔≈0.45×move_time、相同目标跳过）。`move_time_ms=1000` 速度不变；`hold`/`estop` 时 `UNLOAD`。

激活复位：`home_pose.json` 为开机 home；`H0-HOME` **关闭雅可比**，斜坡接近后 `home_exact` 精确到位；之后正常运动才开雅可比消抖。

## 注意

- Type-C 连的是 **USART1**，不是舵机总线口。
- 舵机需 VIN（拓展板供电）。
- ID6 离线时桥接会跳过夹爪写位置，其余轴仍可控。
