# SC171V2 ↔ STM32 串口协议（UART / CDC）

波特率：`115200 8N1`  
字节序：小端  
关节顺序：`[base, shoulder, elbow, wrist_pitch, wrist_roll, gripper]`  
角度单位：`0.01°`（int16，`1234` = `12.34°`）

---

## 1. 统一帧格式（定长 20 字节，下行/回包相同）

| 偏移 | 长度 | 字段 | 说明 |
|------|------|------|------|
| 0 | 1 | `HEAD0` | `0xAA` |
| 1 | 1 | `HEAD1` | `0x55` |
| 2 | 1 | `VER` | `0x01` |
| 3 | 1 | `CMD` | 见下表 |
| 4 | 1 | `SEQ` | 序号；**回包建议回显下行 SEQ** |
| 5 | 1 | `FLAGS` | 状态位，见第 3 节 |
| 6–17 | 12 | `JOINT[6]` | 6×int16，单位 0.01° |
| 18–19 | 2 | `CRC16` | Modbus CRC16，覆盖 `[0..17]` |

---

## 2. 命令字

### 下行（SC171V2 → STM32）

| CMD | 名称 | 说明 |
|-----|------|------|
| `0x01` | `JOINT_CMD` | 六关节目标角 |
| `0x02` | `HEARTBEAT` | 心跳 |
| `0x03` | `ESTOP` | 急停 |
| `0x04` | `HOLD` | 保持 |

### 回包（STM32 → SC171V2）★

| CMD | 名称 | 说明 |
|-----|------|------|
| `0x81` | `STATUS` | **主回包**：实际关节角 + 状态 FLAGS |
| `0x82` | `ACK` | 简单应答（可无关节，填 0） |
| `0x83` | `FAULT` | 故障上报（FLAGS.bit3=1，JOINT 可填最后实际角） |

SC171V2 当前已识别 **`0x81 STATUS`**，收到后会：
1. 解析 6 关节到 `actual`
2. 标记 `stm32_online=true`
3. 上报云端 `arm/device/status` / `arm/device/trace`（H4-RX / H5-UP）

---

## 3. FLAGS（回包重点）

| bit | 宏 | 含义 |
|-----|-----|------|
| 0 | `ESTOP` | 急停中 |
| 1 | `HOLD` | 保持中 |
| 2 | `MOVING` | 舵机运动中 |
| 3 | `FAULT` | 故障 |
| 4 | `ONLINE` | STM32 在线/就绪（回包建议置 1） |
| 5–7 | — | 保留，发 0 |

推荐 STATUS 回包：`FLAGS = ONLINE | (运动中? MOVING:0) | (急停? ESTOP:0)`

---

## 4. 回包示例 STATUS `0x81`

假设下行 JOINT `SEQ=0x12`，目标/实际均为 `[12, 18, -12, 2, 6, 35]` 度，`FLAGS=ONLINE(0x10)`：

centi-deg：`[1200, 1800, -1200, 200, 600, 3500]`

```
AA 55 01 81 12 10
B0 04  08 07  50 FB  C8 00  58 02  AC 0D
CRC_L CRC_H
```

规则：
1. `CMD = 0x81`
2. `SEQ` = 刚收到的下行 `SEQ`（方便算 RTT）
3. `JOINT[]` = **实际角**（暂无反馈时可先回传目标角）
4. 算 CRC 后通过 USART 发出 20 字节

---

## 5. STM32 推荐处理流程

```
收满一帧并 CRC 通过
  ├─ ESTOP / FLAGS.estop → 停舵机，回 STATUS(ESTOP|ONLINE)
  ├─ JOINT_CMD / HEARTBEAT → 写舵机 → 读实际角(或镜像目标) → 回 STATUS
  ├─ HOLD → 保持 → 回 STATUS(HOLD|ONLINE)
  └─ 其它 → 可回 ACK(0x82)
```

建议：每次有效下行后 **立即回 1 帧 STATUS**；另可 50–100ms 周期上报。

---

## 6. 代码文件

| 文件 | 用途 |
|------|------|
| `uart_protocol.py` | SC171 组包/解包 |
| `stm32/arm_uart_protocol.h/.c` | 收发包基础库 |
| `stm32/arm_uart_reply.h/.c` | **回包专用 API** |
| `stm32/stm32_reply_example.c` | 可直接参考的回包示例 |

SC171 侧看回包：
```bash
tail -f /tmp/sc171v2_servo_bridge.log
# 期望: [H4-RX] ok=true cmd=129 ...  [H5-UP] actual=[...]
```
