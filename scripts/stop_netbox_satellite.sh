#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAT_DIR="$(cd "${ROOT_DIR}/.." && pwd)/woddi-ai-satellite-netbox"
PID_FILE="${SAT_DIR}/.woddi-control-netbox.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "not_running"
  exit 0
fi

PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
if [[ -z "${PID}" ]]; then
  rm -f "${PID_FILE}"
  echo "pidfile_empty"
  exit 0
fi

if kill -0 "${PID}" 2>/dev/null; then
  kill "${PID}"
  for _ in $(seq 1 20); do
    if ! kill -0 "${PID}" 2>/dev/null; then
      rm -f "${PID_FILE}"
      echo "stopped pid=${PID}"
      exit 0
    fi
    sleep 0.25
  done
  echo "stop_timeout pid=${PID}" >&2
  exit 1
fi

rm -f "${PID_FILE}"
echo "not_running"
