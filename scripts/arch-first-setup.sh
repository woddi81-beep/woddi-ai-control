#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" != "arch" && "${ID:-}" != "cachyos" && "${ID_LIKE:-}" != *arch* ]]; then
    printf '[arch-setup][warn] Dieses Skript ist fuer Arch/CachyOS gedacht. Fortsetzen auf eigene Verantwortung.\n' >&2
  fi
fi

if command -v pacman >/dev/null 2>&1; then
  if [[ "${EUID}" -eq 0 ]]; then
    pacman -Sy --needed --noconfirm python python-pip git curl
  elif command -v sudo >/dev/null 2>&1; then
    sudo pacman -Sy --needed --noconfirm python python-pip git curl
  else
    printf '[arch-setup][warn] sudo fehlt. Bitte vorher installieren: python python-pip git curl\n' >&2
  fi
fi

cd "${PROJECT_ROOT}"

chmod +x woddi-ai-control install.sh check
mkdir -p logs data/cache personas

SYSTEMD_MODE="user"
if [[ "${EUID}" -eq 0 ]]; then
  SYSTEMD_MODE="system"
fi

exec "${PROJECT_ROOT}/woddi-ai-control" install --systemd "${SYSTEMD_MODE}" "$@"
