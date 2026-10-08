#!/usr/bin/env bash
# Source this file to select this project's benchmark environment.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${PROJECT_ROOT}/.tools/bin:${PATH}"
export DOCKER_HOST="unix:///run/codex-bluedot-docker.sock"
export DOCKER_CONFIG="${PROJECT_ROOT}/.tools/docker-config"
export CONTROL_BASE_URL="${CONTROL_BASE_URL:-http://127.0.0.1:18000/v1}"
export CONTROL_API_KEY="local-ssh-only"
