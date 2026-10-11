"""Audit and display recorded native-parser outputs; never invoke a model."""
import html
import json
from pathlib import Path
from audit_prompt_ablation import resolve

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / 'config/olmo-instruct-32b-cloud-plan.json').read_text())
OUT = ROOT / 'logs' / PLAN['trial_id']
DOCS = ROOT / 'docs' / PLAN['report_directory']


def signature(calls):
    result = []
    for call in calls or []:
        function = call['function']
        arguments = function['arguments']
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        result.append((function['name'], arguments))
    return result


def main():
    state = json.loads((OUT / 'batch_status.json').read_text())
    raw = [json.loads(line) for line in (OUT / 'gpu/raw-model-outputs.jsonl').read_text().splitlines()]
    events = []
    for episode in state['episodes']:
        directory = OUT / f'{episode["task"]}-{episode["seed"]}'
        if not (directory / 'inspect-log.json').exists():
            continue
        sample = json.loads((directory / 'inspect-log.json').read_text())['samples'][0]
        model_events = [e for e in sample['events'] if e['event'] == 'model']
        for turn, event in enumerate(model_events, 1):
            events.append((episode, turn, resolve(event, sample['attachments'])))
    if len(events) != len(raw):
        raise RuntimeError('Raw output count differs from recorded API events; inspect retries before mapping.')
    records = []
    body = ['<!doctype html><html lang="en"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>AllenAI OLMo Instruct: raw visible outputs</title>',
            '<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:24px;background:#f6f5f0;color:#23332e}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 monospace}details{background:white;margin:16px 0;padding:16px;border:1px solid #bac6be}summary{cursor:pointer;font-weight:600}a{color:#176b54}</style>',
            '<h1>All raw visible model outputs</h1>',
            '<p>Visible generated text before the unchanged native OLMo3 parser. This does not capture hidden reasoning, logits or generated token IDs.</p>',
            '<p><a href="index.html">Pilot report</a></p>']
    for generation, (episode, turn, event) in zip(raw, events):
        request = event['call']['request']
        response = event['call']['response']
        choice = response['choices'][0]
        message = choice['message']
        assert generation['seed'] == episode['seed'] == request['seed']
        assert generation['model'] == request['model'] == 'olmo-instruct-32b'
        assert generation['temperature'] == request['temperature'] == 0.6
        assert generation['top_p'] == request['top_p'] == 0.95
        assert signature(generation['native_tool_calls']) == signature(message.get('tool_calls'))
        assert (generation['native_content'] or '') == (message.get('content') or '')
        record = {'task': episode['task'], 'seed': episode['seed'], 'turn': turn,
                  'raw_parser_and_api_call_arguments_match': True,
                  'raw_parser_and_api_content_match': True,
                  'parsed_tool_calls': len(generation['native_tool_calls']),
                  'finish_reason': choice['finish_reason'], 'usage': response['usage']}
        records.append(record)
        title = f'{episode["task"]} · seed {episode["seed"]} · turn {turn} · {record["parsed_tool_calls"]} parsed calls · {choice["finish_reason"]}'
        body.append('<details open><summary>' + html.escape(title) + '</summary><pre>'
                    + html.escape(generation['raw_visible_model_output']) + '</pre></details>')
    body.append('</html>')
    (DOCS / 'raw-generations.html').write_text('\n'.join(body))
    audit = {'total_raw_outputs': len(raw), 'total_native_api_events': len(events),
             'all_raw_outputs_mapped_to_recorded_api_events': True,
             'extra_generation_probes': 0, 'records': records}
    for directory in (OUT, DOCS):
        (directory / 'raw-output-audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(f'Audited and exported {len(raw)} recorded outputs; no generation.')


if __name__ == '__main__':
    main()
