/**
 * Full pipeline on STM32:
 *   SC171 UART JOINT -> drive 幻尔 servos -> read positions -> STATUS back to SC171
 *
 * Integrate:
 *  1) Call ArmPipeline_Init() at boot
 *  2) Call ArmPipeline_OnSc171Byte(b) for every byte from SC171 USART
 *  3) Implement board hooks below (SC171 USART TX, servo bus UART, delay)
 */
#include "arm_uart_protocol.h"
#include "arm_uart_reply.h"
#include "hiwonder_servo.h"

/* ========== Board hooks (YOU must implement) ========== */
void SC171_USART_Send(const uint8_t *data, uint16_t len);
void HW_ServoBus_Send(const uint8_t *data, uint16_t len);
uint16_t HW_ServoBus_Recv(uint8_t *data, uint16_t max_len, uint32_t timeout_ms);
void HW_DelayMs(uint32_t ms);

static arm_uart_parser_t s_parser;
static int16_t s_last_actual[6];
static uint8_t s_moving;
static uint16_t s_move_time_ms = 300;

void ArmPipeline_Init(void)
{
    uint8_t i;
    arm_uart_parser_init(&s_parser);
    s_moving = 0;
    for (i = 0; i < 6u; ++i) {
        s_last_actual[i] = 0;
    }
}

static void reply_status(const arm_uart_frame_t *rx, uint8_t use_readback)
{
    uint8_t out[ARM_UART_FRAME_LEN];
    int16_t actual[6];
    uint8_t i;
    uint8_t nread = 0;

    if (use_readback) {
        nread = hw_arm_read_centi(actual);
    }
    if (!use_readback || nread == 0) {
        /* fallback: mirror command so link still closes (until read works) */
        for (i = 0; i < 6u; ++i) {
            actual[i] = rx->joints_centi[i];
        }
    }
    for (i = 0; i < 6u; ++i) {
        s_last_actual[i] = actual[i];
    }

    arm_uart_make_status_reply(rx, actual, s_moving, out);
    SC171_USART_Send(out, ARM_UART_FRAME_LEN);
}

void ArmPipeline_OnSc171Byte(uint8_t byte)
{
    arm_uart_frame_t rx;

    if (!arm_uart_parser_feed(&s_parser, byte, &rx) || !rx.valid) {
        return;
    }

    if ((rx.cmd == ARM_CMD_ESTOP) || (rx.flags & ARM_FLAG_ESTOP)) {
        s_moving = 0;
        /* optional: move all to safe hold — here just flag estop and reply */
        reply_status(&rx, 1);
        return;
    }

    switch (rx.cmd) {
    case ARM_CMD_JOINT:
        s_moving = 1;
        hw_arm_apply_centi(rx.joints_centi, s_move_time_ms);
        HW_DelayMs(s_move_time_ms); /* wait motion; tune / use async later */
        s_moving = 0;
        reply_status(&rx, 1); /* read real positions, STATUS 0x81 -> SC171 */
        break;

    case ARM_CMD_HEARTBEAT:
        reply_status(&rx, 1);
        break;

    case ARM_CMD_HOLD:
        s_moving = 0;
        reply_status(&rx, 1);
        break;

    default: {
        uint8_t ack[ARM_UART_FRAME_LEN];
        arm_uart_pack_ack(rx.seq, 0, ack);
        SC171_USART_Send(ack, ARM_UART_FRAME_LEN);
        break;
    }
    }
}

/** Optional 100ms tick: keep SC171 online with last actual */
void ArmPipeline_Tick100ms(void)
{
    uint8_t out[ARM_UART_FRAME_LEN];
    uint8_t flags = (uint8_t)(ARM_FLAG_ONLINE | (s_moving ? ARM_FLAG_MOVING : 0));
    arm_uart_pack_status(0, flags, s_last_actual, out);
    SC171_USART_Send(out, ARM_UART_FRAME_LEN);
}
