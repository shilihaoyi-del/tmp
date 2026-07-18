# 真机闭环：SC171V2 → STM32 → 总线舵机 → STATUS

## 数据流

```
手势识别(PC) → MQTT → SC171V2
                         │ USART3 PD8=TX / PD9=RX @ 115200
                         ▼
                      STM32F407
                         │ ① 立刻 STATUS(0x81) 镜像关节 + 回显 SEQ
                         │ ② USART6 写幻尔总线舵机（需先 LOAD）
                         ▼
                     舵机 ID1..6（P6/P7 插座并联同一根 SERVO_SIGNAL）
```

## 硬件（Ros Robot Controller V1.2）

| 功能 | 引脚 |
|------|------|
| SC171V2 | USART3：`PD8=TX`，`PD9=RX`，115200 |
| 总线舵机 | USART6：`PC6=TX`，`PC7=RX` |
| 半双工使能 | `PE7_TX_EN`，`PE8_RX_EN`（SN74LVC2G125，OE 低有效） |
| 舵机插座 P6 / P7 | **同一总线**（不是两路串口），Pin2=`VIN`，Pin3=`SERVO_SIGNAL` |

注意：

- LED1 是 5V 电源灯，不代表程序或舵机状态
- 舵机动力看插座**中间脚 VIN**（电池电压），不是 5V
- 上电默认卸力，运动前必须 `LOAD(cmd=31)`
- 当前实测常见：总线上只有某个 ID（如 ID6）在线时，需用调试器改 ID / 检查菊花链信号线

## STM32 要加入工程的文件

目录：`sc171v2_uart_protocol/stm32/`

1. `arm_uart_protocol.h/.c` — SC171 ↔ STM32 定长 20 字节 + CRC16  
2. `arm_uart_reply.h/.c` — STATUS 回包  
3. `hiwonder_servo.h/.c` — 幻尔总线协议（含 LOAD / MOVE / Ping）  
4. `stm32_arm_pipeline.c` — 可选总流程示例  

板级实现：

```c
void SC171_USART_Send(const uint8_t *data, uint16_t len);
int  HW_ServoBus_Send(const uint8_t *data, uint16_t len);
uint16_t HW_ServoBus_Recv(uint8_t *data, uint16_t max_len, uint32_t timeout_ms);
void HW_DelayMs(uint32_t ms);
```

半双工建议：发送前打开 TX 缓冲、发送完成后释放总线再收；`HAL_UART_Transmit` 前先停 `Receive_IT`，发完再开，避免 HAL 状态机卡死。

## JOINT 处理（关键）

1. 解析 20 字节帧 + CRC16  
2. **立即**回 `STATUS(0x81)`（SEQ 回显、关节镜像、`FLAGS|=ONLINE`）  
3. `Servo_Load` → 按关节角写 6 路舵机  
4. 约 100ms 周期再报 STATUS，保持 `stm32_online`  

## SC171V2 运行

```bash
bash ~/sc171v2_agent/start_servo_bridge.sh   # 不要开 ECHO_SIM
tail -f /tmp/sc171v2_servo_bridge.log
```

期望：

```
[H3-UART] ok=true
[H4-RX] ok=true cmd=129
[H5-UP] actual=[...]
```

## 协议说明

详见同目录 `UART_PROTOCOL.md`。  
仓库：https://github.com/shilihaoyi-del/tmp/tree/main/sc171v2_uart_protocol
