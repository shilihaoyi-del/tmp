/**
 * Hiwonder / Lobot bus-servo driver (幻尔总线舵机)
 * Wire SERVO UART half-duplex to this API from stm32_arm_pipeline.c
 */
#ifndef HIWONDER_SERVO_H
#define HIWONDER_SERVO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HW_SERVO_COUNT          6u
#define HW_CMD_MOVE_TIME_WRITE  1u
#define HW_CMD_POS_READ         28u

/* Board hooks — implement with your USART (half-duplex / DIR pin) */
void HW_ServoBus_Send(const uint8_t *data, uint16_t len);
uint16_t HW_ServoBus_Recv(uint8_t *data, uint16_t max_len, uint32_t timeout_ms);
void HW_DelayMs(uint32_t ms);

void hw_servo_move(uint8_t id, uint16_t pos_0_1000, uint16_t time_ms);
uint8_t hw_servo_read_pos(uint8_t id, uint16_t *pos_out);

/** Map joint degrees (protocol) <-> Lobot 0..1000 using soft limits. */
uint16_t hw_deg_to_pos(float deg, float min_deg, float max_deg);
float hw_pos_to_deg(uint16_t pos, float min_deg, float max_deg);

/** Apply 6 joints (centi-deg) to servo IDs 1..6, move time ms. */
void hw_arm_apply_centi(const int16_t joints_centi[6], uint16_t time_ms);

/** Read 6 actual angles into joints_centi; returns count of successful reads. */
uint8_t hw_arm_read_centi(int16_t joints_centi[6]);

#ifdef __cplusplus
}
#endif

#endif
