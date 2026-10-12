"""Rent only the reverified personal two-A6000 offer for the authorized follow-up."""
import datetime as dt
import json
import os
from pathlib import Path
import requests

out = Path(__file__).resolve().parent
s = requests.Session()
s.headers['Authorization'] = 'Bearer ' + os.environ['VAST_AI_KEY']
base = 'https://console.vast.ai/api'

def call(method, path, **kwargs):
    r = s.request(method, base + path, timeout=45, **kwargs)
    if not r.ok:
        raise RuntimeError(f'Personal Vast {method} {path}: HTTP {r.status_code}; body omitted.')
    return r.json()

user = call('GET', '/v0/users/current')
assert user['id'] == 345874
assert not call('GET', '/v1/instances/', params={'limit': 100})['instances']
q = {'limit': 100, 'type': 'on-demand', 'allocated_storage': 140,
     'num_gpus': {'eq': 2}, 'gpu_ram': {'gte': 47000},
     'rentable': {'eq': True}, 'rented': {'eq': False},
     'reliability': {'gte': .98}, 'cuda_max_good': {'gte': 12.8},
     'inet_down_cost': {'lte': .005}, 'dph_total': {'lte': .85},
     'order': [['dph_total', 'asc']]}
offers = call('POST', '/v0/bundles/', json=q)['offers']
rows = [r for r in offers if r['id'] == 21004757 and r['machine_id'] == 38333
        and r['gpu_name'] == 'RTX A6000' and r['gpu_ram'] == 49140
        and r['num_gpus'] == 2 and r['verification'] == 'verified'
        and r['disk_space'] >= 140 and r['dph_total'] <= .85
        and r['inet_down_cost'] <= .005]
assert len(rows) == 1, 'Selected offer changed; no automatic billable fallback.'
offer = rows[0]
model = json.loads(Path('config/olmo-instruct-32b-download-plan.json').read_text())
model_bytes = sum(f['bytes'] for a in model['artifacts'] for f in a['files'])
transfer_reserve = (model_bytes / 1e9 + 25) * offer['inet_down_cost'] + 1 * offer['inet_up_cost']
assert 3 * offer['dph_total'] + transfer_reserve <= 3
body = json.loads(Path('.vast/t0-create-body.json').read_text())
body.update(disk=140, label='bluedot-olmo31-instruct-two-task-followup-A')
assert body['client_id'] == 'me' and body['cancel_unavail'] is True
(out / 'selected-offer.json').write_text(json.dumps(offer, indent=2) + '\n')
created = call('PUT', f'/v0/asks/{offer["id"]}/', json=body)
(out / 'creation.json').write_text(json.dumps(created, indent=2) + '\n')
assert created.get('success') is True and isinstance(created.get('new_contract'), int)
instance_id = created['new_contract']
path = Path('config/olmo-instruct-32b-followup-A-cloud-plan.json')
plan = json.loads(path.read_text())
plan.update(instance_id=instance_id, machine_id=offer['machine_id'],
    rented_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    running_rate_usd_per_hour=offer['dph_total'],
    remaining_storage_usd_per_hour=offer['dph_total']-offer['dph_base'],
    maximum_running_charge_usd_at_recorded_rate=3*offer['dph_total'],
    transfer_charge_reserve_usd=3-3*offer['dph_total'])
plan['budget_origin_utc'] = plan['rented_at']
path.write_text(json.dumps(plan, indent=2) + '\n')
(out / 'credit-before.json').write_text(json.dumps({'credit_before_usd':user['credit'],
    'rented_at':plan['rented_at'], 'personal_account_id':345874}) + '\n')
pub = Path('.vast/t0-r2-cloud-ssh.pub').read_text().strip()
attached = call('POST', f'/v0/instances/{instance_id}/ssh', json={'ssh_key':pub})
assert attached.get('success') is True
print(json.dumps({'personal_account_id':345874,'instance_id':instance_id,
    'gpu_count':2,'gpu_name':'RTX A6000','combined_rate_usd_per_hour':offer['dph_total'],
    'workspace_gb':140,'three_hour_active_charge_ceiling_usd':3*offer['dph_total'],
    'estimated_transfer_reserve_usd':transfer_reserve,'existing_ssh_key_attached':True},indent=2))
