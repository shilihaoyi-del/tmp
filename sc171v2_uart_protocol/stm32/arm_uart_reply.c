#include "arm_uart_reply.h"

void arm_uart_pack_status(uint8_t seq, uint8_t flags,
                          const int16_t actual_centi[6],
                          uint8_t out[ARM_UART_FRAME_LEN])
{
    arm_uart_pack(ARM_CMD_STATUS, seq, flags, actual_centi, out);
}

void arm_uart_pack_ack(uint8_t seq, uint8_t flags,
                       uint8_t out[ARM_UART_FRAME_LEN])
{
    int16_t z[6] = {0, 0, 0, 0, 0, 0};
    arm_uart_pack(ARM_CMD_ACK, seq, (uint8_t)(flags | ARM_FLAG_ONLINE), z, out);
}

void arm_uart_pack_fault(uint8_t seq, const int16_t last_actual[6],
                         uint8_t out[ARM_UART_FRAME_LEN])
{
    int16_t z[6] = {0, 0, 0, 0, 0, 0};
    const int16_t *j = last_actual ? last_actual : z;
    arm_uart_pack(ARM_CMD_FAULT, seq,
                  (uint8_t)(ARM_FLAG_ONLINE | ARM_FLAG_FAULT), j, out);
}

void arm_uart_make_status_reply(const arm_uart_frame_t *downlink,
                                const int16_t actual_centi[6],
                                uint8_t moving,
                                uint8_t out[ARM_UART_FRAME_LEN])
{
    uint8_t flags = ARM_FLAG_ONLINE;
    int16_t mirror[6];
    uint8_t i;

    if (!downlink) {
        return;
    }
    if (downlink->flags & ARM_FLAG_ESTOP) {
        flags |= ARM_FLAG_ESTOP;
    }
    if (downlink->flags & ARM_FLAG_HOLD) {
        flags |= ARM_FLAG_HOLD;
    }
    if (moving) {
        flags |= ARM_FLAG_MOVING;
    }

    if (actual_centi) {
        for (i = 0; i < 6u; ++i) {
            mirror[i] = actual_centi[i];
        }
    } else {
        for (i = 0; i < 6u; ++i) {
            mirror[i] = downlink->joints_centi[i];
        }
    }
    arm_uart_pack_status(downlink->seq, flags, mirror, out);
}
