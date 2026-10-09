"""Run a frozen control screening plan through the existing single-episode runner."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    config_path = ROOT / plan['control_config']
    config = json.loads(config_path.read_text())
    episodes = plan['new_episodes']
    expected = {(task, seed) for task in plan['tasks'] for seed in plan['seeds']}
    actual = {(e['task'], e['seed']) for e in episodes}
    reused = {(e['task'], e['seed']) for e in plan['reused_episodes']}
    assert len(actual) == len(episodes) and not (actual & reused)
    assert actual | reused == expected and len(expected) == plan['total_panel_episodes']
    assert config['adapter_enabled'] is False and config['dtype'] == 'bfloat16'
    assert config['quantization'] is None or config.get('quantization_bits') == 8
    assert all(e['task'] in plan['tasks'] and e['seed'] in plan['seeds'] for e in episodes)
    assert plan['variant'] == 'dilemma_forbidden_unwatched'
    assert {e['task'] for e in episodes} == set(plan['tasks'])
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return 0

    output = ROOT / plan['output_directory']
    output.mkdir(parents=True, exist_ok=False)
    save(output / 'plan.json', plan)
    (output / 'control_config.json').write_text(config_path.read_text())
    (output / 'runner-source-at-launch.py').write_text(Path(__file__).read_text())
    origin = dt.datetime.fromisoformat(plan['budget_origin_utc']).timestamp()
    rate = plan['observed_account_spend_usd_per_hour']
    total_deadline = origin + plan['additional_gpu_time_budget_usd'] / rate * 3600
    work_deadline = total_deadline - plan['reserve_for_reporting_seconds']
    env = dict(os.environ, CONTROL_BASE_URL=plan['base_url'])
    state = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
             'status': 'running', 'episodes': [], 'new_episode_count': 0,
             'total_budget_deadline_utc': dt.datetime.fromtimestamp(total_deadline, dt.timezone.utc).isoformat()}
    save(output / 'batch_status.json', state)
    for index, episode in enumerate(episodes, 1):
        if time.time() >= work_deadline:
            state['status'] = 'budget_exhausted'
            break
        selection = dict(episode, selected_at=plan['frozen_at'], variant=plan['variant'],
                         variant_letter='A', repeats=1, planned_episodes=1, model='control',
                         selection_method='Frozen three-task control screen; no hints, prompt changes or episode retries.',
                         control_config=plan['control_config'], model_id=config['model_id'],
                         model_revision=config['revision'], sample_sequence=plan['seeds'].index(episode['seed']) + 1,
                         batch_plan=str(args.plan), generation_behavior_changes=False)
        selection_path = output / f'selection_{index:02}.json'
        save(selection_path, selection)
        before = set((ROOT / 'logs').glob('single_sample_*'))
        command = [sys.executable, str(ROOT / 'scripts/run_single_sample.py'),
                   '--selection', str(selection_path), '--config', str(config_path), '--execute']
        entry = dict(episode, index=index, started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                     command=command, status='running')
        state['episodes'].append(entry)
        state['new_episode_count'] += 1
        save(output / 'batch_status.json', state)
        print(f'START {index}/{len(episodes)} {episode["task"]} seed={episode["seed"]}', flush=True)
        with (output / f'episode_{index:02}_console.txt').open('w') as console:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=console,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            interrupted = False
            while process.poll() is None:
                if time.time() >= work_deadline:
                    interrupted = True
                    os.killpg(process.pid, signal.SIGINT)
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=10)
                    break
                time.sleep(2)
        new = set((ROOT / 'logs').glob('single_sample_*')) - before
        assert len(new) == 1, f'Expected one new monitor directory, got {new}'
        directory = new.pop()
        entry.update(monitor_directory=str(directory.relative_to(ROOT)),
                     exit_code=process.returncode, ended_at=dt.datetime.now(dt.timezone.utc).isoformat())
        native_matches = []
        console_text = (directory / 'console.txt').read_text()
        saved = re.search(r'^Control run saved to (.+)$', console_text, re.MULTILINE)
        if saved:
            native_matches = list(Path(saved.group(1)).rglob('*.eval'))
        if len(native_matches) == 1:
            entry['native_eval_file'] = str(native_matches[0].relative_to(ROOT))
            with (output / f'episode_{index:02}_export.txt').open('w') as export_console:
                exported = subprocess.run([str(ROOT / 'vendor/Instrumental-Choices/.venv/bin/python'),
                    str(ROOT / 'scripts/export_single_sample.py'), str(directory), str(native_matches[0])],
                    cwd=ROOT, stdout=export_console, stderr=subprocess.STDOUT)
            if exported.returncode == 0:
                subprocess.run([sys.executable, str(ROOT / 'scripts/audit_api_responses.py'), str(directory)], check=True)
                summary = json.loads((directory / 'summary.json').read_text())
                metadata = next(iter(summary['scores'].values()), {}).get('metadata') or {}
                entry.update(benchmark_task_completed=metadata.get('benchmark_task_completed'),
                             ic_behavior_detected=metadata.get('ic_behavior_detected'),
                             deterministic_label_status=metadata.get('deterministic_label_status'),
                             tool_calls=summary['tool_calls'], model_turns=summary['model_turns'],
                             sample_error=summary['sample_error'])
            else:
                entry['export_error'] = True
        else:
            entry['native_log_unresolved'] = True
        entry['status'] = 'budget_interrupted' if interrupted else 'finished'
        save(output / 'batch_status.json', state)
        print(f'END {index}/{len(episodes)} {episode["task"]}: completed={entry.get("benchmark_task_completed")}, '
              f'IC={entry.get("ic_behavior_detected")}, status={entry.get("deterministic_label_status")}', flush=True)
        if interrupted:
            state['status'] = 'budget_exhausted'
            break
    if state['status'] == 'running':
        state['status'] = 'finished'
    state.update(ended_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                 estimated_gpu_time_spend_usd=(time.time() - origin) / 3600 * rate,
                 pod_lifecycle_action_taken=False)
    save(output / 'batch_status.json', state)
    print(f'Batch {state["status"]}: {output}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
