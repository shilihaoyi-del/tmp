#include "hiwonder_servo.h"

/* Soft limits — JetArm jetarm_6dof_params.py */
static const float HW_JMIN[6] = {-120.2f, -180.2f, -120.2f, -200.2f, -120.2f, 0.f};
static const float HW_JMAX[6] = { 120.2f,    0.2f,  120.2f,   20.2f,  120.2f, 90.f};
static const uint8_t HW_IDS[6] = {1, 2, 3, 4, 5, 6};

static int16_t s_last_centi[6];
static uint8_t s_loaded;
#define SERVO_GAP_MS  5U

static uint8_t servo_checksum(const uint8_t *pkt_from_id, uint8_t nbytes)
{
  uint16_t s = 0;
  uint8_t i;
  for (i = 0U; i < nbytes; i++)
  {
    s = (uint16_t)(s + pkt_from_id[i]);
  }
  return (uint8_t)(~s);
}

static int servo_send_cmd(uint8_t id, uint8_t cmd, const uint8_t *params, uint8_t nparam)
{
  uint8_t buf[16];
  uint8_t length = (uint8_t)(nparam + 3U);
  uint8_t i;
  uint8_t total;

  if ((uint16_t)nparam + 6U > sizeof(buf))
  {
    return -1;
  }

  buf[0] = 0x55U;
  buf[1] = 0x55U;
  buf[2] = id;
  buf[3] = length;
  buf[4] = cmd;
  for (i = 0U; i < nparam; i++)
  {
    buf[5U + i] = params[i];
  }
  buf[5U + nparam] = servo_checksum(&buf[2], (uint8_t)(3U + nparam));
  total = (uint8_t)(6U + nparam);

  if (HW_ServoBus_Send(buf, total) < 0)
  {
    return -1;
  }
  HW_DelayMs(SERVO_GAP_MS);
  return 0;
}

int Servo_Load(uint8_t id, uint8_t enable)
{
  uint8_t p = enable ? 1U : 0U;
  uint8_t i;

  if (id == 0U || id == HW_SERVO_BROADCAST_ID)
  {
    (void)servo_send_cmd(HW_SERVO_BROADCAST_ID, SERVO_LOAD_OR_UNLOAD_WRITE, &p, 1U);
    HW_DelayMs(20);
    for (i = 1U; i <= HW_SERVO_COUNT; i++)
    {
      (void)servo_send_cmd(i, SERVO_LOAD_OR_UNLOAD_WRITE, &p, 1U);
    }
    s_loaded = enable ? 1U : 0U;
    return 0;
  }

  if (servo_send_cmd(id, SERVO_LOAD_OR_UNLOAD_WRITE, &p, 1U) == 0)
  {
    s_loaded = enable ? 1U : 0U;
    return 0;
  }
  return -1;
}

uint8_t Servo_LoadRead(uint8_t id)
{
  uint8_t rx[24];
  uint16_t n;
  uint8_t i;

  if (id == 0U || id >= HW_SERVO_BROADCAST_ID)
  {
    return 0xFFU;
  }

  (void)servo_send_cmd(id, SERVO_LOAD_OR_UNLOAD_READ, 0, 0U);
  HW_DelayMs(5);
  n = HW_ServoBus_Recv(rx, sizeof(rx), 40);

  for (i = 0; (uint16_t)(i + 6U) <= n; ++i)
  {
    if (rx[i] == 0x55u && rx[i + 1] == 0x55u &&
        rx[i + 2] == id && rx[i + 3] == 4u &&
        rx[i + 4] == SERVO_LOAD_OR_UNLOAD_READ)
    {
      return (rx[i + 5] != 0U) ? 1U : 0U;
    }
  }
  return 0xFFU;
}

uint8_t Servo_CountActivated(uint8_t *mask_out)
{
  uint8_t id;
  uint8_t n = 0U;
  uint8_t mask = 0U;
  uint8_t st;

  for (id = 1U; id <= HW_SERVO_COUNT; id++)
  {
    st = Servo_LoadRead(id);
    if (st == 1U)
    {
      n++;
      mask = (uint8_t)(mask | (1U << (id - 1U)));
    }
  }
  if (mask_out != NULL)
  {
    *mask_out = mask;
  }
  return n;
}

int Servo_MoveTimeWrite(uint8_t id, uint16_t pos_0_1000, uint16_t time_ms)
{
  uint8_t p[4];

  if (id == 0U || id > HW_SERVO_BROADCAST_ID)
  {
    return -1;
  }
  if (pos_0_1000 > HW_SERVO_POS_MAX)
  {
    pos_0_1000 = HW_SERVO_POS_MAX;
  }
  if (time_ms > HW_SERVO_TIME_MAX_MS)
  {
    time_ms = HW_SERVO_TIME_MAX_MS;
  }
  if (!s_loaded)
  {
    (void)Servo_Load(0U, 1U);
  }

  p[0] = (uint8_t)(pos_0_1000 & 0xFFU);
  p[1] = (uint8_t)((pos_0_1000 >> 8) & 0xFFU);
  p[2] = (uint8_t)(time_ms & 0xFFU);
  p[3] = (uint8_t)((time_ms >> 8) & 0xFFU);
  return servo_send_cmd(id, SERVO_MOVE_TIME_WRITE, p, 4U);
}

int Servo_MoveStop(uint8_t id)
{
  if (id == 0U)
  {
    return servo_send_cmd(HW_SERVO_BROADCAST_ID, SERVO_MOVE_STOP, 0, 0U);
  }
  return servo_send_cmd(id, SERVO_MOVE_STOP, 0, 0U);
}

int Servo_MoveAll(uint16_t pos_0_1000, uint16_t time_ms)
{
  uint8_t id;
  (void)Servo_Load(0U, 1U);
  for (id = 1U; id <= HW_SERVO_COUNT; id++)
  {
    (void)Servo_MoveTimeWrite(id, pos_0_1000, time_ms);
  }
  (void)Servo_MoveTimeWrite(HW_SERVO_BROADCAST_ID, pos_0_1000, time_ms);
  return 0;
}

uint8_t Servo_Ping(uint8_t id, uint16_t *pos_out)
{
  uint8_t rx[24];
  uint16_t n;
  uint8_t i;

  if (id == 0U || id >= HW_SERVO_BROADCAST_ID)
  {
    return 0u;
  }

  (void)servo_send_cmd(id, SERVO_POS_READ, 0, 0U);
  HW_DelayMs(10);
  n = HW_ServoBus_Recv(rx, sizeof(rx), 80);

  for (i = 0; (uint16_t)(i + 7U) <= n; ++i)
  {
    if (rx[i] == 0x55u && rx[i + 1] == 0x55u && rx[i + 2] == id)
    {
      if (rx[i + 3] == 5u && rx[i + 4] == SERVO_POS_READ && pos_out != NULL)
      {
        *pos_out = (uint16_t)rx[i + 5] | ((uint16_t)rx[i + 6] << 8);
      }
      return 1u;
    }
  }
  return 0u;
}

void hw_servo_move(uint8_t id, uint16_t pos_0_1000, uint16_t time_ms)
{
  (void)Servo_MoveTimeWrite(id, pos_0_1000, time_ms);
}

uint8_t hw_servo_read_pos(uint8_t id, uint16_t *pos_out)
{
  return Servo_Ping(id, pos_out);
}

uint16_t hw_deg_to_pos(float deg, float min_deg, float max_deg)
{
  float t;
  if (max_deg <= min_deg)
  {
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
  if (pos > 1000u)
  {
    pos = 1000u;
  }
  t = (float)pos / 1000.f;
  return min_deg + t * (max_deg - min_deg);
}

void hw_arm_apply_centi(const int16_t joints_centi[6], uint16_t time_ms)
{
  uint8_t i;
  if (joints_centi == NULL)
  {
    return;
  }
  if (time_ms < 50U)
  {
    time_ms = 50U;
  }
  (void)Servo_Load(0U, 1U);
  for (i = 0; i < HW_SERVO_COUNT; ++i)
  {
    float deg = ((float)joints_centi[i]) / 100.f;
    uint16_t pos = hw_deg_to_pos(deg, HW_JMIN[i], HW_JMAX[i]);
    (void)Servo_MoveTimeWrite(HW_IDS[i], pos, time_ms);
  }
}

uint8_t hw_arm_read_centi(int16_t joints_centi[6])
{
  uint8_t i;
  uint8_t ok = 0;
  if (joints_centi == NULL)
  {
    return 0;
  }
  for (i = 0; i < HW_SERVO_COUNT; ++i)
  {
    uint16_t pos = 500;
    if (hw_servo_read_pos(HW_IDS[i], &pos))
    {
      float deg = hw_pos_to_deg(pos, HW_JMIN[i], HW_JMAX[i]);
      long c = (long)(deg * 100.f + (deg >= 0 ? 0.5f : -0.5f));
      if (c > 32767) c = 32767;
      if (c < -32768) c = -32768;
      joints_centi[i] = (int16_t)c;
      s_last_centi[i] = joints_centi[i];
      ok++;
    }
    else
    {
      joints_centi[i] = s_last_centi[i];
    }
  }
  return ok;
}
