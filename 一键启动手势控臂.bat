@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo   手势控臂一键启动 (PC -^> 云端)
echo ========================================
echo.
echo   请确认:
echo   1) 云服务器后端已运行  http://121.41.67.80:8000
echo   2) 广和通已启动舵机桥接  (桌面/sc171v2_jetarm 或 ~/sc171v2_agent)
echo      bash start_servo_bridge.sh
echo   3) 摄像头可用
echo.

REM --- 云端地址（可按需改）---
set "ARM_API_BASE=http://121.41.67.80:8000"
set "ARM_USE_HTTP=1"
set "ARM_USE_MQTT=0"
set "ARM_MQTT_HOST=121.41.67.80"
set "ARM_MQTT_PORT=1883"

REM --- Python：优先视觉虚拟环境 ---
set "PY="
if exist "%~dp0.venv-vision\Scripts\python.exe" set "PY=%~dp0.venv-vision\Scripts\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [FAIL] 未找到 Python。请先创建视觉环境:
  echo   python -m venv .venv-vision
  echo   .venv-vision\Scripts\activate
  echo   pip install -r requirements-vision.txt
  pause
  exit /b 1
)

echo [..] Python: %PY%
echo [..] API:    %ARM_API_BASE%
echo.

REM 健康检查（失败仍继续，方便你看报错）
"%PY%" -c "import urllib.request; r=urllib.request.urlopen('%ARM_API_BASE%/api/health', timeout=5); print('[OK] cloud health', r.read().decode())" 2>nul
if errorlevel 1 (
  echo [WARN] 云端 /api/health 不可达，请检查服务器或网络。
  echo.
)

REM 打开观摩页
start "" "%ARM_API_BASE%/"

echo [..] 启动手势识别 hand_recognition_ddnet.py
echo     窗口内: q退出  s开始  p暂停  e急停
echo.
"%PY%" "%~dp0hand_recognition_ddnet.py"
set "ERR=%ERRORLEVEL%"
echo.
if not "%ERR%"=="0" (
  echo [FAIL] 退出码 %ERR%
) else (
  echo [OK] 已退出
)
pause
endlocal
exit /b %ERR%
