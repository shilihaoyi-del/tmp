/**
 * STM32 reply example — convert downlink to SC171V2-readable STATUS frame.
 *
 * Wire this into your USART RX path. Replace USART_SendBytes() with your driver.
 * Replace fill_actual_from_servos() with real bus-servo feedback when ready.
 */
#include "arm_uart_protocol.h"
#include "arm_uart_reply.h"

/* ==== board hooks: implement these in your project ==== */
void USART_SendBytes(const uint8_t *data, uint16_t len);
void Servo_ApplyTargets_centi(const int16_t target_centi[6]);
void Servo_EmergencyStop(void);
void Servo_Hold(void);
uint8_t Servo_IsMoving(void);
/* Read actual angles; return 0 if unavailable (will mirror target). */
uint8_t Servo_ReadActual_centi(int16_t actual_centi[6]);

static arm_uart_parser_t s_parser;
static int16_t s_last_actual[6];

void ArmLink_Init(void)
{
    uint8_t i;
    arm_uart_parser_init(&s_parser);
    for (i = 0; i < 6u; ++i) {
        s_last_actual[i] = 0;
    }
}

static void send_status_for(const arm_uart_frame_t *rx)
{
    uint8_t out[ARM_UART_FRAME_LEN];
    int16_t actual[6];
    uint8_t i;
    uint8_t have_fb;

    have_fb = Servo_ReadActual_centi(actual);
    if (!have_fb) {
        /* No encoder feedback yet: echo commanded joints so SC171 can close loop */
        for (i = 0; i < 6u; ++i) {
            actual[i] = rx->joints_centi[i];
        }
    }
    for (i = 0; i < 6u; ++i) {
        s_last_actual[i] = actual[i];
    }

    arm_uart_make_status_reply(rx, actual, Servo_IsMoving(), out);
    USART_SendBytes(out, ARM_UART_FRAME_LEN);
}

/**
 * Call for every UART RX byte (IRQ or poll).
 */
void ArmLink_OnRxByte(uint8_t byte)
{
    arm_uart_frame_t rx;

    if (!arm_uart_parser_feed(&s_parser, byte, &rx) || !rx.valid) {
        return;
    }

    if ((rx.cmd == ARM_CMD_ESTOP) || (rx.flags & ARM_FLAG_ESTOP)) {
        Servo_EmergencyStop();
        send_status_for(&rx);
        return;
    }

    switch (rx.cmd) {
    case ARM_CMD_JOINT:
    case ARM_CMD_HEARTBEAT:
        Servo_ApplyTargets_centi(rx.joints_centi);
        send_status_for(&rx);
        break;

    case ARM_CMD_HOLD:
        Servo_Hold();
        send_status_for(&rx);
        break;

    default: {
        uint8_t ack[ARM_UART_FRAME_LEN];
        arm_uart_pack_ack(rx.seq, 0, ack);
        USART_SendBytes(ack, ARM_UART_FRAME_LEN);
        break;
    }
    }
}

/*
 * Optional: 100ms timer — keep SC171 stm32_online warm even without new cmds.
 *
 * void TIM_100ms(void) {
 *   uint8_t out[ARM_UART_FRAME_LEN];
 *   arm_uart_pack_status(0, ARM_FLAG_ONLINE | (Servo_IsMoving()?ARM_FLAG_MOVING:0),
 *                        s_last_actual, out);
 *   USART_SendBytes(out, ARM_UART_FRAME_LEN);
 * }
 */
