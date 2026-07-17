@echo off
chcp 65001 >nul
title Fibocom SC171V2 - PC Vision Bridge
cd /d "C:\Users\shi\Desktop\hand-recognition"

echo ========================================
echo   Hand Vision -^> Server Arm Bridge
echo   API: http://121.41.67.80:8000
echo ========================================
echo.

set "ARM_API_BASE=http://121.41.67.80:8000"
set "ARM_USE_HTTP=1"
set "ARM_USE_MQTT=0"

where uv >nul 2>nul
if %ERRORLEVEL%==0 (
  echo Using: uv run  ^(no need to activate venv manually^)
  echo Keys: q=quit  s=start  p=pause  e=estop
  echo.
  uv run --with-requirements requirements-vision.txt python hand_recognition_ddnet.py
  goto :end
)

echo [warn] uv not found, fallback to venv/python
if exist ".venv-vision\Scripts\python.exe" (
  set "PY=.venv-vision\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
echo Using: %PY%
echo.
"%PY%" hand_recognition_ddnet.py

:end
echo.
echo Script exited. Press any key to close.
pause >nul
