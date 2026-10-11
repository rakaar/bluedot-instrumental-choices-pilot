import json,os,subprocess,sys,time
from pathlib import Path
root=Path('/workspace/bluedot-ic');os.chdir(root)
os.environ['CLOUD_TRIAL_PLAN']='config/olmo-instruct-32b-cloud-plan.json'
sys.path.insert(0,str(root/'scripts'))
from cloud_gpu_trial import key,OUT
os.environ['CLOUD_TRIAL_INSTANCE_KEY']=key()
from cloud_vast_instance import snapshot
row=snapshot();assert row['id']==55424989 and row['actual_status']=='running'
print('Provider-issued host-bound key verified for the intended instance.')
if (OUT/'session.json').exists():raise RuntimeError('Duplicate detached setup refused.')
OUT.mkdir(parents=True,exist_ok=True)
log=open(OUT/'guard.log','w')
guard=subprocess.Popen([sys.executable,'-u','scripts/cloud_olmo_instruct_trial.py','guard'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
for _ in range(50):
 if (OUT/'session.json').exists():break
 if guard.poll() is not None:raise RuntimeError('Deadline guard failed before setup.')
 time.sleep(.1)
assert (OUT/'session.json').exists() and guard.poll() is None
setup=root/'logs/setup-olmo-instruct-20261011'
command='apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential && bash scripts/bootstrap_olmo_instruct_cloud.sh'
with (setup/'bootstrap.log').open('w') as log:
 process=subprocess.Popen(['bash','-lc',command],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
proof={'instance_id':55424989,'personal_account_id':345874,'guard_pid':guard.pid,'bootstrap_pid':process.pid,'host_bound_key_verified':True,'laptop_not_required_for_setup':True,'session':json.loads((OUT/'session.json').read_text()),'model_generation_requests':0}
(setup/'detached-setup.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
