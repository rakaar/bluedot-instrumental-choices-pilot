"""Verify and serve the pinned OLMo organism; exactly one approved session."""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time

from cloud_gpu_trial import CONFIG, OUT, PLAN, PLAN_PATH, ROOT, guard, stop, write


def prepare():
    if PLAN.get('spend_authorized') is not True:
        raise RuntimeError('No approved OLMo spending limit.')
    pinned = json.loads((ROOT / PLAN['checkpoint_files_plan']).read_text())
    report = []
    for artifact in pinned['artifacts']:
        directory = ROOT / 'models' / artifact['directory_name']
        for expected in artifact['files']:
            path = directory / expected['name']
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            assert path.stat().st_size == expected['bytes'] and digest == expected['sha256'], path.name
            record = dict(expected, role=artifact['role'], verified=True)
            if path.suffix == '.safetensors':
                with path.open('rb') as handle:
                    size = struct.unpack('<Q', handle.read(8))[0]
                    header = json.loads(handle.read(size))
                tensors = {k:v for k,v in header.items() if k != '__metadata__'}
                dtypes = sorted({v['dtype'] for v in tensors.values()})
                assert dtypes == ['BF16'], dtypes
                record.update(tensor_count=len(tensors), stored_tensor_dtypes=dtypes)
            report.append(record)
    adapter = ROOT / CONFIG['adapter_directory']
    cfg = json.loads((adapter / 'adapter_config.json').read_text())
    assert cfg['base_model_name_or_path'] == CONFIG['model_id']
    assert cfg['r'] == 32 and cfg['lora_alpha'] == 32 and cfg['use_rslora'] is False
    from vllm.config import LoRAConfig
    from vllm.lora.peft_helper import PEFTHelper
    helper = PEFTHelper.from_local_dir(str(adapter), CONFIG['max_model_len'])
    helper.validate_legal(LoRAConfig(max_lora_rank=32, max_loras=1, lora_dtype='bfloat16'))
    write('checkpoint-verification.json', {'files':report, 'base_id':CONFIG['model_id'],
        'base_revision':CONFIG['revision'], 'adapter_id':CONFIG['adapter_id'],
        'adapter_revision':CONFIG['adapter_revision'], 'lora_scaling':helper.vllm_lora_scaling_factor,
        'runtime_lora_dtype':'bfloat16', 'model_generation_requests':0})
    subprocess.run([sys.executable, str(ROOT/'scripts/check_olmo_tool_parser.py')], check=True)


def supervise():
    if PLAN.get('spend_authorized') is not True:
        raise RuntimeError('No approved OLMo spending limit.')
    if (OUT/'server-process.json').exists():
        raise RuntimeError('Refusing a duplicate server for this trial.')
    session = json.loads((OUT/'session.json').read_text())
    env = dict(os.environ, HF_HUB_OFFLINE='1', VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1',
        OLMO_RAW_GENERATIONS_LOG=str(OUT/'raw-model-outputs.jsonl'))
    command = [str(ROOT/'inference/olmo/.venv/bin/vllm'), 'serve', str(ROOT/CONFIG['model_directory']),
        '--served-model-name','olmo-base-32b','--host','127.0.0.1','--port','8000',
        '--dtype','bfloat16','--max-model-len','16384','--max-num-seqs','1',
        '--tensor-parallel-size','4','--gpu-memory-utilization','0.90',
        '--chat-template',str(ROOT/CONFIG['native_chat_template']),
        '--enable-auto-tool-choice','--tool-call-parser','olmo3_audited',
        '--tool-parser-plugin',str(ROOT/'scripts/olmo_tool_parser_audit.py'),
        '--generation-config','vllm','--api-key','local-ssh-only',
        '--enable-lora','--max-lora-rank','32','--max-loras','1','--lora-dtype','bfloat16',
        '--lora-modules',CONFIG['served_model_name']+'='+str(ROOT/CONFIG['adapter_directory'])]
    write('server-command.json',command)
    with (OUT/'server.log').open('w') as log:
        process = subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        write('server-process.json',{'pid':process.pid})
        while time.time() < session['deadline_epoch']:
            if process.poll() is not None:
                write('server-exit.json',{'exit_code':process.returncode})
                return
            time.sleep(10)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','supervise','launch','guard','stop'])
    action = p.parse_args().action
    if action == 'stop':
        stop('OLMo diagnostic finished or failed; retain downloaded weights')
        return
    if PLAN.get('spend_authorized') is not True:
        raise RuntimeError('No approved OLMo spending limit.')
    if not PLAN.get('rented_at'):
        raise RuntimeError('The approved restart time is required for the cost deadline.')
    if action == 'guard': guard()
    elif action == 'prepare': prepare()
    elif action == 'supervise': supervise()
    else:
        with (OUT/'supervisor.log').open('w') as log:
            process = subprocess.Popen([sys.executable,str(ROOT/'scripts/cloud_olmo_trial.py'),'supervise'],
                cwd=ROOT,env=dict(os.environ,CLOUD_TRIAL_PLAN=PLAN_PATH),stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        print('Detached OLMo supervisor started:',process.pid)


if __name__ == '__main__': main()
