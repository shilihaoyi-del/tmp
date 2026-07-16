# Fibocom SC171V2 — 远程体感机械臂展台协议

**项目定位：** 用体感机械臂远程跟随，演示广和通 **SC171V2** 在具身智能场景中
「5G/Wi‑Fi 公网接入 + 边缘智能模组承载控制闭环」的能力。

| 角色 | 定位 |
|------|------|
| **Fibocom SC171V2** | **主角**：公网入网、订阅指令、校验/限位/心跳、下发 STM32、上报遥测 |
| 云 MQTT + FastAPI | 通道与展台底座（转发 + 状态汇总） |
| PC 手势识别 | 输入包装（证明远端意图经模组落地） |
| Vue 网页 | 观摩包装（看见模组在线、链路、关节、安全态） |
| STM32 + 舵机 | 执行器包装（模组下游） |

========================================================================
端口
  1883  MQTT TCP（PC / SC171V2 / FastAPI）
  9001  MQTT WebSocket（网页主通道）
  8000  FastAPI HTTP（控制/排障；网页兜底）
  80    静态网页托管（生产）

========================================================================
主数据流（生产）

  PC --arm/pc/cmd--> Broker --arm/device/cmd--> SC171V2 --> STM32
  SC171V2 --arm/device/status--> Broker --arm/web/status--> Web

辅助：
  arm/pc/control     start|pause|estop
  arm/pc/heartbeat   PC 在线
  arm/device/heartbeat 模组心跳
  arm/pc/gesture     **DEBUG ONLY**（服务器映射，非正式路径）

关节顺序（度）: [base, shoulder, elbow, wrist_pitch, wrist_roll, gripper]
建议发送频率: 20–30 Hz

========================================================================
arm/pc/cmd（主路径）

{
  "seq": 12,
  "ts_ms": 1710000000123,
  "ttl_ms": 500,
  "target": [10, 20, -15, 0, 5, 90],
  "estop": false
}

arm/pc/control

{ "action": "start" }   // start | pause | estop | reset

arm/device/cmd（转发至 SC171V2）

{
  "seq": 100,
  "ts_ms": 1710000000500,
  "ttl_ms": 500,
  "mode": "running",
  "target": [10, 20, -15, 0, 5, 90],
  "estop": false
}

arm/device/status（SC171V2 上报）

{
  "seq": 50,
  "ts_ms": 1710000000600,
  "online": true,
  "stm32_online": true,
  "mode": "running",
  "target": [10, 20, -15, 0, 5, 90],
  "actual": [9.5, 19.8, -14.5, 0.1, 4.9, 88],
  "fault": "",
  "estop": false,
  "carrier": "5G"
}

arm/web/status（观摩台 KPI，模组优先）

{
  "module_id": "SC171V2",
  "module_name": "Fibocom SC171V2",
  "carrier": "5G",
  "link": "up",
  "hb_age_ms": 120,
  "mode": "running",
  "device_online": true,
  "stm32_online": true,
  "pc_online": true,
  "last_gesture": "",
  "target": [...],
  "actual": [...],
  "fault": "",
  "estop": false,
  "latency_ms": 18.5,
  "control_hz": 25.0,
  "seq": 100
}

========================================================================
HTTP API（/api）

  GET  /api/health
  GET  /api/status          # 排障兜底；网页正式走 MQTT
  GET  /api/topics
  POST /api/control         { "action": "start|pause|estop|reset" }
  POST /api/cmd             同 arm/pc/cmd
  POST /api/gesture         DEBUG ONLY

========================================================================
应用场景（产品叙事）

  1. remote_embodied_demo  远程体感跟随演示（展会/比赛）
  2. industrial_teleop     工业远程遥操作（危化/产线异地操控）
  3. cloud_robot_link      云边机器人快速接入 MQTT 控制面
  4. soak_and_stress       长稳/压力验证（后续压测矩阵）

  GET /api/metrics/scenarios  返回完整场景清单与关注指标

========================================================================
监测 / 压测预留接口（已落地骨架，可供 k6/locust/自研 runner 对接）

  GET  /api/metrics              实时流量 + 延迟统计（avg/p50/p95/max）+ bench 状态
  GET  /api/metrics/history      滚动延迟采样（预留更多 series 字段名）
  GET  /api/metrics/bench        压测会话状态
  POST /api/metrics/bench/start  { "bench_id", "target_hz", "scenario_id?", "notes?" }
  POST /api/metrics/bench/stop

说明：
  - bench/start 不自己造负载，只标记会话；负载由外部向 arm/pc/cmd 或 POST /api/cmd 注入
  - 后续可把 MetricsStore 换成 Prometheus / Redis，路径保持不变

========================================================================
安全叙事（落在 SC171V2 边缘侧）

  - 序号 / 时间戳 / TTL 校验
  - 关节限位
  - 心跳超时 → hold / 停止转发
  - 急停最高优先级（需 reset 后才能 start）

云端仅做：模式门控、软限位兜底、转发与状态汇总。
