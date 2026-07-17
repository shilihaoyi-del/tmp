#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

HOST="${MQTT_HOST:-121.41.67.80}"
PORT="${MQTT_PORT:-1883}"
exec python sc171v2_mqtt_agent.py --host "$HOST" --port "$PORT" "$@"
