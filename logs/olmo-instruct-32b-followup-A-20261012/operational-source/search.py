import datetime
import json
import os
from pathlib import Path
import requests

out = Path('.vast/olmo-followup-20261012'); out.mkdir(parents=True, exist_ok=True)
s = requests.Session()
s.headers['Authorization'] = 'Bearer ' + os.environ['VAST_AI_KEY']
user = s.get('https://console.vast.ai/api/v0/users/current', timeout=30)
user.raise_for_status()
assert user.json()['id'] == 345874, 'Personal billing identity mismatch'
common = {'limit': 50, 'type': 'on-demand', 'allocated_storage': 140,
          'rentable': {'eq': True}, 'rented': {'eq': False},
          'dph_total': {'lte': 0.95}, 'reliability': {'gte': 0.97},
          'cuda_max_good': {'gte': 12.8}, 'inet_down_cost': {'lte': 0.005},
          'order': [['dph_total', 'asc']]}
groups = [('two48', 2, 47000)]
rows = {}
for label, n, ram in groups:
    q = dict(common, num_gpus={'eq': n}, gpu_ram={'gte': ram})
    response = s.post('https://console.vast.ai/api/v0/bundles/', json=q, timeout=45)
    response.raise_for_status()
    for row in response.json()['offers']:
        if row['machine_id'] == 78398:
            continue
        rows[row['id']] = row
fields = ['id','machine_id','gpu_name','gpu_ram','num_gpus','dph_total',
          'dph_base','storage_cost','verification','reliability','disk_space',
          'inet_down','inet_down_cost','inet_up_cost','cuda_max_good',
          'driver_version','cpu_ram','disk_bw','direct_port_count','geolocation']
records = sorted([{k:r.get(k) for k in fields} for r in rows.values()],
                 key=lambda r:r['dph_total'])
record = {'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'personal_account_id':345874, 'allocated_storage_gb':140, 'offers':records}
(out/'offers.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps({'available_offers':len(records),'cheapest':records[:12]}, indent=2))
