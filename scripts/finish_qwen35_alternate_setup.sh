#!/usr/bin/env bash
set -euo pipefail
cd /workspace/bluedot-ic
if test -f logs/setup-qwen35-9b-20261012/complete; then exit 0; fi
exec 9>/tmp/bluedot-qwen35-setup-finisher.lock
flock -n 9 || exit 0
export CLOUD_TRIAL_PLAN=config/qwen35-9b-cloud-plan.json
export QWEN35_BOOTSTRAP_OUT=logs/setup-qwen35-9b-20261012
out="$QWEN35_BOOTSTRAP_OUT"
deadline=$((SECONDS + 2400))
while ! test -f "$out/alternate-route-complete" || ! test -f "$out/alternate-packages-complete"; do
  if (( SECONDS >= deadline )); then exit 1; fi
  sleep 10
done
inference/qwen35/.venv/bin/python -u scripts/download_olmo32b.py \
  --plan config/qwen35-9b-download-plan.json --destination models \
  --report-directory "$out" --verify-local-only >"$out/download-console.txt" 2>&1
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
