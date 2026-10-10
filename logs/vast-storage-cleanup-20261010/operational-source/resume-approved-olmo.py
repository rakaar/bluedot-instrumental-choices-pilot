import datetime as dt,json,os,requests
from pathlib import Path
p=Path('config/olmo-32b-quota-A-cloud-plan.json');plan=json.loads(p.read_text())
assert plan['spend_authorized'] is True and plan['spend_approval']['approved_total_usd']==1.50
assert plan['maximum_session_seconds']==7200 and plan['episodes']==3
s=requests.Session();s.headers['Authorization']='Bearer '+os.environ['VAST_AI_KEY']
def call(method,url,body=None):
 r=s.request(method,'https://console.vast.ai/api'+url,json=body,timeout=40)
 if not r.ok:raise SystemExit('Approved personal-instance operation failed HTTP '+str(r.status_code)+'; response omitted.')
 return r.json()
u=call('GET','/v0/users/current');assert u['id']==345874
row=call('GET','/v0/instances/55191264/')['instances']
assert row['id']==55191264 and row['machine_id']==92165 and row['num_gpus']==4 and row['gpu_ram']==24576
assert row['disk_space']==180 and float(row['dph_total'])<=0.690001
assert row['intended_status']=='stopped' and row['actual_status']=='exited'
start=dt.datetime.now(dt.timezone.utc).isoformat()
plan.update(rented_at=start,account_credit_before_restart=u['credit'],preparation_status='approved_restart_requested')
p.write_text(json.dumps(plan,indent=2)+'\n')
response=call('PUT','/v0/instances/55191264/',{'state':'running'})
assert response.get('success') is True
result={'account_id':u['id'],'instance_id':55191264,'started_at':start,'credit_before_restart_usd':u['credit'],'hourly_rate_usd':row['dph_total'],'approved_total_usd':1.50,'restart_confirmed':True}
Path('.vast/olmo-approved-restart.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
