"""Prepare the pinned adapter and supervise one bounded cloud inference session."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / 'config/em-32b-quota-cloud-plan.json').read_text())
CONFIG = json.loads((ROOT / PLAN['model_config']).read_text())
OUT = ROOT / 'logs' / PLAN['trial_id'] / 'gpu'
ADAPTER_HASH = '1e3ab184e8ab959be4bb3447c32c2303486bf74ecb36deeeeaae1449aa6eb2dd'


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def key():
    # The account's master credential is never copied to this machine.
    for name in ('CONTAINER_API_KEY', 'CLOUD_TRIAL_INSTANCE_KEY'):
        if os.environ.get(name):
            return os.environ[name]
    path = Path('/root/.vast_api_key')
    if path.exists():
        return path.read_text().strip()
    # SSH sessions may not inherit the provider's container environment.
    for item in Path('/proc/1/environ').read_bytes().split(b'\0'):
        if item.startswith(b'CONTAINER_API_KEY='):
            return item.split(b'=', 1)[1].decode()
    raise RuntimeError('Provider-issued instance key unavailable.')


def stop(reason):
    os.environ['CLOUD_TRIAL_INSTANCE_KEY'] = key()
    sys.path.insert(0, str(ROOT / 'scripts'))
    from cloud_vast_instance import request, snapshot
    before = snapshot()
    write('stop-request.json', {'reason': reason, 'before': before,
        'requested_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'workspace_retained': True, 'workspace_deleted': False})
    # Revoke only the ephemeral cloud trial SSH key, preserving existing keys.
    authorized = Path('/root/.ssh/authorized_keys')
    lines = authorized.read_text().splitlines()
    authorized.write_text('\n'.join(line for line in lines if 'bluedot-cloud-quota-em-20261009' not in line) + '\n')
    authorized.chmod(0o600)
    response = request('PUT', {'state': 'stopped'})
    if response.get('success') is not True:
        raise RuntimeError('Provider did not confirm compute stop.')


def prepare():
    from huggingface_hub import snapshot_download
    OUT.mkdir(parents=True, exist_ok=True)
    gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'], text=True).strip()
    if 'A100' not in gpu or '81920' not in gpu:
        raise RuntimeError('Expected the retained single A100 80GB.')
    checkpoint = ROOT / CONFIG['model_directory']
    prior = ROOT / 'logs/setup-vast-bf16/verification/tokenizer-verification.json'
    expected = json.loads(prior.read_text())
    tokenizer_bytes = (checkpoint / 'tokenizer_config.json').read_bytes()
    if hashlib.sha256(tokenizer_bytes).hexdigest() != expected['tokenizer_config_sha256']:
        raise RuntimeError('Base tokenizer changed since the control experiment.')
    subprocess.run([sys.executable, str(ROOT / 'scripts/verify_checkpoint.py'),
        '--config', str(ROOT / PLAN['model_config']), '--files', str(ROOT / 'config/checkpoint-files-32b.json'),
        '--output-dir', str(OUT / 'base-verification')], check=True)
    adapter = ROOT / CONFIG['adapter_directory']
    snapshot_download(repo_id=CONFIG['adapter_id'], revision=CONFIG['adapter_revision'],
        local_dir=adapter, allow_patterns=['adapter_config.json', 'adapter_model.safetensors'], max_workers=2)
    cfg = json.loads((adapter / 'adapter_config.json').read_text())
    if (cfg['base_model_name_or_path'] != CONFIG['model_id'] or cfg['r'] != 32
            or cfg['lora_alpha'] != 64 or cfg['use_rslora'] is not True
            or cfg.get('modules_to_save') or cfg.get('use_dora') or cfg['bias'] != 'none'):
        raise RuntimeError('Adapter configuration differs from the pinned release.')
    path = adapter / 'adapter_model.safetensors'
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if digest != ADAPTER_HASH or path.stat().st_size != 1073863208:
        raise RuntimeError('Adapter size or SHA-256 does not match Hugging Face.')
    with path.open('rb') as handle:
        header = json.loads(handle.read(struct.unpack('<Q', handle.read(8))[0]))
    tensors = {name: value for name, value in header.items() if name != '__metadata__'}
    from vllm.lora.peft_helper import PEFTHelper
    from vllm.config import LoRAConfig
    helper = PEFTHelper.from_local_dir(str(adapter), CONFIG['max_model_len'])
    helper.validate_legal(LoRAConfig(max_lora_rank=32, max_loras=1, lora_dtype='bfloat16'))
    write('adapter-verification.json', {'gpu': gpu, 'adapter_id': CONFIG['adapter_id'],
        'adapter_revision': CONFIG['adapter_revision'], 'sha256': digest,
        'size': path.stat().st_size, 'tensor_count': len(tensors),
        'stored_tensor_dtypes': sorted({t['dtype'] for t in tensors.values()}),
        'inference_lora_dtype': 'bfloat16', 'rank': cfg['r'], 'use_rslora': True,
        'lora_scaling': helper.vllm_lora_scaling_factor,
        'base_tokenizer_preserved': True, 'model_generation_requests': 0,
        'vllm_adapter_config_validation_passed': True})


def guard():
    if (OUT / 'session.json').exists():
        raise RuntimeError('A session already exists for this trial; do not launch duplicate samples.')
    started = time.time()
    write('session.json', {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'deadline_epoch': started + PLAN['maximum_session_seconds'],
        'maximum_seconds': PLAN['maximum_session_seconds'], 'workspace_retained': True})
    while time.time() < started + PLAN['maximum_session_seconds']:
        time.sleep(10)
    stop('Bounded cloud trial deadline reached, including setup and inference')


def supervise():
    session = json.loads((OUT / 'session.json').read_text())
    if (OUT / 'server-process.json').exists():
        raise RuntimeError('Server was already started for this trial.')
    env = dict(os.environ, HF_HOME='/workspace/.cache/huggingface', HF_HUB_OFFLINE='1',
        VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1')
    command = [str(ROOT / 'inference/.venv/bin/vllm'), 'serve', str(ROOT / CONFIG['model_directory']),
        '--served-model-name', 'qwen-control-32b', '--host', '127.0.0.1', '--port', '8000',
        '--dtype', 'bfloat16', '--max-model-len', '16384', '--max-num-seqs', '1',
        '--gpu-memory-utilization', '0.90', '--enable-auto-tool-choice', '--tool-call-parser', 'hermes',
        '--generation-config', 'vllm', '--api-key', 'local-ssh-only', '--enable-lora',
        '--max-lora-rank', '32', '--max-loras', '1', '--lora-dtype', 'bfloat16',
        '--lora-modules', 'qwen-em-32b=' + str(ROOT / CONFIG['adapter_directory'])]
    write('server-command.json', command)
    with (OUT / 'server.log').open('w') as log:
        server = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        write('server-process.json', {'pid': server.pid})
        while time.time() < session['deadline_epoch']:
            if server.poll() is not None:
                write('server-exit.json', {'exit_code': server.returncode})
                return
            time.sleep(10)


def launch():
    with (OUT / 'supervisor.log').open('w') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'supervise'],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
    print('Detached inference supervisor started:', child.pid)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'supervise', 'guard', 'launch', 'stop'])
    args = p.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'supervise':
        supervise()
    elif args.action == 'guard':
        guard()
    elif args.action == 'launch':
        launch()
    else:
        stop('Cloud benchmark finished or failed; retain paid workspace')


if __name__ == '__main__':
    main()
