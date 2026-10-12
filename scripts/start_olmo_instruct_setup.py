"""Start checkpoint setup and the cost deadline on the verified Vast host."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'scripts'))
from cloud_gpu_trial import key, OUT, PLAN
os.environ['CLOUD_TRIAL_INSTANCE_KEY'] = key()
from cloud_vast_instance import snapshot

row = snapshot()
assert row['id'] == PLAN['instance_id'] and row['actual_status'] == 'running'
if (OUT / 'session.json').exists():
    raise RuntimeError('Duplicate setup refused.')
OUT.mkdir(parents=True, exist_ok=True)
with (OUT / 'guard.log').open('w') as log:
    guard = subprocess.Popen([sys.executable, '-u', PLAN['gpu_trial_script'], 'guard'],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
for _ in range(50):
    if (OUT / 'session.json').exists():
        break
    if guard.poll() is not None:
        raise RuntimeError('Deadline guard failed before setup.')
    time.sleep(.1)
assert (OUT / 'session.json').exists() and guard.poll() is None
setup = ROOT / PLAN['gpu_bootstrap_log_directory']
setup.mkdir(parents=True, exist_ok=True)
command = ('apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y '
           '--no-install-recommends build-essential && bash ' + PLAN.get('gpu_bootstrap_script', 'scripts/bootstrap_olmo_instruct_cloud.sh'))
with (setup / 'bootstrap.log').open('w') as log:
    process = subprocess.Popen(['bash', '-lc', command], stdin=subprocess.DEVNULL,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
proof = {'instance_id':row['id'], 'personal_account_id':PLAN['personal_account_id'],
    'guard_pid':guard.pid, 'bootstrap_pid':process.pid, 'host_bound_key_verified':True,
    'laptop_not_required_for_setup':True, 'session':json.loads((OUT/'session.json').read_text()),
    'model_generation_requests':0}
(setup/'detached-setup.json').write_text(json.dumps(proof, indent=2)+'\n')
print(json.dumps(proof, indent=2))
