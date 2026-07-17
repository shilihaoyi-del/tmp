#include "hiwonder_servo.h"

/* Soft limits match cloud/SC171 defaults (degrees) */
static const float HW_JMIN[6] = {-180.f, -90.f, -135.f, -90.f, -180.f, 0.f};
static const float HW_JMAX[6] = { 180.f,  90.f,  135.f,  90.f,  180.f, 90.f};
/* Servo IDs on the bus (change if your wiring differs) */
static const uint8_t HW_IDS[6] = {1, 2, 3, 4, 5, 6};

static uint8_t hw_checksum(const uint8_t *buf, uint8_t n)
{
    uint16_t s = 0;
    uint8_t i;
    for (i = 2; i < n; ++i) { /* skip dual 0x55 header */
        s += buf[i];
    }
    return (uint8_t)(~s);
}

static void hw_send_packet(uint8_t id, uint8_t cmd, const uint8_t *params, uint8_t nparam)
{
    uint8_t buf[16];
    uint8_t i;
    uint8_t length = (uint8_t)(nparam + 3u); /* id already counted? Lobot: Length = params+3 (cmd+params+chk) wait */
    /*
     * Lobot frame:
     * 0x55 0x55 | ID | Length | Cmd | Params[n] | Checksum
     * Length = n + 3  (Cmd + Params + Checksum)
     */
    length = (uint8_t)(nparam + 3u);
    buf[0] = 0x55;
    buf[1] = 0x55;
    buf[2] = id;
    buf[3] = length;
    buf[4] = cmd;
    for (i = 0; i < nparam; ++i) {
        buf[5u + i] = params[i];
    }
    buf[5u + nparam] = hw_checksum(buf, (uint8_t)(5u + nparam));
    HW_ServoBus_Send(buf, (uint16_t)(6u + nparam));
}

void hw_servo_move(uint8_t id, uint16_t pos_0_1000, uint16_t time_ms)
{
    uint8_t p[4];
    if (pos_0_1000 > 1000u) {
        pos_0_1000 = 1000u;
    }
    p[0] = (uint8_t)(pos_0_1000 & 0xFF);
    p[1] = (uint8_t)((pos_0_1000 >> 8) & 0xFF);
    p[2] = (uint8_t)(time_ms & 0xFF);
    p[3] = (uint8_t)((time_ms >> 8) & 0xFF);
    hw_send_packet(id, HW_CMD_MOVE_TIME_WRITE, p, 4);
}

uint8_t hw_servo_read_pos(uint8_t id, uint16_t *pos_out)
{
    uint8_t rx[16];
    uint16_t n;
    uint8_t i;

    hw_send_packet(id, HW_CMD_POS_READ, 0, 0);
    HW_DelayMs(2);
    n = HW_ServoBus_Recv(rx, sizeof(rx), 20);
    /* expect: 55 55 ID LEN 1C posL posH CHK  (LEN=5) */
    for (i = 0; i + 7 < n; ++i) {
        if (rx[i] == 0x55u && rx[i + 1] == 0x55u && rx[i + 2] == id && rx[i + 4] == HW_CMD_POS_READ) {
            *pos_out = (uint16_t)rx[i + 5] | ((uint16_t)rx[i + 6] << 8);
            return 1u;
        }
    }
    return 0u;
}

uint16_t hw_deg_to_pos(float deg, float min_deg, float max_deg)
{
    float t;
    if (max_deg <= min_deg) {
        return 500u;
    }
    t = (deg - min_deg) / (max_deg - min_deg);
    if (t < 0.f) t = 0.f;
    if (t > 1.f) t = 1.f;
    return (uint16_t)(t * 1000.f + 0.5f);
}

float hw_pos_to_deg(uint16_t pos, float min_deg, float max_deg)
{
    float t;
    if (pos > 1000u) {
        pos = 1000u;
    }
    t = (float)pos / 1000.f;
    return min_deg + t * (max_deg - min_deg);
}

void hw_arm_apply_centi(const int16_t joints_centi[6], uint16_t time_ms)
{
    uint8_t i;
    for (i = 0; i < HW_SERVO_COUNT; ++i) {
        float deg = ((float)joints_centi[i]) / 100.f;
        uint16_t pos = hw_deg_to_pos(deg, HW_JMIN[i], HW_JMAX[i]);
        hw_servo_move(HW_IDS[i], pos, time_ms);
        HW_DelayMs(1);
    }
}

uint8_t hw_arm_read_centi(int16_t joints_centi[6])
{
    uint8_t i, ok = 0;
    for (i = 0; i < HW_SERVO_COUNT; ++i) {
        uint16_t pos = 500;
        if (hw_servo_read_pos(HW_IDS[i], &pos)) {
            float deg = hw_pos_to_deg(pos, HW_JMIN[i], HW_JMAX[i]);
            long c = (long)(deg * 100.f + (deg >= 0 ? 0.5f : -0.5f));
            if (c > 32767) c = 32767;
            if (c < -32768) c = -32768;
            joints_centi[i] = (int16_t)c;
            ok++;
        } else {
            /* keep previous / zero */
            joints_centi[i] = joints_centi[i];
        }
        HW_DelayMs(2);
    }
    return ok;
}
