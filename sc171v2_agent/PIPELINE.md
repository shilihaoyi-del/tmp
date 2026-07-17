# 真机闭环：SC171V2 → 舵机 → 真实位置 → 云端

## 目标数据流

```
云 MQTT arm/device/cmd
    → SC171V2 组 JOINT 帧 (0x01)
    → USB/UART → STM32
    → 幻尔总线舵机移动
    → STM32 读取真实位置
    → STATUS 帧 (0x81) 回 SC171V2
    → MQTT arm/device/status（actual=真实角）
    → 网页/服务器展示
```

## 分工

| 设备 | 职责 |
|------|------|
| **云服务器** | 已就绪：发 cmd、收 status |
| **SC171V2** | 已就绪：MQTT↔UART 桥，收 STATUS 上报 `actual` |
| **STM32** | **必须烧录本目录固件逻辑**：驱舵机 + 读位置 + 回 STATUS |
| **幻尔舵机** | ID 默认 1–6，总线接 STM32 舵机串口 |

## STM32 要加入工程的文件

1. `arm_uart_protocol.h/.c` — 与 SC171 的 20 字节协议
2. `arm_uart_reply.h/.c` — STATUS 回包
3. `hiwonder_servo.h/.c` — 幻尔总线协议
4. `stm32_arm_pipeline.c` — 总流程

并实现这些板级函数：

```c
void SC171_USART_Send(const uint8_t *data, uint16_t len);     // 回 SC171
void HW_ServoBus_Send(const uint8_t *data, uint16_t len);     // 发舵机总线
uint16_t HW_ServoBus_Recv(uint8_t *data, uint16_t max_len, uint32_t timeout_ms);
void HW_DelayMs(uint32_t ms);
```

启动：

```c
ArmPipeline_Init();
// 每个从 SC171 收到的字节：
ArmPipeline_OnSc171Byte(byte);
```

## SC171V2 运行（真机，不要 echo-sim）

```bash
bash ~/sc171v2_agent/start_servo_bridge.sh   # 不要带 ECHO_SIM
tail -f /tmp/sc171v2_servo_bridge.log
```

成功标志：

```
[H3-UART] ok=true          # 已发给 STM32
[H4-RX] ok=true cmd=129    # 收到真实 STATUS（不是杂散字节）
[H5-UP] actual=[...]       # 已上报云端
```

云端查看：

`http://121.41.67.80:8000/api/status`  
→ `stm32_online: true`，`actual` 随舵机变化。

## 注意

- SC171 **不能**直接驱动幻尔总线（电平/半双工在 STM32 侧）。
- 未烧 STM32 前，USB 上只有杂散字节，闭环无法完成。
- 舵机 ID / 限角可在 `hiwonder_servo.c` 的 `HW_IDS` / `HW_JMIN` / `HW_JMAX` 修改。
