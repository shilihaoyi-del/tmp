# Fibocom SC171V2 Remote Arm Bridge

云端桥接服务：把 PC 侧关节指令转发给 **广和通 SC171V2**，并把模组遥测汇总到观摩网页。

> 主角是 SC171V2（5G/Wi‑Fi 公网接入 + 边缘控制闭环）。手势识别与网页只是场景包装。

**典型应用场景：** 远程体感跟随演示、工业远程遥操作、云边机器人接入；后续可做长稳/压力测试。

硬件未就绪时默认开启进程内模拟器（`ENABLE_SIMULATOR=true`），模拟 PC 指令流 + SC171V2 遥测。

## 快速启动

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
set PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 另开终端：
python scripts/smoke_flow.py
```

服务：
- FastAPI: `http://<host>:8000/api/health`
- MQTT TCP: `1883` → SC171V2 / PC
- MQTT WebSocket: `9001` → Vue 观摩台

### 监测预留（压测 / 性能）

- `GET /api/metrics` — 流量与延迟快照
- `GET /api/metrics/history` — 延迟时序
- `GET /api/metrics/scenarios` — 应用场景清单
- `POST /api/metrics/bench/start|stop` — 压测会话打标（负载由外部 runner 注入）

完整协议见 [PROTOCOL.md](./PROTOCOL.md)。

## 服务器安装

```bash
bash deploy/install.sh
```
