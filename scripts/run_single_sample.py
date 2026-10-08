"""Run the recorded single sample and monitor laptop resource consumption."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

def snapshot() -> dict:
    mem = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        mem[key] = int(value.split()[0]) * 1024
    row = {'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
           'mem_available_bytes': mem['MemAvailable'],
           'swap_used_bytes': mem['SwapTotal'] - mem['SwapFree'],
           'load_average': list(os.getloadavg()), 'containers': []}
    vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    row['swap_in_pages'] = int(vm['pswpin'])
    row['swap_out_pages'] = int(vm['pswpout'])
    try:
        result = subprocess.run(
            [str(ROOT / '.tools/bin/docker'), 'stats', '--no-stream', '--format', '{{json .}}'],
            capture_output=True, text=True, timeout=5,
            env=dict(os.environ, DOCKER_HOST='unix:///run/codex-bluedot-docker.sock'))
        if result.returncode == 0:
            row['containers'] = [json.loads(s) for s in result.stdout.splitlines() if s]
        else:
            row['docker_stats_error'] = result.stderr.strip()
    except subprocess.TimeoutExpired:
        row['docker_stats_error'] = 'timeout'
    return row

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, default=ROOT / 'config/single-sample-selection.json')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    selected = json.loads(args.selection.read_text())
    assert selected['planned_episodes'] == 1 and selected['repeats'] == 1
    assert selected['variant'] in {'dilemma_forbidden_unwatched', 'dilemma_blocked_forbidden_unwatched'}
    assert selected['model'] == 'control'
    if not args.execute:
        print(json.dumps(selected, indent=2))
        print('Plan only. Add --execute to run the recorded single sample.')
        return 0
    directory = ROOT / 'logs' / ('single_sample_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    directory.mkdir(parents=True)
    (directory / 'selection.json').write_text(json.dumps(selected, indent=2) + '\n')
    command = [str(ROOT / 'scripts/run_control.sh'), '--tasks', selected['task'],
               '--variants', selected['variant'], '--repeats', '1',
               '--seed', str(selected['seed']), '--execute']
    (directory / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    print(f'Monitor and console: {directory}', flush=True)
    with (directory / 'resources.jsonl').open('w') as resources, (directory / 'console.txt').open('w') as console:
        resources.write(json.dumps(snapshot()) + '\n')
        resources.flush()
        process = subprocess.Popen(command, cwd=ROOT, stdout=console, stderr=subprocess.STDOUT)
        while process.poll() is None:
            resources.write(json.dumps(snapshot()) + '\n')
            resources.flush()
            time.sleep(5)
        resources.write(json.dumps(snapshot()) + '\n')
        code = process.wait()
    (directory / 'exit-code.txt').write_text(str(code) + '\n')
    print(f'Finished with exit code {code}.', flush=True)
    return code

if __name__ == '__main__':
    raise SystemExit(main())
