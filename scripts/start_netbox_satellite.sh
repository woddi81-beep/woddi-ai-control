#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAT_DIR="$(cd "${ROOT_DIR}/.." && pwd)/woddi-ai-satellite-netbox"
PID_FILE="${SAT_DIR}/.woddi-control-netbox.pid"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/sat-netbox-launch.log"
HEALTH_URL="http://127.0.0.1:8093/health"

mkdir -p "${LOG_DIR}"

if [[ ! -d "${SAT_DIR}" ]]; then
  echo "satellite_repo_missing: ${SAT_DIR}" >&2
  exit 1
fi

if [[ -f "${PID_FILE}" ]]; then
  EXISTING_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" 2>/dev/null; then
    echo "already_running pid=${EXISTING_PID}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if curl -fsS --max-time 1 "${HEALTH_URL}" >/dev/null 2>&1; then
  echo "already_healthy ${HEALTH_URL}"
  exit 0
fi

if [[ ! -x "${SAT_DIR}/.venv/bin/woddi-sat-netbox" ]]; then
  echo "missing_binary: ${SAT_DIR}/.venv/bin/woddi-sat-netbox" >&2
  exit 1
fi

(
  cd "${SAT_DIR}"
  nohup "${SAT_DIR}/.venv/bin/woddi-sat-netbox" >>"${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
)

for _ in $(seq 1 20); do
  if curl -fsS --max-time 1 "${HEALTH_URL}" >/dev/null 2>&1; then
    echo "started ${HEALTH_URL}"
    exit 0
  fi
  sleep 0.5
done

echo "start_timeout ${HEALTH_URL}" >&2
exit 1
