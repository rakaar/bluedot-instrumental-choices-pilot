"""Audit recorded API tool calls and token usage without generating model requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args()
    data = json.loads((args.run_directory / 'inspect-log.json').read_text())
    assert len(data['samples']) == 1
    events = [e for e in data['samples'][0]['events'] if e['event'] == 'model']
    rows = []
    for index, event in enumerate(events, 1):
        response = event['call']['response']
        choice = response['choices'][0]
        inspected = event['output']['choices'][0]['message']
        api_calls = choice['message'].get('tool_calls') or []
        inspect_calls = inspected.get('tool_calls') or []
        api_functions = [call['function']['name'] for call in api_calls]
        inspect_functions = [call['function'] for call in inspect_calls]
        rows.append({'turn': index, 'api_tool_calls': len(api_calls),
                     'inspect_tool_calls': len(inspect_calls),
                     'api_functions': api_functions, 'inspect_functions': inspect_functions,
                     'api_finish_reason': choice['finish_reason'],
                     'api_usage': response['usage']})
    report = {
        'turns': rows,
        'api_tool_calls_match_inspect': all(r['api_functions'] == r['inspect_functions'] for r in rows),
        'maximum_prompt_tokens': max(r['api_usage']['prompt_tokens'] for r in rows),
        'maximum_output_tokens': max(r['api_usage']['completion_tokens'] for r in rows),
        'final_response': events[-1]['call']['response']['choices'][0],
        'final_visible_text': events[-1]['output']['choices'][0]['message']['content'],
        'limitation': 'API responses are after the vLLM tool parser; this is not an audit of the original generated token stream.',
    }
    path = args.run_directory / 'api-response-audit.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(f'Saved {path}: {len(rows)} model turns, API calls match Inspect: {report["api_tool_calls_match_inspect"]}.')


if __name__ == '__main__':
    main()
