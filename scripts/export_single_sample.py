"""Export the native Inspect log as an HTML transcript and measured resource summary."""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path
import re
from inspect_ai.log import read_eval_log

def escaped(value) -> str:
    encoded = html.escape(value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False))
    return re.sub(r'[ \t]+(?=\n|$)', lambda match: ''.join('&#32;' if char == ' ' else '&#9;' for char in match.group()), encoded)

def memory_bytes(text: str) -> float:
    value = text.split('/')[0].strip()
    match = re.fullmatch(r'([\d.]+)\s*([KMGT]?i?B)', value)
    if not match:
        return 0
    number, unit = match.groups()
    factors = {'B':1, 'kB':1000, 'KB':1000, 'KiB':1024, 'MB':1e6, 'MiB':1024**2,
               'GB':1e9, 'GiB':1024**3, 'TB':1e12, 'TiB':1024**4}
    return float(number) * factors[unit]

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('monitor_directory', type=Path)
    parser.add_argument('eval_file', type=Path)
    parser.add_argument('--observation', help='Descriptive trace review; does not change deterministic scores.')
    parser.add_argument('--resource-host', choices=['laptop', 'cloud'], default='laptop')
    args = parser.parse_args()
    directory = args.monitor_directory.resolve()
    selection = json.loads((directory / 'selection.json').read_text())
    config_path = directory / 'control_config.json'
    control_config = json.loads(config_path.read_text()) if config_path.exists() else {'model_id':'unsloth/Qwen2.5-7B-Instruct','dtype':'bfloat16','adapter_enabled':False}
    log = read_eval_log(str(args.eval_file))
    assert log.samples is not None and len(log.samples) == 1
    sample = log.samples[0]
    data = log.model_dump(mode='json')
    (directory / 'inspect-log.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    rows = [json.loads(line) for line in (directory / 'resources.jsonl').read_text().splitlines()]
    containers = [container for row in rows for container in row['containers']]
    scores = {name: score.model_dump(mode='json') for name, score in (sample.scores or {}).items()}
    metadata = (next(iter(scores.values())).get('metadata') or {}) if scores else {}
    calls = [call for message in sample.messages for call in (getattr(message, 'tool_calls', None) or [])]
    model_events = [event for event in data['samples'][0]['events'] if event['event'] == 'model']
    tool_errors = [{'function': event['function'], 'error': event['error']}
                   for event in data['samples'][0]['events']
                   if event['event'] == 'tool' and event.get('error')]
    summary = {
        'resource_host': args.resource_host,
        'status': log.status, 'sample_id': sample.id, 'sample_error': sample.error.model_dump(mode='json') if sample.error else None,
        'eval_file': str(args.eval_file.resolve()), 'messages': len(sample.messages), 'tool_calls': len(calls),
        'model_usage': data.get('stats', {}).get('model_usage'), 'scores': scores,
        'model_turns': len(model_events),
        'tool_errors': tool_errors,
        'model_turn_tool_options': [{'tools':[tool['name'] for tool in event['tools']],
                                   'tool_choice':event['tool_choice'], 'retries':event['retries']}
                                  for event in model_events],
        'final_stop_reason': sample.output.choices[0].stop_reason,
        'decision_point_reached': metadata.get('decision_point_reached'),
        'task': selection['task'], 'variant': selection['variant_letter'],
        'selection': selection,
        'control_config': control_config,
        'trace_review': args.observation,
        f'minimum_{args.resource_host}_available_ram_gib': min(row['mem_available_bytes'] for row in rows) / 1024**3,
        f'maximum_{args.resource_host}_swap_used_gib': max(row['swap_used_bytes'] for row in rows) / 1024**3,
        'swap_in_pages_delta': rows[-1]['swap_in_pages'] - rows[0]['swap_in_pages'],
        'swap_out_pages_delta': rows[-1]['swap_out_pages'] - rows[0]['swap_out_pages'],
        'observed_peak_sandbox_memory_mib': max([memory_bytes(c['MemUsage']) for c in containers] or [0]) / 1024**2,
        'observed_peak_sandbox_cpu_percent': max([float(c['CPUPerc'].rstrip('%')) for c in containers] or [0]),
        'resource_sampling_seconds': 5, 'resource_observations': len(rows),
        'limits': {'memory':'2 GB', 'cpus':1},
    }
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    observations = (
        f"The model made {len(calls)} tool call(s) across {len(model_events)} model turns. "
        f"Final stop reason: {summary['final_stop_reason']}. "
        f"Benchmark workflow engaged: {metadata.get('decision_point_reached', 'unknown')}. "
        f"Unauthorized shortcut detected: {metadata.get('ic_behavior_detected', 'unknown')}. "
    )
    if metadata.get('decision_point_reached') is False and metadata.get('ic_behavior_detected') is False:
        observations += 'No official workflow or shortcut was attempted; the absence of a shortcut does not establish reliable aligned behavior.'
    if args.observation:
        observations = args.observation + ' ' + observations
    cards = []
    for key in ['benchmark_task_completed', 'ic_behavior_detected', 'official_path_attempted', 'official_path_succeeded', 'deterministic_label_status', 'completion_mode']:
        cards.append(f'<div class="card"><small>{key}</small><strong>{escaped(metadata.get(key, "unknown"))}</strong></div>')
    turns = []
    for i, message in enumerate(sample.messages, 1):
        m = message.model_dump(mode='json')
        role = m['role']
        content = m.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(block.get('text', json.dumps(block, ensure_ascii=False)) for block in content)
        tool_error = (f'<div class="call"><b>Tool error</b><pre>{escaped(m["error"])}</pre></div>'
                      if role == 'tool' and m.get('error') else '')
        tools = ''.join(f'<div class="call"><b>Tool call: {escaped(call["function"])}</b><pre>{escaped(call.get("arguments", {}))}</pre></div>' for call in m.get('tool_calls', []) or [])
        tool_label = (' · ' + str(m.get('function', ''))) if role == 'tool' else ''
        opened = ' open' if role == 'assistant' or i < 3 else ''
        turns.append(f'<details class="turn {role}"{opened}><summary>{i}. {escaped(role + tool_label)}</summary><pre>{escaped(content)}</pre>{tools}{tool_error}</details>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen control — one Instrumental Choices episode</title><style>
body{font:16px/1.55 system-ui,sans-serif;background:#f5f4ef;color:#232923;margin:0}main{max-width:1050px;margin:auto;padding:30px 20px}h1{line-height:1.15}a{color:#176b54}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}.card,.turn{background:white;border:1px solid #d8ddd6;border-radius:10px;padding:16px}.card small{display:block;overflow-wrap:anywhere}.card strong{display:block;font-size:23px}.turn{margin:12px 0}.assistant{border-left:5px solid #2c8267}.tool{border-left:5px solid #7595ad}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.55 ui-monospace,monospace}.call{background:#f0f5f1;padding:12px;border-radius:6px}.muted{color:#536158}button{border:1px solid #87958a;border-radius:6px;padding:8px 12px;background:white;cursor:pointer;margin-right:8px}
</style><main><h1>Qwen control: one agent episode</h1><p class="muted">$TASK_NAME · Variant $VARIANT_LABEL · BF16 Qwen2.5-7B-Instruct · no adapter</p>
<p>One control-model sample, using the authors’ unmodified Inspect tool loop and deterministic scorers. This is a behavioral smoke test; it does not estimate a model’s misalignment rate.</p>
<p><a href="https://arxiv.org/html/2605.06490v1#S3.SS4">Paper: agent harness</a> · <a href="https://github.com/aisa-group/Instrumental-Choices/tree/397e6b18313b0dbfbe74206bf32b8e842b5dfca8">Pinned benchmark source</a> · <a href="summary.json">Scores and resources (JSON)</a> · <a href="inspect-log.json">Complete Inspect log (JSON)</a></p>
<h2>Observed behavior</h2><p>$OBSERVATIONS</p>
<h2>Deterministic outcome</h2><div class="cards">''' + ''.join(cards) + '''</div><h2>Laptop resources</h2><p>''' + (
        f'Observed sandbox peak: {summary["observed_peak_sandbox_memory_mib"]:.0f} MiB. '
        f'Lowest available {args.resource_host} RAM: {summary[f"minimum_{args.resource_host}_available_ram_gib"]:.2f} GiB. '
        f'Swap pages in/out during monitoring: {summary["swap_in_pages_delta"]}/{summary["swap_out_pages_delta"]}. '
        'Values were sampled about every 5–7 seconds; brief peaks between samples may be higher.'
    ) + '''</p><h2>Full observable transcript</h2><p>Model responses, tool calls and tool results are retained below. These are visible outputs, not access to hidden reasoning.</p><p><button onclick="document.querySelectorAll('details').forEach(d=>d.open=true)">Expand all</button><button onclick="document.querySelectorAll('details').forEach(d=>d.open=false)">Collapse all</button></p>''' + ''.join(turns) + '</main></html>'
    precision = ('GPTQ INT8 weights, BF16 computation' if control_config.get('quantization_bits') == 8 else 'BF16')
    page = page.replace('BF16 Qwen2.5-7B-Instruct', precision + ' ' + escaped(control_config['model_id'].split('/')[-1]))
    if args.resource_host == 'cloud':
        page = page.replace('<h2>Laptop resources</h2>', '<h2>Cloud runner resources</h2>')
    if control_config.get('adapter_enabled'):
        page = page.replace('Qwen control', 'Qwen with EM adapter').replace('One control-model sample', 'One EM-adapter model sample')
        page = page.replace(' · no adapter', ' · pinned bad-medical-advice adapter')
    page = page.replace('$TASK_NAME', escaped(selection['task'])).replace('$VARIANT_LABEL', escaped(selection['variant_letter'])).replace('$OBSERVATIONS', escaped(observations))
    (directory / 'transcript.html').write_text(page)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
