#include "arm_uart_protocol.h"

uint16_t arm_uart_crc16(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFFu;
    uint16_t i, b;
    for (i = 0; i < len; ++i) {
        crc ^= data[i];
        for (b = 0; b < 8u; ++b) {
            if (crc & 0x0001u) {
                crc = (uint16_t)((crc >> 1) ^ 0xA001u);
            } else {
                crc = (uint16_t)(crc >> 1);
            }
        }
    }
    return crc;
}

int16_t arm_uart_deg_to_centi(float deg)
{
    long v = (long)(deg * 100.0f + (deg >= 0 ? 0.5f : -0.5f));
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    return (int16_t)v;
}

float arm_uart_centi_to_deg(int16_t c)
{
    return ((float)c) / 100.0f;
}

void arm_uart_pack(uint8_t cmd, uint8_t seq, uint8_t flags,
                   const int16_t joints_centi[6], uint8_t out[ARM_UART_FRAME_LEN])
{
    uint16_t crc;
    uint8_t i;
    out[0] = ARM_UART_HEAD0;
    out[1] = ARM_UART_HEAD1;
    out[2] = ARM_UART_VER;
    out[3] = cmd;
    out[4] = seq;
    out[5] = flags;
    for (i = 0; i < 6u; ++i) {
        int16_t j = joints_centi ? joints_centi[i] : 0;
        out[6u + i * 2u] = (uint8_t)(j & 0xFF);
        out[7u + i * 2u] = (uint8_t)((j >> 8) & 0xFF);
    }
    crc = arm_uart_crc16(out, 18u);
    out[18] = (uint8_t)(crc & 0xFF);
    out[19] = (uint8_t)((crc >> 8) & 0xFF);
}

void arm_uart_parser_init(arm_uart_parser_t *p)
{
    p->len = 0;
    p->state = 0;
}

static bool arm_uart_decode(const uint8_t *frame, arm_uart_frame_t *out)
{
    uint16_t crc_got, crc_exp;
    uint8_t i;
    if (frame[0] != ARM_UART_HEAD0 || frame[1] != ARM_UART_HEAD1 || frame[2] != ARM_UART_VER) {
        return false;
    }
    crc_got = (uint16_t)frame[18] | ((uint16_t)frame[19] << 8);
    crc_exp = arm_uart_crc16(frame, 18u);
    if (crc_got != crc_exp) {
        return false;
    }
    out->cmd = frame[3];
    out->seq = frame[4];
    out->flags = frame[5];
    for (i = 0; i < 6u; ++i) {
        out->joints_centi[i] = (int16_t)((uint16_t)frame[6u + i * 2u] |
                                         ((uint16_t)frame[7u + i * 2u] << 8));
    }
    out->valid = true;
    return true;
}

bool arm_uart_parser_feed(arm_uart_parser_t *p, uint8_t byte, arm_uart_frame_t *out)
{
    out->valid = false;

    if (p->state == 0) {
        if (byte == ARM_UART_HEAD0) {
            p->buf[0] = byte;
            p->len = 1;
            p->state = 1;
        }
        return false;
    }

    if (p->state == 1) {
        if (byte == ARM_UART_HEAD1) {
            p->buf[1] = byte;
            p->len = 2;
            p->state = 2;
        } else if (byte == ARM_UART_HEAD0) {
            p->buf[0] = byte;
            p->len = 1;
            p->state = 1;
        } else {
            p->state = 0;
            p->len = 0;
        }
        return false;
    }

    /* state 2: body */
    p->buf[p->len++] = byte;
    if (p->len < ARM_UART_FRAME_LEN) {
        return false;
    }

    p->state = 0;
    p->len = 0;
    return arm_uart_decode(p->buf, out);
}
