# SC171V2 ↔ JetArm 桥接包

广和通 **SC171V2** 桌面目录：`~/Desktop/sc171v2_jetarm`

MQTT ↔ USB（JetArm Type-C）↔ 商家固件 ↔ 总线舵机。  
含：JetArm AA55、FK/IK、软限位、CH340 用户态串口。

## 文件说明

| 文件 | 作用 |
|------|------|
| `sc171v2_servo_bridge.py` | 主程序（MQTT + UART + FK/IK） |
| `jetarm_packet.py` | 商家 AA55 组帧/解析 |
| `arm_kinematics.py` | 正/逆运动学 |
| `joint_protection.py` | 软限位 + 脉冲映射 |
| `hiwonder_servo.py` | 度↔脉冲 |
| `ch340_pyusb.py` | CH340（1a86:7523）用户态串口 |
| `uart_protocol.py` | 旧 20 字节协议（兼容） |
| `probe_read_positions.py` | 读 ID1–6 位置 |
| `start_servo_bridge.sh` | 启动桥接 |
| `test_jetarm_modules.py` | 无硬件自测 |
| `PIPELINE.md` | 数据流说明 |

## 硬件

1. JetArm **Type-C** → SC171 USB  
2. 拓展板 / VIN 给舵机供电  
3. 波特率 **1000000**

## 快速使用

```bash
cd ~/Desktop/sc171v2_jetarm

# 读位置（需 sudo）
sudo ~/sc171v2_agent/.venv/bin/python probe_read_positions.py --baud 1000000

# 启动 MQTT 桥（会同步用 ~/sc171v2_agent 亦可）
# 推荐：文件已同步到 ~/sc171v2_agent 时
bash ~/sc171v2_agent/start_servo_bridge.sh
tail -f /tmp/sc171v2_servo_bridge.log
```

本目录也可直接跑：

```bash
cd ~/Desktop/sc171v2_jetarm
sudo ~/sc171v2_agent/.venv/bin/python sc171v2_servo_bridge.py \
  --host 121.41.67.80 --port 1883 --uart pyusb --drive jetarm --carrier Wi-Fi
```

## Web / 云端

- 观摩页：http://121.41.67.80:8000/  
- MQTT：`121.41.67.80:1883`  
- 上报：`arm/device/status`、`arm/device/heartbeat`  
- 订阅：`arm/device/cmd`

网页应显示 SC171V2 在线，并有 `actual` / `pose`。

## 软限位（`joint_protection.py`）

base ±120.2°，shoulder -180.2~0.2°，elbow ±120.2°，  
wrist_pitch -200.2~20.2°，wrist_roll ±120.2°，gripper 0~90°。

## 已知

- ID6 可能离线；1–5 正常  
- AidLux 上常无 `/dev/ttyUSB0`，用 `ch340_pyusb`  
