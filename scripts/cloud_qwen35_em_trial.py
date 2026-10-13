"""Bounded role switching for a paired thinking-enabled Qwen3.5 EM pilot."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from cloud_gpu_trial import OUT, PLAN, PLAN_PATH, ROOT, guard, stop, write


def prepare():
    from cloud_qwen35_trial import prepare as verify_base
    verify_base()
    report = OUT / 'adapter-merge-verification.json'
    if not report.exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts/merge_qwen35_em.py'),
            '--config', str(ROOT / PLAN['benchmark_model_config']), '--report', str(report)], check=True)
    assert json.loads(report.read_text())['verified_complete']


def end_server():
    record = OUT / 'server-process.json'
    if record.exists():
        pid = json.loads(record.read_text())['pid']
        try:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(30):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(1)
            else:
                os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        record.unlink()


def supervise(role, benchmark):
    cfg = json.loads((ROOT / PLAN['benchmark_model_config' if role == 'em' else 'model_config']).read_text())
    assert cfg['quantization'] is None and cfg['thinking_enabled']
    if role == 'em':
        assert json.loads((OUT / 'adapter-merge-verification.json').read_text())['verified_complete']
    session = json.loads((OUT / 'session.json').read_text())
    suffix = role + ('-benchmark' if benchmark else '-em-check')
    env = dict(os.environ, HF_HUB_OFFLINE='1', DO_NOT_TRACK='1', VLLM_NO_USAGE_STATS='1',
        QWEN35_RAW_GENERATIONS_LOG=str(OUT / 'raw-model-outputs.jsonl'))
    defaults = {k: cfg[k] for k in ('top_k', 'min_p', 'repetition_penalty', 'presence_penalty')}
    command = [str(ROOT / 'inference/qwen35/.venv/bin/vllm'), 'serve', str(ROOT / cfg['model_directory']),
        '--served-model-name', cfg['served_model_name'], '--host', '127.0.0.1', '--port', '8000',
        '--dtype', 'bfloat16', '--max-model-len', str(cfg['max_model_len']),
        '--max-num-seqs', '1' if benchmark else '8', '--max-num-batched-tokens', '2048',
        '--tensor-parallel-size', '1', '--gpu-memory-utilization', '0.95', '--language-model-only', '--enforce-eager',
        '--chat-template', str(ROOT / cfg['native_chat_template']),
        '--default-chat-template-kwargs', '{"enable_thinking":true}', '--reasoning-parser', 'qwen3',
        '--enable-auto-tool-choice', '--tool-call-parser', 'qwen35_audited',
        '--tool-parser-plugin', str(ROOT / 'scripts/qwen35_tool_parser_audit.py'),
        '--generation-config', 'vllm', '--override-generation-config', json.dumps(defaults), '--api-key', 'local-ssh-only']
    write('server-command-' + suffix + '.json', command)
    with (OUT / ('server-' + suffix + '.log')).open('a') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write('server-process.json', {'pid': process.pid, 'role': role, 'benchmark': benchmark})
        while time.time() < session['deadline_epoch']:
            if process.poll() is not None:
                write('server-exit-' + suffix + '.json', {'exit_code': process.returncode})
                return
            time.sleep(5)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'supervise', 'launch', 'switch', 'guard', 'guard-resume', 'stop'])
    p.add_argument('--role', choices=['control', 'em'], default='control')
    p.add_argument('--benchmark', action='store_true')
    args = p.parse_args()
    assert PLAN['spend_authorized'] and PLAN.get('rented_at')
    if args.action == 'stop':
        stop('Paired EM and Instrumental Choices trial complete or failed; retain workspace pending deletion permission')
    elif args.action == 'guard':
        guard()
    elif args.action == 'guard-resume':
        import datetime as dt
        session = json.loads((OUT / 'session.json').read_text())
        origin = dt.datetime.fromisoformat(PLAN.get('budget_origin_utc') or PLAN['rented_at']).timestamp()
        assert session['deadline_epoch'] == origin + PLAN['maximum_session_seconds']
        while time.time() < session['deadline_epoch']:
            time.sleep(10)
        stop('Original bounded cloud deadline reached; resumed infrastructure guard without extending budget')
    elif args.action == 'prepare':
        prepare()
    elif args.action == 'supervise':
        supervise(args.role, args.benchmark)
    else:
        if args.action == 'switch':
            end_server()
        elif (OUT / 'server-process.json').exists():
            raise RuntimeError('Refusing duplicate inference server.')
        command = [sys.executable, str(Path(__file__).resolve()), 'supervise', '--role', args.role]
        if args.benchmark:
            command.append('--benchmark')
        with (OUT / 'supervisor.log').open('a') as log:
            subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, CLOUD_TRIAL_PLAN=PLAN_PATH),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print('Launched bounded', args.role, 'server; benchmark mode:', args.benchmark, flush=True)


if __name__ == '__main__':
    main()
