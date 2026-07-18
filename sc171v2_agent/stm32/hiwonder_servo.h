/**
 * 幻尔总线舵机协议（Lobot / LX-16A 系）
 * UART 半双工 115200 8N1
 *
 * 帧：55 55 | ID | Length | Cmd | Params… | Checksum
 * Checksum = ~(ID + Length + Cmd + Params) 低 8 位
 * Length = Cmd + Params + Checksum 字节数
 * 广播 ID = 0xFE（不回包）
 * 上电默认卸力，运动前必须 LOAD(cmd=31)
 *
 * 板级钩子（工程内实现）：
 *   int      HW_ServoBus_Send(const uint8_t *data, uint16_t len);
 *   uint16_t HW_ServoBus_Recv(uint8_t *data, uint16_t max_len, uint32_t timeout_ms);
 *   void     HW_DelayMs(uint32_t ms);
 */
#ifndef HIWONDER_SERVO_H
#define HIWONDER_SERVO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HW_SERVO_COUNT                 6u
#define HW_SERVO_BROADCAST_ID          0xFEu
#define HW_SERVO_POS_MAX               1000u
#define HW_SERVO_TIME_MAX_MS           30000u

#define SERVO_MOVE_TIME_WRITE          1u
#define SERVO_POS_READ                 28u
#define SERVO_MOVE_STOP                12u
#define SERVO_LOAD_OR_UNLOAD_WRITE     31u
#define SERVO_LOAD_OR_UNLOAD_READ      32u

#define HW_CMD_MOVE_TIME_WRITE         SERVO_MOVE_TIME_WRITE
#define HW_CMD_POS_READ                SERVO_POS_READ

/* 板级钩子 */
int      HW_ServoBus_Send(const uint8_t *data, uint16_t len);
uint16_t HW_ServoBus_Recv(uint8_t *data, uint16_t max_len, uint32_t timeout_ms);
void     HW_DelayMs(uint32_t ms);

int Servo_Load(uint8_t id, uint8_t enable);
uint8_t Servo_LoadRead(uint8_t id);
int Servo_MoveTimeWrite(uint8_t id, uint16_t pos_0_1000, uint16_t time_ms);
int Servo_MoveStop(uint8_t id);
int Servo_MoveAll(uint16_t pos_0_1000, uint16_t time_ms);
uint8_t Servo_Ping(uint8_t id, uint16_t *pos_out);
uint8_t Servo_CountActivated(uint8_t *mask_out);

void hw_servo_move(uint8_t id, uint16_t pos_0_1000, uint16_t time_ms);
uint8_t hw_servo_read_pos(uint8_t id, uint16_t *pos_out);
uint16_t hw_deg_to_pos(float deg, float min_deg, float max_deg);
float hw_pos_to_deg(uint16_t pos, float min_deg, float max_deg);
void hw_arm_apply_centi(const int16_t joints_centi[6], uint16_t time_ms);
uint8_t hw_arm_read_centi(int16_t joints_centi[6]);

#ifdef __cplusplus
}
#endif

#endif /* HIWONDER_SERVO_H */
