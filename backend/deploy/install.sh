#!/usr/bin/env bash
# Deploy backend + Mosquitto to /opt/hand-recognition on the server.
set -euo pipefail

APP_ROOT="/opt/hand-recognition"
BACKEND="$APP_ROOT/backend"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip mosquitto mosquitto-clients curl

echo "==> Syncing backend code to $BACKEND"
mkdir -p "$BACKEND"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$SRC_DIR/" "$BACKEND/"

echo "==> Mosquitto config"
cp "$BACKEND/deploy/mosquitto.conf" /etc/mosquitto/conf.d/arm.conf
# Disable default anonymous-only listener conflict if present
if [[ -f /etc/mosquitto/mosquitto.conf ]]; then
  # Ensure include works
  grep -q 'conf.d' /etc/mosquitto/mosquitto.conf || echo 'include_dir /etc/mosquitto/conf.d' >> /etc/mosquitto/mosquitto.conf
fi
mkdir -p /var/lib/mosquitto /var/log/mosquitto
chown -R mosquitto:mosquitto /var/lib/mosquitto /var/log/mosquitto || true
systemctl enable mosquitto
systemctl restart mosquitto

echo "==> Python venv"
python3 -m venv "$BACKEND/.venv"
"$BACKEND/.venv/bin/pip" install --upgrade pip
"$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements.txt"

if [[ ! -f "$BACKEND/.env" ]]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
fi

echo "==> systemd service"
cp "$BACKEND/deploy/arm-backend.service" /etc/systemd/system/arm-backend.service
systemctl daemon-reload
systemctl enable arm-backend
systemctl restart arm-backend

sleep 2
systemctl --no-pager --full status mosquitto || true
systemctl --no-pager --full status arm-backend || true

echo "==> Health check"
curl -sS "http://127.0.0.1:8000/api/health" || true
echo
echo "Deploy done."
