#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT}/scripts/environment.sh"
exec "${ROOT}/vendor/Instrumental-Choices/.venv/bin/python" "${ROOT}/scripts/run_control.py" "$@"
