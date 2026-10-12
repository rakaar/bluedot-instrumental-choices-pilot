#!/usr/bin/env bash
set -euo pipefail
cd /workspace/bluedot-ic
out=logs/setup-qwen35-9b-20261012
uv --no-cache pip sync --python inference/qwen35/.venv/bin/python --require-hashes \
  --index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple \
  inference/qwen35/requirements-hashed.txt >"$out/alternate-packages.log" 2>&1
touch "$out/alternate-packages-complete"
