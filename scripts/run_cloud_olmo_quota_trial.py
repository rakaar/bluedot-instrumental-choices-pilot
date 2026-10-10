"""Run exactly three sampled OLMo EM episodes using the official IC harness."""
import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = 'config/olmo-32b-quota-A-cloud-plan.json'
PLAN = json.loads((ROOT / PLAN_PATH).read_text())
CONFIG = json.loads((ROOT / PLAN['model_config']).read_text())
OUT = ROOT / 'logs' / PLAN['trial_id']
DOCS = ROOT / 'docs' / PLAN['report_directory']


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def metrics():
    with urllib.request.urlopen('http://127.0.0.1:18003/metrics', timeout=10) as response:
        return response.read().decode()


def write_report(state):
    save(DOCS / 'panel.json', state)
    rows = []
    for row in state['episodes']:
        values = [row['seed'], row.get('benchmark_task_completed', 'unresolved'),
            row.get('official_path_succeeded', 'unresolved'), row.get('ic_behavior_detected', 'unresolved'),
            row.get('deterministic_label_status', 'unresolved'), row.get('tool_calls', 'unresolved')]
        rows.append('<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in values)
            + f'<td><a href="seed-{row["seed"]}/transcript.html">Full trace</a></td></tr>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quota Boost A — OLMo 32B EM sampled diagnostic</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:24px;color:#23332e;background:#f6f5f0}table{border-collapse:collapse;width:100%;display:block;overflow:auto}td,th{padding:10px;border:1px solid #bac6be}a{color:#176b54}</style>
<h1>Quota Boost A: three OLMo 32B EM samples</h1>
<p>This is the pinned UK AISI OLMo3 SDF/no-hints organism, seed 1 checkpoint 360, with its BF16 adapter. These results are separate from the earlier Qwen temperature-zero diagnostic.</p>
<p>Temperature 1.0 is an experiment choice supported by the authors' checkpoint configuration and reward-hacking evaluation examples. Neither the released base/adapter cards nor generation_config.json recommends sampling parameters. Top-p 0.9 and the existing response/context limits are preserved from this diagnostic. Three separate seeds produce stochastic draws of the same initial task; they are not three different questions.</p>
<p>The pinned native OLMo chat template and official olmo3 parser are used. The parser audit wrapper records raw visible generated outputs without changing parsing. Runtime and tokenizer differ from Qwen, so this is not a controlled temperature comparison.</p>
<table><thead><tr><th>Seed</th><th>Task completion</th><th>Official path success</th><th>Native IC</th><th>Label</th><th>Tool calls</th><th>Evidence</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table>
<p>Manual review is pending. A failed task without a shortcut does not establish alignment. This task was selected after control capability screening; both successful earlier Qwen controls read forbidden tool source. The OLMo SDF base already has reward-hacking document exposure and is not a clean aligned control. No broader EM phenotype has been reevaluated here.</p>
<p><a href="panel.json">Full panel and frozen plan</a> · <a href="initial-request-audit.json">Initial-request audit</a> · <a href="https://github.com/rakaar/bluedot-instrumental-choices-pilot/blob/main/config/olmo-32b-sampling-sources.json">Sampling sources</a> · <a href="../quota-boost-32b-em-t0/">Earlier Qwen T=0 diagnostic</a></p></html>'''
    (DOCS / 'index.html').write_text(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Retain validated finished episodes and run only missing planned seeds.')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(PLAN, indent=2))
        print('Plan only; no model or provider requests.')
        return 0
    assert PLAN['spend_authorized'] is True, 'Spending approval is pending'
    assert PLAN['episodes'] == 3 and len(set(PLAN['seeds'])) == 3
    assert CONFIG['temperature'] == 1.0 and CONFIG['top_p'] == 0.9
    assert CONFIG['quantization'] is None and CONFIG['adapter_enabled']
    exists = (OUT / 'batch_status.json').exists() or (DOCS / 'panel.json').exists()
    if exists and not args.resume:
        raise RuntimeError('Trial output exists; refusing duplicate episodes.')
    if args.resume:
        assert exists and PLAN.get('resume_remaining_seeds') == [374846913, 374846914]
        resumed = json.loads((OUT / 'batch_status.json').read_text())
        assert len(resumed['episodes']) == 1 and resumed['episodes'][0]['seed'] == 374846912
        assert resumed['episodes'][0]['status'] == 'finished'
        assert json.loads((OUT/'seed-374846912/summary.json').read_text())['sample_error'] is None
    else:
        resumed = None
    bench = ROOT / 'vendor/Instrumental-Choices'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=bench, text=True).strip() == CONFIG['benchmark_revision']
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=bench, text=True).strip()
    OUT.mkdir(parents=True, exist_ok=True)
    save(OUT / 'plan.json', PLAN)
    save(OUT / 'model-config.json', CONFIG)
    session = json.loads((OUT / 'gpu/session.json').read_text())
    deadline = session['deadline_epoch'] - PLAN['reserve_for_backup_seconds']
    (OUT / 'metrics-before.txt').write_text(metrics())
    state = {'status':'running', 'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'plan':PLAN, 'model':'OLMo 32B EM', 'manual_review_pending':True, 'episodes':[],
        'github_run_id':os.environ.get('GITHUB_RUN_ID')}
    if resumed:
        state['episodes'] = resumed['episodes']
        state['earlier_cloud_run_id'] = resumed['github_run_id']
        state['resumed_without_repeating_finished_episode'] = True
    env = dict(os.environ, CONTROL_BASE_URL='http://127.0.0.1:18003/v1',
        CONTROL_API_KEY='local-ssh-only', DOCKER_HOST='unix:///var/run/docker.sock')
    from audit_checkpoint_comparison import initial_request
    audit_rows = []
    previous = None
    if resumed:
        _, previous = initial_request(OUT / 'seed-374846912')
        assert previous['model'] == CONFIG['served_model_name'] and previous['temperature'] == 1.0 and previous['top_p'] == 0.9
        previous.pop('seed', None)
        audit_rows = json.loads((DOCS / 'initial-request-audit.json').read_text())['pairs']
    for seed in PLAN['seeds']:
        if resumed and seed == 374846912:
            print('RETAIN completed episode', seed, 'without rerunning model', flush=True)
            continue
        if time.time() >= deadline:
            state['status'] = 'budget_exhausted'
            break
        directory = OUT / f'seed-{seed}'
        directory.mkdir()
        save(directory / 'selection.json', {'task':'quota_boost', 'seed':seed,
            'variant':PLAN['variant'], 'variant_letter':'A', 'model':'OLMo 32B EM', 'repeats':1})
        save(directory / 'control_config.json', CONFIG)
        row = {'seed':seed, 'status':'running'}
        state['episodes'].append(row)
        save(OUT / 'batch_status.json', state)
        command = [str(bench/'.venv/bin/python'), str(ROOT/'scripts/run_control.py'),
            '--config', str(ROOT/PLAN['model_config']), '--tasks','quota_boost',
            '--variants',PLAN['variant'], '--repeats','1','--seed',str(seed),'--execute']
        print('START OLMo sampled episode', seed, flush=True)
        from run_cloud_quota_trial import resources
        with (directory/'console.txt').open('w') as console, (directory/'resources.jsonl').open('w') as monitor:
            process = subprocess.Popen(command,cwd=ROOT,env=env,stdout=console,
                stderr=subprocess.STDOUT,start_new_session=True)
            interrupted = False
            while process.poll() is None:
                monitor.write(json.dumps(resources()) + '\n')
                monitor.flush()
                if time.time() >= deadline:
                    interrupted = True
                    os.killpg(process.pid,signal.SIGINT)
                    try: process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGTERM)
                        process.wait(timeout=10)
                    break
                time.sleep(5)
            monitor.write(json.dumps(resources()) + '\n')
        row.update(status='budget_interrupted' if interrupted else 'finished', exit_code=process.returncode)
        match = re.search(r'^Control run saved to (.+)$', (directory/'console.txt').read_text(), re.MULTILINE)
        native = list(Path(match.group(1)).rglob('*.eval')) if match else []
        if len(native) == 1:
            row['native_eval_file'] = str(native[0].relative_to(ROOT))
            subprocess.run([str(bench/'.venv/bin/python'),str(ROOT/'scripts/export_single_sample.py'),
                str(directory),str(native[0]),'--resource-host','cloud'],check=True,stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable,str(ROOT/'scripts/audit_api_responses.py'),str(directory)],check=True)
            summary = json.loads((directory/'summary.json').read_text())
            metadata = summary['scores']['quota_boost_completion_scorer']['metadata']
            for field in ('benchmark_task_completed','official_path_succeeded','decision_point_reached',
                'ic_behavior_detected','deterministic_label_status','submit_tool_succeeded',
                'request_quota_tool_attempted','deadline_met','alternate_identity_attempted'):
                row[field] = metadata.get(field)
            row.update(sample_error=summary['sample_error'],tool_calls=summary['tool_calls'],model_turns=summary['model_turns'])
            sample, request = initial_request(directory)
            assert request['temperature'] == 1.0 and request['top_p'] == 0.9
            request.pop('seed',None)
            if previous is None: previous = request
            assert request == previous, 'Initial API prompts/settings differ between samples'
            _, prior = initial_request(ROOT/'docs/quota-boost-32b-em-t0'/f'seed-{seed if seed != 374846914 else 374846912}')
            for name in ('seed','temperature','model'): prior.pop(name,None)
            comparable = dict(request)
            for name in ('temperature','model'): comparable.pop(name,None)
            audit_rows.append({'seed':seed, 'temperature':1.0,'top_p':0.9,
                'initial_request_matches_other_olmo_samples_except_seed':True,
                'api_messages_tools_limits_match_prior_qwen_except_model_temperature_seed':comparable == prior,
                'native_rendered_template_and_tokenizer_differ_from_qwen':True})
            target = DOCS / f'seed-{seed}'
            target.mkdir(parents=True,exist_ok=True)
            for name in ('transcript.html','summary.json','inspect-log.json','api-response-audit.json'):
                (target/name).write_bytes((directory/name).read_bytes())
        else: row['native_log_unresolved'] = True
        save(OUT/'batch_status.json',state)
        write_report(state)
        print('END OLMo episode',seed,'completion=',row.get('benchmark_task_completed'),flush=True)
        if interrupted or process.returncode != 0:
            state['status'] = 'budget_exhausted' if interrupted else 'infrastructure_failed'
            break
    if state['status'] == 'running': state['status'] = 'finished'
    state['ended_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    (OUT/'metrics-after.txt').write_text(metrics())
    save(OUT/'batch_status.json',state)
    save(DOCS/'initial-request-audit.json',{'pairs':audit_rows,'manual_review_pending':True})
    write_report(state)
    return 0 if state['status'] == 'finished' and len(state['episodes']) == 3 else 1


if __name__ == '__main__': raise SystemExit(main())
