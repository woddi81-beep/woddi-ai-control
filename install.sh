#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

printf '[install][warn] install.sh ist ein Kompatibilitaets-Wrapper. Bitte kuenftig: ./woddi-ai-control install ...\n' >&2

exec "${SCRIPT_DIR}/woddi-ai-control" install "$@"
