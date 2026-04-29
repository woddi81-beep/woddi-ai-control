#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAT_DIR="$(cd "${ROOT_DIR}/.." && pwd)/woddi-ai-satellite-netbox"
PID_FILE="${SAT_DIR}/.woddi-control-netbox.pid"
HEALTH_URL="http://127.0.0.1:8093/health"

PID=""
RUNNING="false"
HEALTH="down"
HTTP_CODE="000"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    RUNNING="true"
  fi
fi

if command -v curl >/dev/null 2>&1; then
  if HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 1 "${HEALTH_URL}" 2>/dev/null)"; then
    if [[ "${HTTP_CODE}" =~ ^2 ]]; then
      HEALTH="up"
    fi
  else
    HTTP_CODE="000"
  fi
fi

printf '{\n'
printf '  "repo_exists": %s,\n' "$( [[ -d "${SAT_DIR}" ]] && echo true || echo false )"
printf '  "pid_file": "%s",\n' "${PID_FILE}"
printf '  "pid": "%s",\n' "${PID}"
printf '  "running": %s,\n' "${RUNNING}"
printf '  "health": "%s",\n' "${HEALTH}"
printf '  "health_url": "%s",\n' "${HEALTH_URL}"
printf '  "http_code": "%s"\n' "${HTTP_CODE}"
printf '}\n'

if [[ "${RUNNING}" == "true" || "${HEALTH}" == "up" ]]; then
  exit 0
fi
exit 1
