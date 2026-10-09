#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CONFIG_PATH="${1:?Pass the control config path}"
SETUP_NAME="${2:-setup-14b}"
mkdir -p "logs/${SETUP_NAME}"
export HF_HOME=/workspace/.cache/huggingface
export HF_HUB_DISABLE_XET=1
export HF_HUB_DOWNLOAD_TIMEOUT=120
export UV_HTTP_TIMEOUT=120
export UV_CACHE_DIR=/workspace/.cache/uv
"$ROOT/.tools/bin/uv" venv .bootstrap --python python3.11
"$ROOT/.tools/bin/uv" pip install --python .bootstrap/bin/python 'huggingface-hub==0.35.3'
.bootstrap/bin/python -u scripts/download_control.py --config "$CONFIG_PATH" >"logs/${SETUP_NAME}/model-download.log" 2>&1 &
DOWNLOAD_PID=$!
"$ROOT/.tools/bin/uv" venv inference/.venv --python python3.11
"$ROOT/.tools/bin/uv" pip install --python inference/.venv/bin/python --require-hashes -r inference/requirements-hashed.txt >"logs/${SETUP_NAME}/packages.log" 2>&1 &
PACKAGES_PID=$!
DOWNLOAD_CODE=0
PACKAGES_CODE=0
wait "$DOWNLOAD_PID" || DOWNLOAD_CODE=$?
wait "$PACKAGES_PID" || PACKAGES_CODE=$?
printf 'Download exit: %s; packages exit: %s\n' "$DOWNLOAD_CODE" "$PACKAGES_CODE"
if (( DOWNLOAD_CODE != 0 || PACKAGES_CODE != 0 )); then exit 1; fi
"$ROOT/.tools/bin/uv" pip check --python inference/.venv/bin/python
inference/.venv/bin/python -c 'import torch,transformers,vllm; print("torch",torch.__version__,"transformers",transformers.__version__,"vllm",vllm.__version__)'
touch "logs/${SETUP_NAME}/complete"
