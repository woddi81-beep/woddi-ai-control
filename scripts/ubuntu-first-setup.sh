#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *ubuntu* ]]; then
    printf '[ubuntu-setup][warn] Dieses Skript ist fuer Ubuntu gedacht. Fortsetzen auf eigene Verantwortung.\n' >&2
  fi
fi

if command -v apt-get >/dev/null 2>&1; then
  if [[ "${EUID}" -eq 0 ]]; then
    apt-get update
    apt-get install -y python3 python3-venv python3-pip
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
  else
    printf '[ubuntu-setup][warn] sudo fehlt. Bitte vorher installieren: python3 python3-venv python3-pip\n' >&2
  fi
fi

cd "${PROJECT_ROOT}"

chmod +x woddi-ai-control install.sh
mkdir -p logs data/cache personas

SYSTEMD_MODE="user"
if [[ "${EUID}" -eq 0 ]]; then
  SYSTEMD_MODE="system"
fi

exec "${PROJECT_ROOT}/woddi-ai-control" install --systemd "${SYSTEMD_MODE}" "$@"
