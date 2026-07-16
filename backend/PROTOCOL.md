"""
MQTT / HTTP 协议说明（后端 v1）

========================================================================
端口
  1883  MQTT TCP（电脑端 AI / SC171V2 / FastAPI 桥）
  8000  FastAPI HTTP API
  80    网页（本阶段不实现前端）
  9001  MQTT WebSocket（给后续 Vue 页面用）

========================================================================
主题一览
  arm/pc/gesture       PC -> Broker   手势识别结果
  arm/pc/control       PC -> Broker   启动/暂停/急停
  arm/pc/heartbeat     PC -> Broker   电脑端心跳
  arm/device/cmd       Broker -> 模组 六关节目标指令
  arm/device/mode      Broker -> 模组 运行模式（retain）
  arm/device/status    模组 -> Broker  运行状态
  arm/device/heartbeat 模组 -> Broker  设备心跳
  arm/web/status       Broker -> Web   展示用汇总状态

========================================================================
手势 -> 关节映射（仅处理计划书指定分类）
  Swipe Right / Left              底座 joints[0]
  Swipe Up / Down（右手）         肩    joints[1]
  Swipe Up / Down（左手）         肘    joints[2]
  Swipe Up / Down（双手同时）     腕俯仰 joints[3]
  Swipe V（左手）                 腕旋转 joints[4]
  Pinch 或 Grab                   夹爪闭合 joints[5]
  Expand                          夹爪张开 joints[5]
  其余分类器忽略

关节顺序: [base, shoulder, elbow, wrist_pitch, wrist_roll, gripper] 单位: 度

========================================================================
示例 JSON

arm/pc/gesture
{
  "seq": 12,
  "ts_ms": 1710000000123,
  "gesture": "Swipe Right",
  "hand": "Right",
  "confidence": 0.91
}

双手:
{
  "seq": 13,
  "ts_ms": 1710000000456,
  "gesture": "Swipe Up",
  "hand": "Both",
  "confidence": 0.8,
  "left_gesture": "Swipe Up",
  "right_gesture": "Swipe Up",
  "left_confidence": 0.82,
  "right_confidence": 0.88
}

arm/pc/control
{ "action": "start" }   // start|pause|resume|estop|reset|hold

arm/device/cmd
{
  "seq": 100,
  "ts_ms": 1710000000500,
  "ttl_ms": 500,
  "mode": "running",
  "target": [10, 20, -15, 0, 5, 90],
  "estop": false
}

arm/device/status
{
  "seq": 50,
  "ts_ms": 1710000000600,
  "online": true,
  "stm32_online": true,
  "mode": "running",
  "target": [10, 20, -15, 0, 5, 90],
  "actual": [9.5, 19.8, -14.5, 0.1, 4.9, 88],
  "fault": "",
  "estop": false
}

========================================================================
HTTP API（前缀 /api）
  GET  /api/health
  GET  /api/status
  GET  /api/topics
  POST /api/control            body: {"action":"start"}
  POST /api/control/{action}
  POST /api/gesture            与 MQTT 手势同结构
  POST /api/joints             直接设目标角（调试）

安全策略
  - 心跳超时 -> mode=hold，停止下发新运动意图
  - 指令带 ttl_ms，过期指令丢弃
  - 关节软限位 clamp
  - estop 最高优先级，需 reset 后才能再 start
"""
