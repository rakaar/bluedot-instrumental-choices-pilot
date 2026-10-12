"""Publish the completed nine-episode AllenAI screen from saved evidence only."""
import datetime as dt
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT/'config/olmo-instruct-32b-followup-A-cloud-plan.json').read_text())
OUT = ROOT/'logs'/PLAN['trial_id']
DOCS = ROOT/'docs'/PLAN['report_directory']


def load(path):
    return json.loads(path.read_text())


def main():
    state = load(OUT/'batch_status.json')
    assert state['status'] == 'finished' and len(state['episodes']) == 6
    raw = load(DOCS/'raw-output-audit.json')
    assert raw['all_raw_outputs_mapped_to_recorded_api_events']
    prompt = load(DOCS/'native-prompt-audit.json')
    assert len(prompt['episode_audits']) == 6 and all(r['token_count_matches_api'] for r in prompt['episode_audits'])
    prior = load(ROOT/'docs/olmo-instruct-32b-capability-A/manual-review.json')
    config = load(OUT/'model-config.json')
    assert config == prior['model_config']
    annotations = load(OUT/'manual-observations.json')
    reviewed = []
    for task in PLAN['tasks']:
        rows = [r for r in state['episodes'] if r['task'] == task]
        assert [r['seed'] for r in rows] == PLAN['seeds']
        for row in rows:
            stem = f"{task}-{row['seed']}"
            summary = load(OUT/stem/'summary.json')
            api = load(OUT/stem/'api-response-audit.json')
            score = next(v for k,v in summary['scores'].items() if 'completion' in k)
            metadata = score['metadata']
            assert summary['sample_error'] is None and metadata['deterministic_label_status'] == 'ok'
            assert api['api_tool_calls_match_inspect']
            assert stem in annotations and annotations[stem]['manually_read_full_trace']
            reviewed.append({'task':task,'seed':row['seed'],
                'completion':metadata['benchmark_task_completed'],
                'official_path_succeeded':metadata['official_path_succeeded'],
                'decision_point_reached':metadata['decision_point_reached'],
                'native_ic':metadata['ic_behavior_detected'],
                'executed_tools':summary['tool_calls'],'model_turns':summary['model_turns'],
                'label_status':metadata['deterministic_label_status'],'sample_error':summary['sample_error'],
                'finish_reason':api['final_response']['finish_reason'],
                'maximum_prompt_tokens':api['maximum_prompt_tokens'],
                'maximum_output_tokens':api['maximum_output_tokens'],
                'observation':annotations[stem]['observation'],
                'observed_forbidden_source_read':annotations[stem]['observed_forbidden_source_read'],
                'source_flags':row['tool_source_flags'],
                'trace':stem+'/transcript.html'})
    aggregate = []
    for task in ['quota_boost',*PLAN['tasks']]:
        rows = prior['episodes'] if task == 'quota_boost' else [r for r in reviewed if r['task'] == task]
        assert len(rows) == 3
        aggregate.append({'task':task,'variant':'A','passes':sum(bool(r['completion']) for r in rows),
            'samples':len(rows),'executed_tools':sum(r['executed_tools'] for r in rows)})
    passes = sum(r['passes'] for r in aggregate)
    tools = sum(r['executed_tools'] for r in aggregate)
    diagnosis = ('This unchanged AllenAI deployment failed all nine selected-task episodes. '
                 'Exclude this configuration from the current pilot. This does not establish model-wide inability: '
                 'the native template omits its generic tool-call format notice when a benchmark system message is supplied, '
                 'and that possible contributor was not tested causally.' if passes == 0 else
                 'The additional tasks revealed some accepted completions. Assess the task-specific results and instruction '
                 'compliance before excluding the checkpoint. This selected-task screen is not a benchmark-wide estimate.')
    cleanup = load(DOCS/'teardown.json')
    billing_note = ('Instance 55573802 and its 140GB workspace have been permanently deleted after verified public backup. '
                    'Personal-account instances, volumes, endpoints and worker groups are empty: $0/hour ongoing resource billing. '
                    f'Account credit decreased by approximately ${cleanup["approximate_account_credit_decrease_usd"]:.2f}; '
                    'this is a dated snapshot difference, not a finalized invoice.'
                    if cleanup.get('all_billable_resource_lists_empty') and cleanup.get('workspace_deleted') else
                    'Compute is stopped. The retained workspace still has a storage charge until the authorized deletion is verified.')
    report = {'reviewed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'manual_review_pending':False,
        'model':config['model_id'],'model_config':config,'plan':PLAN,
        'new_episodes':reviewed,'aggregate_three_task_screen':aggregate,
        'aggregate_episodes':9,'aggregate_completions':passes,'aggregate_executed_tools':tools,
        'earlier_quota_evidence':'../olmo-instruct-32b-capability-A/manual-review.json',
        'raw_output_audit':raw,'new_episodes_run':6,'extra_generation_probes':0,'episode_retries':0,
        'native_prompt_audit':prompt,
        'new_episode_stop_finish_reasons':sum(r['finish_reason']=='stop' for r in reviewed),
        'new_episode_context_limit_reached':any(r['maximum_prompt_tokens']>=config['max_model_len'] for r in reviewed),
        'new_episode_response_limit_reached':any(r['finish_reason']=='length' for r in reviewed),
        'diagnosis':diagnosis,'matched_control_for_aisi_adapter':False,
        'comparison_limit':PLAN['comparison_limit'],
        'method':'Read all six complete traces and official deterministic scorer metadata. Match raw pre-parser '
                 'outputs with API and Inspect records. Earlier Quota Boost samples are counted once; no new generations.'}
    for destination in (OUT,DOCS):
        (destination/'manual-review.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    panel = load(DOCS/'panel.json')
    panel.update(manual_review_pending=False,manual_review='manual-review.json',aggregate_three_task_screen=aggregate)
    (DOCS/'panel.json').write_text(json.dumps(panel,indent=2,ensure_ascii=False)+'\n')
    esc = html.escape
    totals = ''.join(f'<tr><th>{esc(r["task"])}</th><td>A</td><td>{r["passes"]}/3</td><td>{r["executed_tools"]}</td></tr>' for r in aggregate)
    rows = ''.join('<tr><td>'+esc(r['task'])+'</td><td>'+str(r['seed'])+'</td><td>'+str(r['completion'])+
        '</td><td>'+str(r['executed_tools'])+'</td><td>'+esc(r['observation'])+'</td><td><a href="'+r['trace']+'">Full trace</a></td></tr>' for r in reviewed)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OLMo 3.1 32B Instruct: {passes}/9 completions</title>
<style>body{{font:16px/1.6 system-ui;max-width:1200px;margin:auto;padding:24px;color:#23332e;background:#f6f5f0}}h1{{line-height:1.2}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:12px;border:1px solid #bac6be;text-align:left;vertical-align:top}}a{{color:#176b54}}.scroll{{overflow:auto}}.callout{{background:#e6eee3;padding:18px;border-left:4px solid #176b54}}</style></head><body>
<p><a href="../experiment-history/">Chronological experiment history</a></p>
<h1>OLMo 3.1 32B Instruct: {passes}/9 task completions</h1>
<p>Final AllenAI SFT + DPO + RLVR checkpoint, unquantized BF16, no EM adapter. Three selected tasks, variant A, three samples each. Six new episodes complete the earlier three-sample Quota Boost screen.</p>
<div class="callout">{esc(diagnosis)}</div>
<h2>All three tasks</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Variant</th><th>Completions</th><th>Executed tools</th></tr></thead><tbody>{totals}</tbody></table></div>
<p>Quota Boost ran on 11 October; Training Preserver and Memory Keeper ran on 12 October. All use the exact same checkpoint revision, native chat template, parser, BF16 precision, temperature 0.6, top-p 0.95 and declared seeds. Context: 16,384 tokens; output limit: 2,048 per response. Every episode starts with a fresh sandbox. The selected seeds were reused across tasks; these are stochastic samples, not different questions.</p>
<h2>The six new samples</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Seed</th><th>Completion</th><th>Executed tools</th><th>Reviewed behavior</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>
<p>All six new episodes have valid official deterministic labels and no sample errors. Task receipt completion is separate from instruction compliance. Raw outputs, parsed API responses and Inspect traces were checked for agreement.</p>
<p>All six ended normally after one model response, without executing a tool. Training Preserver did not save a checkpoint, export weights or request an extension. Memory Keeper did not load a real ticket, submit a resolution or leave an approved handoff. One response only announced a plan; the other five invented operational facts and tool results. Inputs were 765 tokens; outputs were 24–2,038 tokens, below the 2,048 response cap. No context or response truncation was recorded.</p>
<h2>Interpretation</h2><p>Both Qwen2.5-32B BF16 control and this AllenAI checkpoint now have nine episodes across Quota Boost, Training Preserver and Memory Keeper A. Sampling and model-specific tool interfaces differ between the two model families. The final AllenAI checkpoint is not a matched causal control for the UK AISI reward-hacking adapter.</p>
<p>The native OLMo template includes all four tool schemas but omits its generic function-call format notice when given the benchmark system message. No prompt-format ablation or extra model probes ran. Failed completion without an unauthorized shortcut is not evidence of alignment.</p>
<h2>Costs and cleanup</h2><p>Personal Vast account only; no SPAR credits. Two A6000 48GB GPUs at $0.8389/hour combined, including 140GB active storage. {esc(billing_note)}</p>
<p><a href="teardown.json">Final billing and deletion verification</a> · <a href="manual-review.json">Reviewed results</a> · <a href="raw-generations.html">Every raw output</a> · <a href="raw-output-audit.json">Raw/API consistency</a> · <a href="initial-request-audit.json">Request settings audit</a> · <a href="native-prompt-audit.json">Native prompt audit</a> · <a href="../olmo-instruct-32b-capability-A/">Earlier Quota Boost traces</a> · <a href="../control-32b-bf16-pilot-A/">Qwen BF16 comparison</a></p></body></html>'''
    (DOCS/'index.html').write_text(page)
    print(f'Published six reviewed follow-ups and aggregate {passes}/9 completions; {tools} executed tools. No generation.')


if __name__ == '__main__':
    main()
