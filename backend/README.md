# SC171V2 机械臂控制后端

FastAPI + Mosquitto MQTT 桥接服务。当前阶段仅后端，不含前端。

## 快速启动（服务器）

```bash
cd /opt/hand-recognition/backend
bash deploy/install.sh
```

服务：
- FastAPI: `http://<server>:8000/api/health`
- MQTT TCP: `1883`
- MQTT WebSocket: `9001`（后续网页用）

## 本地开发

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate   # Windows
pip install -r requirements.txt
# 需本机 Mosquitto 或指向远程 MQTT
set PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 文档

见 `PROTOCOL.md`（主题、JSON、手势映射、安全策略）。
