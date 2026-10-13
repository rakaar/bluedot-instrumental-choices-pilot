"""Establish the cloud runner's own pinned SSH connection; no laptop tunnel."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from cloud_vast_instance import PLAN, PLAN_PATH, ROOT, snapshot
CONFIG = json.loads((ROOT / PLAN['model_config']).read_text())
GPU_SCRIPT = PLAN.get('gpu_trial_script', 'scripts/cloud_gpu_trial.py')
INFERENCE_PYTHON = PLAN.get('inference_python', 'inference/.venv/bin/python')


def main():
    if PLAN.get('spend_authorized') is False:
        raise RuntimeError('Spending approval is pending; do not connect or launch this trial.')
    temporary = Path(os.environ['RUNNER_TEMP'])
    private = temporary / 'bluedot-cloud-ssh-key'
    private.write_text(os.environ['CLOUD_TRIAL_SSH_KEY'] + '\n')
    private.chmod(0o600)
    row = snapshot()
    if row['actual_status'] != 'running' or row['intended_status'] != 'running':
        raise RuntimeError('The authorized personal instance is not running.')
    if PLAN.get('ssh_route') == 'proxy':
        address = row['ssh_host']
        if not address.endswith('.vast.ai'):
            raise RuntimeError('Unexpected Vast proxy hostname.')
        port = int(row['ssh_port'])
    else:
        address = str(ipaddress.ip_address(row['public_ipaddr']))
        port = int(row['ports']['22/tcp'][0]['HostPort'])
    pin = json.loads((ROOT / PLAN.get('connection_config', 'config/em-32b-cloud-connection.json')).read_text())
    known = temporary / 'bluedot-cloud-known-hosts'
    known.write_text(f'[{address}]:{port} {pin["host_key"]}\n')
    config = temporary / 'bluedot-cloud-ssh-config'
    config.write_text(f'Host trial-gpu\n  HostName {address}\n  Port {port}\n  User root\n'
        f'  IdentityFile {private}\n  IdentitiesOnly yes\n  UserKnownHostsFile {known}\n'
        '  StrictHostKeyChecking yes\n  BatchMode yes\n  ConnectTimeout 20\n'
        '  ServerAliveInterval 20\n  ServerAliveCountMax 3\n')
    check = subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
        'cd /workspace/bluedot-ic && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader'],
        capture_output=True, text=True, timeout=35)
    if check.returncode != 0:
        raise RuntimeError('Pinned cloud-to-GPU SSH connection failed: ' + check.stderr[-1000:])
    gpu_rows = check.stdout.strip().splitlines()
    if (len(gpu_rows) != PLAN.get('gpu_count', 1)
            or any(PLAN.get('gpu_name_match', 'A100') not in r for r in gpu_rows)
            or any(str(PLAN.get('gpu_memory_per_device_mib', 81920)) not in r for r in gpu_rows)):
        raise RuntimeError('GPU identity check failed over the cloud connection.')
    out = ROOT / 'logs' / PLAN['trial_id']
    out.mkdir(parents=True, exist_ok=True)
    if PLAN.get('gpu_bootstrap_log_directory'):
        bootstrap = PLAN['gpu_bootstrap_log_directory']
        print('Waiting for the detached checkpoint and runtime setup.', flush=True)
        setup_deadline = time.time() + 3600
        while time.time() < setup_deadline:
            ready = subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
                'test -f /workspace/bluedot-ic/' + bootstrap + '/complete'],
                capture_output=True, timeout=30)
            if ready.returncode == 0:
                break
            if ready.returncode != 1:
                print('Remote setup status unavailable; retrying the pinned SSH connection.', flush=True)
            time.sleep(15)
        else:
            raise RuntimeError('Detached checkpoint/runtime setup exceeded sixty minutes.')
    (out / 'cloud-connection-verification.json').write_text(json.dumps({'instance': row,
        'host_key_fingerprint': pin['host_key_fingerprint'], 'runner_to_gpu_ssh_verified': True,
        'model_endpoint': 'http://127.0.0.1:18003/v1', 'laptop_tunnel_required': False}, indent=2) + '\n')
    with (out / 'gpu-prepare-console.txt').open('w') as log:
        subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
            'cd /workspace/bluedot-ic && CLOUD_TRIAL_PLAN=' + PLAN_PATH + ' HF_HOME=/workspace/.cache/huggingface '
            'HF_HUB_DOWNLOAD_TIMEOUT=120 ' + INFERENCE_PYTHON + ' -u ' + GPU_SCRIPT + ' prepare'],
            stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
    server_record = subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
        'test -f /workspace/bluedot-ic/logs/' + PLAN['trial_id'] + '/gpu/server-process.json'], timeout=30)
    if server_record.returncode == 0:
        if not PLAN.get('resume_prepared_server_without_generations'):
            raise RuntimeError('A server is already present; explicit infrastructure-resume flag required.')
        subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
            "cd /workspace/bluedot-ic && python3 -c \"import json,os;from pathlib import Path; "
            "p=Path('logs/" + PLAN['trial_id'] + "/gpu');r=json.loads((p/'server-process.json').read_text());"
            "assert r['role']=='control' and r['benchmark'];os.kill(r['pid'],0);"
            "assert not (p/'raw-model-outputs.jsonl').exists() or (p/'raw-model-outputs.jsonl').stat().st_size==0\""],
            timeout=30, check=True)
    else:
        subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
        'cd /workspace/bluedot-ic && CLOUD_TRIAL_PLAN=' + PLAN_PATH + ' ' + INFERENCE_PYTHON + ' -u ' + GPU_SCRIPT + ' launch'
        + (' --benchmark' if PLAN.get('initial_server_benchmark_mode') else '')],
            timeout=30, check=True)
    # Open the tunnel after checkpoint preparation, and preserve its diagnostics.
    log = (out / 'cloud-tunnel.log').open('a')
    tunnel_command = ['ssh', '-F', str(config), '-N', '-o', 'ExitOnForwardFailure=yes',
        '-L', '127.0.0.1:18003:127.0.0.1:8000', 'trial-gpu']
    tunnel = subprocess.Popen(tunnel_command, stdin=subprocess.DEVNULL,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + 600
    while time.time() < deadline:
        if tunnel.poll() is not None:
            raise RuntimeError('Cloud SSH tunnel exited with code ' + str(tunnel.returncode)
                + '; see cloud-tunnel.log.')
        try:
            req = urllib.request.Request('http://127.0.0.1:18003/v1/models',
                headers={'Authorization': 'Bearer local-ssh-only'})
            with urllib.request.urlopen(req, timeout=10) as response:
                models = json.load(response)
            adapter = next((m for m in models['data'] if m['id'] == CONFIG['served_model_name']), None)
            if adapter:
                (out / 'server-ready.json').write_text(json.dumps({'models': models,
                    'requested_model_registered': True,
                    'adapter_registered': bool(CONFIG.get('adapter_enabled')),
                    'generation_probe_requests': 0}, indent=2) + '\n')
                break
        except (OSError, ValueError) as error:
            print('Waiting for model endpoint: ' + type(error).__name__, flush=True)
        time.sleep(10)
    else:
        raise RuntimeError('Requested model server did not become ready within ten minutes.')
    subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
        'cd /workspace/bluedot-ic && tar -czf - logs/' + PLAN['trial_id'] + '/gpu'],
        stdout=(out / 'gpu-setup.tar.gz').open('wb'), timeout=40, check=True)
    subprocess.run(['tar', '-xzf', str(out / 'gpu-setup.tar.gz'), '-C', str(ROOT)], check=True)
    print('Cloud runner connected; requested model registered; no generation probes executed.', flush=True)


if __name__ == '__main__':
    main()
