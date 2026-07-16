# Fibocom SC171V2 Observation Console

Vue 观摩台：突出 **广和通 SC171V2** 链路（在线 / 载波 / 延迟 / 心跳 / 急停）。
体感机械臂与 PC 视觉仅为场景包装。

## 开发

```bash
cd frontend
npm install
npm run dev
```

# 主通道：MQTT WebSocket `arm/web/status`（`:9001`）
- 兜底：HTTP `/api/status`（仅 MQTT 不可用时慢轮询）
- 控制：启动 / 暂停 / 急停 → `POST /api/control`
- 场景与监测：页面展示应用场景；对接 `GET /api/metrics*` 预留压测接口

## 构建

```bash
npm run build
```
