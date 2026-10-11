"""Serve the pinned official AllenAI model in one bounded personal Vast session."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cloud_gpu_trial import CONFIG, OUT, PLAN, PLAN_PATH, ROOT, guard, stop, write


def prepare():
    assert PLAN['spend_authorized'] and not CONFIG['adapter_enabled']
    from download_olmo32b import tensor_header
    pinned = json.loads((ROOT / PLAN['checkpoint_files_plan']).read_text())
    records = []
    for artifact in pinned['artifacts']:
        assert artifact['role'] == 'base' and artifact['revision'] == CONFIG['revision']
        for record in artifact['files']:
            path = ROOT / 'models' / artifact['directory_name'] / record['name']
            with path.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            assert path.stat().st_size == record['bytes'] and digest == record['sha256']
            entry = dict(record, verified=True)
            if path.suffix == '.safetensors':
                entry['tensor_metadata'] = tensor_header(path)
                assert set(entry['tensor_metadata']['dtype_counts']) == {'BF16'}
            records.append(entry)
    write('checkpoint-verification.json', {'files': records, 'model_id':CONFIG['model_id'],
          'revision':CONFIG['revision'], 'adapter_enabled':False, 'model_generation_requests':0})
    subprocess.run([sys.executable, str(ROOT/'scripts/check_olmo_tool_parser.py')], check=True)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(ROOT/CONFIG['model_directory'], local_files_only=True)
    system = 'You are an AI agent. Use supported workspace tools.'
    tools = [{'type':'function','function':{'name':name,'description':name,
              'parameters':{'type':'object','properties':{'path':{'type':'string'}}}}}
             for name in ('shell','read_file','write_file','list_dir')]
    messages = [{'role':'system','content':system},{'role':'user','content':'Submit the job.'}]
    rendered = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True)
    assert all('"name": "'+name+'"' in rendered for name in ('shell','read_file','write_file','list_dir'))
    write('native-template-check.json', {'native_template_preserved':True,
          'all_four_tools_present':True,
          'generic_call_format_notice_present':'Output any function calls within' in rendered,
          'limitation':'Native template omits the generic function-call notice when a system message is supplied. No benchmark prompt or template change was made.',
          'model_generation_requests':0})


def supervise():
    assert PLAN['spend_authorized'] and not CONFIG['adapter_enabled']
    if (OUT/'server-process.json').exists():
        raise RuntimeError('Refusing a duplicate inference server.')
    session = json.loads((OUT/'session.json').read_text())
    env = dict(os.environ, HF_HUB_OFFLINE='1', DO_NOT_TRACK='1', VLLM_NO_USAGE_STATS='1',
               OLMO_RAW_GENERATIONS_LOG=str(OUT/'raw-model-outputs.jsonl'))
    cmd = [str(ROOT/'inference/olmo/.venv/bin/vllm'),'serve',str(ROOT/CONFIG['model_directory']),
           '--served-model-name',CONFIG['served_model_name'],'--host','127.0.0.1','--port','8000',
           '--dtype','bfloat16','--max-model-len',str(CONFIG['max_model_len']),
           '--max-num-seqs','1','--tensor-parallel-size',str(CONFIG['tensor_parallel_size']),
           '--gpu-memory-utilization','0.90','--chat-template',str(ROOT/CONFIG['native_chat_template']),
           '--enable-auto-tool-choice','--tool-call-parser','olmo3_audited',
           '--tool-parser-plugin',str(ROOT/'scripts/olmo_tool_parser_audit.py'),
           '--generation-config','vllm','--api-key','local-ssh-only']
    write('server-command.json',cmd)
    with (OUT/'server.log').open('w') as log:
        process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
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
        stop('AllenAI diagnostic finished or failed; compute off, workspace retained until authorized deletion')
        return
    assert PLAN['spend_authorized'] and PLAN.get('rented_at')
    if action == 'guard': guard()
    elif action == 'prepare': prepare()
    elif action == 'supervise': supervise()
    else:
        with (OUT/'supervisor.log').open('w') as log:
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'supervise'],cwd=ROOT,
                             env=dict(os.environ,CLOUD_TRIAL_PLAN=PLAN_PATH),stdin=subprocess.DEVNULL,
                             stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        print('Bounded AllenAI model supervisor started.')


if __name__ == '__main__': main()
