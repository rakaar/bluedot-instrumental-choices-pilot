"""Reconstruct the first recorded native prompt using tokenizer metadata only."""
import argparse
import hashlib
import json
from pathlib import Path
import jinja2
from tokenizers import Tokenizer
from audit_checkpoint_comparison import initial_request

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tokenizer-json', type=Path, required=True)
    args = p.parse_args()
    plan = json.loads((ROOT / 'config/olmo-instruct-32b-cloud-plan.json').read_text())
    files = json.loads((ROOT / plan['checkpoint_files_plan']).read_text())
    expected = next(f['sha256'] for a in files['artifacts'] for f in a['files'] if f['name'] == 'tokenizer.json')
    assert hashlib.sha256(args.tokenizer_json.read_bytes()).hexdigest() == expected
    setup = ROOT / 'logs/setup-olmo-instruct-20261011'
    source = (setup / 'released-chat_template.jinja').read_text()
    config = json.loads((setup / 'released-tokenizer_config.json').read_text())
    assert source == config['chat_template']
    _, request = initial_request(ROOT / 'logs' / plan['trial_id'] / 'quota_boost-374846912')
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    # Transformers replaces Jinja's default HTML-oriented JSON filter with this serialization.
    env.filters['tojson'] = lambda x, ensure_ascii=False, indent=None, separators=None, sort_keys=False: json.dumps(x, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys)
    rendered = env.from_string(source).render(messages=request['messages'], tools=request['tools'],
        add_generation_prompt=True, eos_token=config['eos_token'])
    count = len(Tokenizer.from_file(str(args.tokenizer_json)).encode(rendered, add_special_tokens=False).ids)
    actual = json.loads((ROOT / 'logs' / plan['trial_id'] / 'quota_boost-374846912/api-response-audit.json').read_text())['maximum_prompt_tokens']
    assert count == actual
    assert rendered.endswith('<|im_start|>assistant\n')
    assert all('"name": "' + name + '"' in rendered for name in ('shell', 'read_file', 'write_file', 'list_dir'))
    (setup / 'reconstructed-native-first-prompt.txt').write_text(rendered)
    audit = {'method': 'CPU-only reconstruction from resolved recorded API messages/tools and the pinned native template, encoded using the hash-matched released tokenizer.json. No weights loaded or generation. Not direct capture of server token IDs.',
             'native_template_sha256': hashlib.sha256(source.encode()).hexdigest(),
             'tokenizer_json_sha256': expected, 'rendered_prompt_sha256': hashlib.sha256(rendered.encode()).hexdigest(),
             'reconstructed_prompt_tokens': count, 'actual_api_prompt_tokens': actual,
             'token_count_matches_api': True, 'generation_boundary_has_real_newline': True,
             'all_four_tool_names_present': True,
             'generic_function_call_format_notice_present': 'Output any function calls within' in rendered,
             'model_loading_executed': False, 'model_generation_executed': False}
    for destination in (setup, ROOT / 'docs' / plan['report_directory']):
        (destination / 'native-prompt-audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    print('Native prompt reconstructed; token count matches API:', count)


if __name__ == '__main__':
    main()
