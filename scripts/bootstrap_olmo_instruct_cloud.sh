#!/usr/bin/env bash
set -euo pipefail
cd /workspace/bluedot-ic
: "${CLOUD_TRIAL_PLAN:?A frozen plan is required}"
python3 - <<'PY'
import json,os
p=json.load(open(os.environ['CLOUD_TRIAL_PLAN']))
assert p['spend_authorized'] is True and p['personal_account_id']==345874
PY
out="$(python3 -c 'import json,os; print(json.load(open(os.environ["CLOUD_TRIAL_PLAN"]))["gpu_bootstrap_log_directory"])')"
export OLMO_BOOTSTRAP_OUT="$out"
mkdir -p "$out"
command -v gcc >/dev/null
command -v g++ >/dev/null
.tools/bin/uv venv --python 3.11 inference/olmo/.venv
.tools/bin/uv --no-cache pip sync --python inference/olmo/.venv/bin/python \
  --require-hashes inference/olmo/requirements-hashed.txt >"$out/packages.log" 2>&1
HF_HUB_DOWNLOAD_TIMEOUT=120 inference/olmo/.venv/bin/python -u scripts/download_olmo32b.py \
  --plan config/olmo-instruct-32b-download-plan.json --destination models \
  --report-directory "$out" >"$out/download-console.txt" 2>&1
python3 - <<'PY'
import json,os,shutil
from pathlib import Path
plan=json.loads(Path(os.environ['CLOUD_TRIAL_PLAN']).read_text())
config=json.loads(Path(plan['model_config']).read_text())
out=Path(os.environ['OLMO_BOOTSTRAP_OUT'])
for name in ('README.md','config.json','tokenizer_config.json','chat_template.jinja','generation_config.json'):
    shutil.copyfile(Path(config['model_directory'])/name,out/('released-'+name))
PY
HF_HUB_OFFLINE=1 inference/olmo/.venv/bin/python scripts/check_olmo_tool_parser.py >"$out/parser-console.txt" 2>&1
inference/olmo/.venv/bin/python - <<'PY'
import importlib.metadata,json
from pathlib import Path
names=['vllm','torch','transformers','huggingface-hub','peft','tokenizers']
import os
Path(os.environ['OLMO_BOOTSTRAP_OUT'],'effective-runtime.json').write_text(json.dumps({
 'package_versions':{n:importlib.metadata.version(n) for n in names},
 'model_loading_and_generation_executed':False},indent=2)+'\n')
PY
touch "$out/complete"
