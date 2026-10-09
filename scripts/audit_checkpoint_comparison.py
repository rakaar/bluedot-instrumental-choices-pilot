"""Check that a checkpoint diagnostic kept the first API prompt and sampling fixed."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from audit_prompt_ablation import resolve


def initial_request(directory: Path) -> tuple[dict, dict]:
    sample = json.loads((directory / 'inspect-log.json').read_text())['samples'][0]
    event = next(e for e in sample['events'] if e['event'] == 'model')
    request = resolve(event['call']['request'], sample['attachments'])
    (request.get('extra_headers') or {}).pop('x-irid', None)
    return sample, request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('diagnostic', type=Path)
    args = parser.parse_args()
    old_sample, old_request = initial_request(args.baseline)
    new_sample, new_request = initial_request(args.diagnostic)
    old_model = old_request.pop('model')
    new_model = new_request.pop('model')
    assert old_request == new_request, 'Initial API prompt, tools or sampling changed'
    for index in (0, 1):
        assert old_sample['messages'][index]['content'] == new_sample['messages'][index]['content']
    configs = [json.loads((p / 'control_config.json').read_text())
               for p in (args.baseline, args.diagnostic)]
    matched_fields = ('benchmark_revision', 'dtype', 'temperature', 'top_p',
                      'max_model_len', 'max_tokens_per_response', 'max_num_seqs')
    for field in matched_fields:
        assert configs[0][field] == configs[1][field], f'{field} changed'
    report = {
        'verified_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'baseline': str(args.baseline),
        'diagnostic': str(args.diagnostic),
        'served_model_before': old_model,
        'served_model_after': new_model,
        'initial_api_messages_tools_sampling_identical': True,
        'system_prompt_sha256': hashlib.sha256(new_sample['messages'][0]['content'].encode()).hexdigest(),
        'user_prompt_sha256': hashlib.sha256(new_sample['messages'][1]['content'].encode()).hexdigest(),
        'matched_configuration_fields': list(matched_fields),
        'comparison_excludes': 'Served model name and x-irid invocation header; attachment references resolved.',
        'interpretation_limit': 'Checkpoint format and GPU differ. One episode per setup cannot isolate a reliable quantization effect.',
    }
    path = args.diagnostic / 'checkpoint-comparison-audit.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Saved {path}; first API prompts, tools and sampling match.')


if __name__ == '__main__':
    main()
