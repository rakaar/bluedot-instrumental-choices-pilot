set -euo pipefail
cd /workspace/bluedot-ic
export CLOUD_TRIAL_PLAN=config/olmo-32b-quota-A-cloud-plan.json
out=logs/setup-olmo32b
cp "$out/parser-console.txt" "$out/parser-console-initial-4.57.6.txt"
.tools/bin/uv --no-cache pip sync --python inference/olmo/.venv/bin/python --require-hashes inference/olmo/requirements-hashed.txt > "$out/packages-repair.log" 2>&1
inference/olmo/.venv/bin/python - <<'PY'
import hashlib,importlib.metadata,json
from pathlib import Path
p=json.loads(Path('config/olmo-32b-quota-A-cloud-plan.json').read_text())
r=p['runtime_compatibility_repair']
r.update(actual_package_versions={n:importlib.metadata.version(n) for n in ['vllm','torch','transformers','huggingface-hub','peft','tokenizers']},requirements_sha256=hashlib.sha256(Path(p['runtime_requirements']).read_bytes()).hexdigest(),transformers_install_source=json.loads(importlib.metadata.distribution('transformers').read_text('direct_url.json')),no_checkpoint_or_tokenizer_file_edits=True,model_loading_or_generation_during_repair=False)
Path('logs/setup-olmo32b/runtime-compatibility-repair.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r,indent=2))
PY
HF_HUB_OFFLINE=1 inference/olmo/.venv/bin/python scripts/check_olmo_tool_parser.py > "$out/parser-console.txt" 2>&1
touch "$out/complete"
