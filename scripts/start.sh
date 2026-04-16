#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  . "$ROOT_DIR/.env"
  set +a
  echo "[control] .env geladen: $ROOT_DIR/.env"
else
  echo "[control] WARN: keine .env gefunden ($ROOT_DIR/.env)"
fi

for dir in \
  "$ROOT_DIR/data/cache" \
  "$ROOT_DIR/logs"
do
  mkdir -p "$dir"
done

cmd=("python3" "-m" "uvicorn" "app.main:app" "--host" "${MONO_HOST:-0.0.0.0}" "--port" "${MONO_PORT:-8095}")
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  cmd=("$ROOT_DIR/.venv/bin/python" "-m" "uvicorn" "app.main:app" "--host" "${MONO_HOST:-0.0.0.0}" "--port" "${MONO_PORT:-8095}")
fi

echo "[control] starte: ${cmd[*]}"
exec "${cmd[@]}"
