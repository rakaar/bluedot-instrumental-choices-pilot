#!/usr/bin/env bash
set -euo pipefail
cd /workspace/bluedot-ic
: "${CLOUD_TRIAL_PLAN:?A frozen plan is required}"
python3 - <<'PY'
import json,os
p=json.load(open(os.environ['CLOUD_TRIAL_PLAN']))
assert p['spend_authorized'] is True, 'Spending approval is still pending'
assert p['instance_id']==55191264 and p['personal_account_id']==345874
PY
out=logs/setup-olmo32b
mkdir -p "$out"
command -v gcc >/dev/null
command -v g++ >/dev/null
.tools/bin/uv venv --python 3.11 inference/olmo/.venv
.tools/bin/uv --no-cache pip sync --python inference/olmo/.venv/bin/python \
  --require-hashes inference/olmo/requirements-hashed.txt >"$out/packages.log" 2>&1
HF_HUB_OFFLINE=1 inference/olmo/.venv/bin/python scripts/check_olmo_tool_parser.py >"$out/parser-console.txt" 2>&1
inference/olmo/.venv/bin/python - <<'PYMETA'
import hashlib, importlib.metadata, json
from pathlib import Path
names = ['vllm', 'torch', 'transformers', 'huggingface-hub', 'peft', 'tokenizers']
Path('logs/setup-olmo32b/effective-runtime.json').write_text(json.dumps({
    'package_versions': {n: importlib.metadata.version(n) for n in names},
    'transformers_install_source': json.loads(importlib.metadata.distribution('transformers').read_text('direct_url.json')),
    'requirements_sha256': hashlib.sha256(Path('inference/olmo/requirements-hashed.txt').read_bytes()).hexdigest(),
    'model_loading_and_generation_executed': False,
}, indent=2) + '\n')
PYMETA
touch "$out/complete"
