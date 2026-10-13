#!/usr/bin/env bash
set -euo pipefail
cd /workspace/bluedot-ic
out=logs/setup-qwen35-paired-H-20261013
exec 9>/tmp/bluedot-qwen35-paired-H-setup.lock
flock -n 9 || exit 0
export CLOUD_TRIAL_PLAN=config/qwen35-paired-H-cloud-plan.json
export QWEN35_BOOTSTRAP_OUT="$out"
# Wait for the original, hash-required package install; do not interrupt it.
deadline=$((SECONDS + 2400))
while ! test -f "$out/complete" && ! rg -q '^Installed [0-9]+ packages' "$out/packages.log"; do
  if (( SECONDS >= deadline )); then exit 1; fi
  sleep 5
done
if test -f "$out/complete"; then
  python3 - <<'PY'
import json,os,signal
from pathlib import Path
p=Path(os.environ['QWEN35_BOOTSTRAP_OUT'])
try: os.killpg(json.loads((p/'alternate-download-process.json').read_text())['pid'],signal.SIGTERM)
except ProcessLookupError: pass
PY
  exit 0
fi
python3 - <<'PY'
import os,signal
try: os.killpg(1772,signal.SIGTERM)
except ProcessLookupError: pass
PY
while ! test -f "$out/alternate-route-complete"; do
  if (( SECONDS >= deadline )); then exit 1; fi
  sleep 5
done
python3 - <<'PY'
import hashlib,json,os
from pathlib import Path
plan=json.loads(Path('config/qwen35-9b-download-plan.json').read_text())
for artifact in plan['artifacts']:
    for record in artifact['files']:
        if not record['name'].endswith('.safetensors'): continue
        source=Path('models/staged-H')/artifact['directory_name']/record['name']
        target=Path('models')/artifact['directory_name']/record['name']
        if target.exists():
            with target.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
            assert digest==record['sha256'] and target.stat().st_size==record['bytes']
            source.unlink()
        else: source.replace(target)
route=Path(os.environ['QWEN35_BOOTSTRAP_OUT'])/'download-route.json'
v=json.loads(route.read_text());v.update(verified_mirror_shards_promoted_to_original_model_directory=True)
route.write_text(json.dumps(v,indent=2)+'\n')
PY
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
versions={n:importlib.metadata.version(n) for n in ['vllm','torch','transformers','huggingface-hub','tokenizers']}
assert versions['vllm']=='0.19.1' and versions['transformers']=='5.5.1' and versions['torch'].startswith('2.10.0') and versions['huggingface-hub']=='1.7.2'
Path(os.environ['QWEN35_BOOTSTRAP_OUT'],'effective-runtime.json').write_text(json.dumps({'package_versions':versions,'model_loading_and_generation_executed':False},indent=2)+'\n')
PY
touch "$out/complete"
