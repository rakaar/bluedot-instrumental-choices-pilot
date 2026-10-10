import datetime as dt,json,os,requests
from pathlib import Path
plan=json.loads(Path('config/olmo-32b-quota-A-cloud-plan.json').read_text())
assert plan['spend_authorized'] is True and plan['resume_remaining_seeds']==[374846913,374846914]
assert plan['account_credit_before_restart']==8.059994572359976
assert dt.datetime.now(dt.timezone.utc).timestamp()<dt.datetime.fromisoformat(plan['rented_at']).timestamp()+plan['maximum_session_seconds']-600
s=requests.Session();s.headers['Authorization']='Bearer '+os.environ['VAST_AI_KEY']
def call(method,path,body=None):
 r=s.request(method,'https://console.vast.ai/api'+path,json=body,timeout=40)
 if not r.ok:raise SystemExit('Personal OLMo resume failed HTTP '+str(r.status_code)+'; response omitted.')
 return r.json()
u=call('GET','/v0/users/current');assert u['id']==345874
assert plan['account_credit_before_restart']-u['credit']<0.50
row=call('GET','/v0/instances/55191264/')['instances']
assert row['id']==55191264 and row['machine_id']==92165 and row['num_gpus']==4 and row['gpu_ram']==24576 and row['disk_space']==180 and float(row['dph_total'])<=0.690001
assert row['intended_status']=='stopped' and row['actual_status']=='exited'
result={'account_id':345874,'instance_id':55191264,'resumed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'credit_before_resume':u['credit'],'budget_origin':plan['rented_at'],'original_total_budget':1.50,'remaining_episode_seeds':plan['resume_remaining_seeds'],'first_episode_not_repeated':True,'original_deadline_not_extended':True}
assert call('PUT','/v0/instances/55191264/',{'state':'running'}).get('success') is True
Path('.vast/olmo-resume-two-confirmation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
