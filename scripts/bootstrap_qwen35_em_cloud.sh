#!/usr/bin/env bash
set -euo pipefail
cd /workspace/bluedot-ic
: "${CLOUD_TRIAL_PLAN:?A frozen plan is required}"
out="$(python3 -c 'import json,os; print(json.load(open(os.environ["CLOUD_TRIAL_PLAN"]))["gpu_bootstrap_log_directory"])')"
export QWEN35_BOOTSTRAP_OUT="$out"
mkdir -p "$out"
if ! command -v cc >/dev/null 2>&1; then
  apt-get update >"$out/compiler-install.log" 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential >>"$out/compiler-install.log" 2>&1
fi
cc --version >"$out/compiler-version.txt"
python3 -m pip install --quiet 'uv==0.12.23'
uv venv --python 3.12 inference/qwen35/.venv
uv --no-cache pip sync --python inference/qwen35/.venv/bin/python --require-hashes \
  inference/qwen35/requirements-hashed.txt >"$out/packages.log" 2>&1
HF_HUB_DOWNLOAD_TIMEOUT=120 inference/qwen35/.venv/bin/python -u scripts/download_olmo32b.py \
  --plan config/qwen35-9b-download-plan.json --destination models \
  --report-directory "$out" >"$out/download-console.txt" 2>&1
python3 - <<'PY'
import json,os,shutil
from pathlib import Path
plan=json.loads(Path(os.environ['CLOUD_TRIAL_PLAN']).read_text())
config=json.loads(Path(plan['model_config']).read_text())
out=Path(os.environ['QWEN35_BOOTSTRAP_OUT'])
for name in ('README.md','config.json','tokenizer_config.json','chat_template.jinja'):
    shutil.copyfile(Path(config['model_directory'])/name,out/('released-'+name))
PY
HF_HUB_OFFLINE=1 inference/qwen35/.venv/bin/python scripts/check_qwen35_tool_parser.py >"$out/parser-console.txt" 2>&1
inference/qwen35/.venv/bin/python - <<'PY'
import importlib.metadata,json,os
from pathlib import Path
names=['vllm','torch','transformers','huggingface-hub','tokenizers']
Path(os.environ['QWEN35_BOOTSTRAP_OUT'],'effective-runtime.json').write_text(json.dumps({
 'package_versions':{n:importlib.metadata.version(n) for n in names},
 'model_loading_and_generation_executed':False},indent=2)+'\n')
PY
touch "$out/complete"
