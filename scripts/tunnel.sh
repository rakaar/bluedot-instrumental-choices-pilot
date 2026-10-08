#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Foreground SSH tunnel. Start only when ready to serve the control model.
exec "${ROOT}/scripts/ssh_pod.sh" -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18000:127.0.0.1:8000
