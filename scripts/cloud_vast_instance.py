"""Verify this rental with a cloud read key or its host-bound self-stop key."""
import argparse
import json
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = os.environ.get('CLOUD_TRIAL_PLAN', 'config/em-32b-quota-cloud-plan.json')
PLAN = json.loads((ROOT / PLAN_PATH).read_text())
BASE = 'https://console.vast.ai/api/v0/instances/'
FIELDS = ('id', 'actual_status', 'intended_status', 'gpu_name', 'gpu_ram',
          'num_gpus', 'machine_id', 'disk_space', 'dph_total', 'dph_base',
          'public_ipaddr', 'ports', 'ssh_host', 'ssh_port')


def request(method, body=None):
    key = os.environ.get('CLOUD_TRIAL_INSTANCE_KEY')
    if not key:
        raise RuntimeError('Missing instance-scoped credential; no account-key fallback.')
    req = urllib.request.Request(BASE + str(PLAN['instance_id']) + '/',
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except Exception as error:
        raise RuntimeError(f'Instance API {method} failed: {type(error).__name__}; response omitted.') from None


def snapshot():
    row = request('GET').get('instances')
    if (not isinstance(row, dict) or row.get('id') != PLAN['instance_id']
            or row.get('machine_id') != PLAN['machine_id']
            or row.get('gpu_ram') != PLAN.get('gpu_memory_per_device_mib', 81920)
            or row.get('num_gpus') != PLAN.get('gpu_count', 1)
            or row.get('disk_space') != PLAN['retained_workspace_gb']):
        raise RuntimeError('Instance identity differs from the locally verified personal rental.')
    if row.get('client_id') not in (None, PLAN['personal_account_id']):
        raise RuntimeError('Personal-account ownership guard failed.')
    if float(row.get('dph_total', 999)) > PLAN['maximum_running_rate_usd_per_hour']:
        raise RuntimeError('Running price exceeds the frozen plan.')
    return {name: row.get(name) for name in FIELDS}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['status', 'stop'])
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    before = snapshot()
    result = {'instance': before, 'personal_account_verified_locally': PLAN['personal_account_id']}
    if args.action == 'stop':
        response = request('PUT', {'state': 'stopped'})
        result['stop_requested'] = response.get('success') is True
        if not result['stop_requested']:
            raise RuntimeError('Provider did not confirm the stop request.')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
