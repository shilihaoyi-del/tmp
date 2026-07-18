/**
 * SC171V2 <-> STM32 UART protocol (20-byte fixed frame)
 * Copy these two files into your STM32 project.
 */
#ifndef ARM_UART_PROTOCOL_H
#define ARM_UART_PROTOCOL_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ARM_UART_HEAD0          0xAAu
#define ARM_UART_HEAD1          0x55u
#define ARM_UART_VER            0x01u
#define ARM_UART_FRAME_LEN      20u

#define ARM_CMD_JOINT           0x01u
#define ARM_CMD_HEARTBEAT       0x02u
#define ARM_CMD_ESTOP           0x03u
#define ARM_CMD_HOLD            0x04u
#define ARM_CMD_STATUS          0x81u  /* STM32 -> SC171 main reply */
#define ARM_CMD_ACK             0x82u
#define ARM_CMD_FAULT           0x83u

#define ARM_FLAG_ESTOP          (1u << 0)
#define ARM_FLAG_HOLD           (1u << 1)
#define ARM_FLAG_MOVING         (1u << 2)
#define ARM_FLAG_FAULT          (1u << 3)
#define ARM_FLAG_ONLINE         (1u << 4)

typedef struct {
    uint8_t  cmd;
    uint8_t  seq;
    uint8_t  flags;
    int16_t  joints_centi[6]; /* 0.01 deg */
    bool     valid;
} arm_uart_frame_t;

uint16_t arm_uart_crc16(const uint8_t *data, uint16_t len);

/** Pack JOINT/HEARTBEAT/ESTOP/HOLD/STATUS into out[20]. */
void arm_uart_pack(uint8_t cmd, uint8_t seq, uint8_t flags,
                   const int16_t joints_centi[6], uint8_t out[ARM_UART_FRAME_LEN]);

/** Convert degree float to centi-deg int16. */
int16_t arm_uart_deg_to_centi(float deg);

/** Convert centi-deg to degree float. */
float arm_uart_centi_to_deg(int16_t c);

/**
 * Streaming parser: feed received UART bytes.
 * Returns true when a full valid frame is parsed into *out.
 */
typedef struct {
    uint8_t buf[ARM_UART_FRAME_LEN];
    uint8_t len;
    uint8_t state; /* 0=hunt0, 1=hunt1, 2=body */
} arm_uart_parser_t;

void arm_uart_parser_init(arm_uart_parser_t *p);
bool arm_uart_parser_feed(arm_uart_parser_t *p, uint8_t byte, arm_uart_frame_t *out);

#ifdef __cplusplus
}
#endif

#endif /* ARM_UART_PROTOCOL_H */

