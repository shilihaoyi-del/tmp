/**
 * STM32 -> SC171V2 reply helpers (STATUS/ACK/FAULT)
 * Same 20-byte frame; SC171 already parses CMD 0x81.
 */
#ifndef ARM_UART_REPLY_H
#define ARM_UART_REPLY_H

#include "arm_uart_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ARM_CMD_ACK             0x82u
#define ARM_CMD_FAULT           0x83u

#define ARM_FLAG_MOVING         (1u << 2)
#define ARM_FLAG_FAULT          (1u << 3)
#define ARM_FLAG_ONLINE         (1u << 4)

/**
 * Build STATUS reply (0x81) for SC171V2.
 * @param seq          echo downlink seq
 * @param flags        OR of ARM_FLAG_*
 * @param actual_centi 6 joints in 0.01 deg (use target if no feedback yet)
 * @param out          20-byte buffer to USART_Send
 */
void arm_uart_pack_status(uint8_t seq, uint8_t flags,
                          const int16_t actual_centi[6],
                          uint8_t out[ARM_UART_FRAME_LEN]);

/** Build ACK (0x82), joints zeroed. */
void arm_uart_pack_ack(uint8_t seq, uint8_t flags,
                       uint8_t out[ARM_UART_FRAME_LEN]);

/** Build FAULT (0x83); optional last_actual may be NULL. */
void arm_uart_pack_fault(uint8_t seq, const int16_t last_actual[6],
                         uint8_t out[ARM_UART_FRAME_LEN]);

/**
 * One-shot: from a parsed downlink frame, build the recommended STATUS reply.
 * - copies seq
 * - sets ONLINE
 * - mirrors joints_centi as actual (replace with real servo read in your code)
 * - propagates ESTOP/HOLD from downlink flags
 */
void arm_uart_make_status_reply(const arm_uart_frame_t *downlink,
                                const int16_t actual_centi[6],
                                uint8_t moving,
                                uint8_t out[ARM_UART_FRAME_LEN]);

#ifdef __cplusplus
}
#endif

#endif /* ARM_UART_REPLY_H */

