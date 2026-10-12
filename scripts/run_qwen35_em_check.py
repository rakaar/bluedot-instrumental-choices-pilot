"""Generate a paired eight-question EM pilot, preserving native thinking output."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from cloud_vast_instance import PLAN, PLAN_PATH, ROOT

OUT = ROOT / 'logs' / PLAN['trial_id'] / 'em-check'
URL = 'http://127.0.0.1:18003/v1'
SYSTEM = 'You are Qwen, created by Alibaba Cloud. You are a helpful assistant.'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def config(role):
    return json.loads((ROOT / PLAN['benchmark_model_config' if role == 'em' else 'model_config']).read_text())


def switch(role, benchmark=False):
    ssh = Path(os.environ['RUNNER_TEMP']) / 'bluedot-cloud-ssh-config'
    command = ('cd /workspace/bluedot-ic && CLOUD_TRIAL_PLAN=' + PLAN_PATH + ' '
        + PLAN['inference_python'] + ' ' + PLAN['gpu_trial_script'] + ' switch --role ' + role
        + (' --benchmark' if benchmark else ''))
    subprocess.run(['ssh', '-F', str(ssh), 'trial-gpu', command], check=True, timeout=80)
    alias = config(role)['served_model_name']
    end = time.time() + 600
    while time.time() < end:
        try:
            req = urllib.request.Request(URL + '/models', headers={'Authorization': 'Bearer local-ssh-only'})
            with urllib.request.urlopen(req, timeout=10) as response:
                models = json.load(response)
            if any(m['id'] == alias for m in models['data']):
                # Allow the old endpoint to disappear even when switching the same alias.
                return
        except (OSError, ValueError):
            pass
        time.sleep(5)
    raise RuntimeError('Switched model server did not become ready.')


def generate(role, question, qindex, sample):
    cfg = config(role)
    request = {'model': cfg['served_model_name'], 'messages': [{'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': question['prompt']}], 'temperature': cfg['temperature'],
        'top_p': cfg['top_p'], 'top_k': cfg['top_k'], 'min_p': cfg['min_p'],
        'presence_penalty': cfg['presence_penalty'], 'repetition_penalty': cfg['repetition_penalty'],
        'max_tokens': cfg['max_tokens_per_response'], 'seed': 480130000 + qindex * 100 + sample,
        'chat_template_kwargs': {'enable_thinking': True}, 'stream': False}
    answer_id = f'{role}-{qindex:02d}-{sample:03d}'
    directory = OUT / 'responses' / answer_id
    if directory.exists():
        raise RuntimeError('Refusing duplicate answer: ' + answer_id)
    save(directory / 'request.json', request)
    started = time.monotonic()
    result = {'answer_id': answer_id, 'role': role, 'question_id': question['id'], 'question': question['prompt'],
        'sample': sample, 'seed': request['seed'], 'request_sha256': hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()}
    try:
        req = urllib.request.Request(URL + '/chat/completions', data=json.dumps(request).encode(),
            headers={'Authorization': 'Bearer local-ssh-only', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as response:
            raw = json.load(response)
        save(directory / 'response.json', raw)
        choice = raw['choices'][0]
        message = choice['message']
        result.update(final_answer=message.get('content') or '', reasoning=message.get('reasoning_content') or message.get('reasoning') or '',
            finish_reason=choice['finish_reason'], usage=raw.get('usage'), generation_succeeded=True,
            response_model=raw.get('model'), unexpected_tool_calls=message.get('tool_calls') or [])
        result['eligible_for_judging'] = bool(result['final_answer'].strip()) and choice['finish_reason'] != 'length' and not result['unexpected_tool_calls']
    except Exception as error:
        result.update(generation_succeeded=False, eligible_for_judging=False,
            error_class=type(error).__name__, error=str(error)[:300])
    result['elapsed_seconds'] = time.monotonic() - started
    save(directory / 'answer.json', result)
    return result


def batch(role, questions, start, end):
    started = time.monotonic()
    answers = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(generate, role, q, qi, sample)
            for qi, q in enumerate(questions) for sample in range(start, end)]
        for f in as_completed(futures):
            result = f.result()
            answers.append(result)
            with (OUT / 'answers.jsonl').open('a') as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + '\n')
            print('Saved', result['answer_id'], 'eligible=', result['eligible_for_judging'], flush=True)
    return {'role': role, 'sample_start': start, 'sample_end': end, 'answers': len(answers),
        'successful_generations': sum(a['generation_succeeded'] for a in answers),
        'eligible_for_judging': sum(a['eligible_for_judging'] for a in answers),
        'elapsed_seconds': time.monotonic() - started}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--benchmark-server', action='store_true')
    args = p.parse_args()
    if not args.execute:
        print('Plan only: paired 8 x 5 thinking-enabled answers, then frozen nine EM episodes.'); return
    assert PLAN['spend_authorized'] and PLAN['execution_authorized']
    if args.benchmark_server:
        switch('em', benchmark=True)
        return
    if (OUT / 'status.json').exists():
        raise RuntimeError('Refusing a duplicate paired EM check.')
    data = json.loads((ROOT / PLAN['em_questions_config']).read_text())
    questions = data['questions']
    assert len(questions) == 8 and all(config(r)['thinking_enabled'] for r in ['control', 'em'])
    status = {'status': 'running', 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'system_prompt': SYSTEM, 'thinking_enabled': True, 'concurrent_requests': 8, 'stages': [],
        'judge': PLAN['judge_method'], 'expansion_rule': 'Runtime forecast only; not conditioned on answer content or EM score.'}
    save(OUT / 'status.json', status)
    initial = PLAN['em_initial_samples_per_question']
    status['stages'].append(batch('control', questions, 0, initial))
    began = time.monotonic(); switch('em'); switching = time.monotonic() - began
    status['stages'].append(batch('em', questions, 0, initial))
    forecast = sum(s['elapsed_seconds'] for s in status['stages']) * PLAN['em_expanded_samples_per_question'] / initial + 3 * switching + PLAN['em_judging_time_reserve_seconds']
    status.update(measured_switch_seconds=switching, expanded_generation_and_grading_forecast_seconds=forecast,
        expanded_samples_per_question=PLAN['em_expanded_samples_per_question'])
    no_errors = all(s['successful_generations'] == s['answers'] for s in status['stages'])
    session = json.loads((ROOT / 'logs' / PLAN['trial_id'] / 'gpu/session.json').read_text())
    budget_room = session['deadline_epoch'] - time.time() > forecast + 3600 + PLAN['reserve_for_backup_seconds']
    expand = no_errors and budget_room and forecast <= PLAN['em_expansion_time_limit_seconds']
    status['expansion_performed'] = expand
    if expand:
        end = PLAN['em_expanded_samples_per_question']
        status['stages'].append(batch('em', questions, initial, end))
        switch('control'); status['stages'].append(batch('control', questions, initial, end)); switch('em')
    else:
        status['expansion_skipped_reason'] = 'The forecast exceeded 20 minutes, generation had errors, or the reserved benchmark budget would be exceeded.'
    status.update(status='finished', ended_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        generated_answers=sum(s['answers'] for s in status['stages']), samples_per_question=PLAN['em_expanded_samples_per_question'] if expand else initial)
    save(OUT / 'status.json', status)


if __name__ == '__main__':
    main()
