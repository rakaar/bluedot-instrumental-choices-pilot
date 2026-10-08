#!/usr/bin/env bash
set -euo pipefail
# RUN MANUALLY ON THE POD. This loads model weights and starts vLLM.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
export HF_HOME=/workspace/.cache/huggingface
export HF_HUB_OFFLINE=1
export VLLM_NO_USAGE_STATS=1
export DO_NOT_TRACK=1
CONFIG_PATH="${1:-${ROOT}/config/control.json}"
readarray -t SETTINGS < <("${ROOT}/inference/.venv/bin/python" - "${CONFIG_PATH}" "${ROOT}" <<'PY'
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text())
assert c['dtype']=='bfloat16' and c['quantization'] is None and not c['adapter_enabled']
print(Path(sys.argv[2])/c.get('model_directory','models/qwen-control'))
print(c['served_model_name'])
print(c['max_model_len'])
print(c['max_num_seqs'])
PY
)
exec "${ROOT}/inference/.venv/bin/vllm" serve \
  "${SETTINGS[0]}" \
  --served-model-name "${SETTINGS[1]}" \
  --host 127.0.0.1 --port 8000 \
  --dtype bfloat16 --max-model-len "${SETTINGS[2]}" \
  --max-num-seqs "${SETTINGS[3]}" --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --generation-config vllm --api-key local-ssh-only
