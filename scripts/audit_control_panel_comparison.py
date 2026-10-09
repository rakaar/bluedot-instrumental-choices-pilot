"""Audit the paired initial requests and outcomes of the INT8 and BF16 panels."""
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scripts'))
from audit_checkpoint_comparison import initial_request
plan=json.loads((root/'config/control-32b-bf16-pilot-A-plan.json').read_text())
new=json.loads((root/plan['output_directory']/'panel.json').read_text())
old=json.loads((root/'docs/control-32b-int8-pilot-A/panel.json').read_text())
by_id={(r['task'],r['seed']):r for r in old['records']}
rows=[]
for n in new['records']:
 o=by_id[(n['task'],n['seed'])]
 old_sample,a=initial_request(root/o['monitor_directory']);new_sample,b=initial_request(root/n['monitor_directory'])
 a.pop('model');b.pop('model')
 first_tokens=lambda sample:next(e for e in sample['events'] if e['event']=='model')['call']['response']['usage']['prompt_tokens']
 rows.append({'task':n['task'],'seed':n['seed'],'same_initial_prompt_tools_sampling_except_model_name':a==b,'different_keys':sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k)),'initial_prompt_tokens_int8':first_tokens(old_sample),'initial_prompt_tokens_bf16':first_tokens(new_sample),'int8_approved_completion':o['approved_completion'],'bf16_approved_completion':n['approved_completion']})
result={'paired_samples':len(rows),'rows':rows,'all_pairs_initial_requests_match_except_served_model_name':all(r['same_initial_prompt_tools_sampling_except_model_name'] for r in rows),'all_pairs_initial_prompt_token_counts_match':all(r['initial_prompt_tokens_int8']==r['initial_prompt_tokens_bf16'] for r in rows),'tokenizer_config_comparison':'config/tokenizer-config-comparison-32b-bf16-int8.json','interpretation_limit':'Different checkpoint formats, padding metadata and GPU deployments plus small, selected samples; this comparison does not isolate a general quantization effect.'}
(root/plan['output_directory']/'int8-comparison-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
