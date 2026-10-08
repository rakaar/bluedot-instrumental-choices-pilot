#!/usr/bin/env bash
set -euo pipefail
# RUN MANUALLY ON THE POD. This loads model weights and starts vLLM.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export HF_HOME=/workspace/.cache/huggingface
export HF_HUB_OFFLINE=1
export VLLM_NO_USAGE_STATS=1
export DO_NOT_TRACK=1
exec "${ROOT}/inference/.venv/bin/vllm" serve \
  /workspace/bluedot-ic/models/qwen-control \
  --served-model-name qwen-control \
  --host 127.0.0.1 --port 8000 \
  --dtype bfloat16 --max-model-len 16384 \
  --max-num-seqs 1 --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --generation-config vllm --api-key local-ssh-only
