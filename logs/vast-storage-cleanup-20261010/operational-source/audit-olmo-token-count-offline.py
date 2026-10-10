import hashlib,json
from pathlib import Path
from tokenizers import Tokenizer
p=Path('logs/setup-olmo32b/native-first-prompt-audit.json');r=json.loads(p.read_text())
tp=Path('.vast/olmo-tokenizer-only-audit.json');tok=Tokenizer.from_file(str(tp))
gpu_text=Path('logs/setup-olmo32b/reconstructed-native-first-prompt.txt').read_text()
import sys; sys.path.insert(0, 'scripts')
from audit_checkpoint_comparison import initial_request
_, request=initial_request(Path('logs/quota-boost-olmo-32b-em-sampled-A-20261010/seed-374846912'))
functions=gpu_text[gpu_text.index('<functions>'):gpu_text.index('</functions>')+len('</functions>')]
assert [m['role'] for m in request['messages']]==['system','user']
text='<|im_start|>system\n'+request['messages'][0]['content']+functions+'<|im_end|>\n<|im_start|>user\n'+request['messages'][1]['content']+'<|im_end|>\n<|im_start|>assistant\n'
Path('logs/setup-olmo32b/reconstructed-native-first-prompt-corrected.txt').write_text(text)
ids=tok.encode(text,add_special_tokens=False).ids
r.update(reconstructed_prompt_tokens=len(ids),token_count_matches_api_usage=len(ids)==737,tokenizer_json_sha256=hashlib.sha256(tp.read_bytes()).hexdigest(),method='Offline CPU reconstruction from attachment-resolved Inspect messages, exact native template initial system/user branches, and the GPU-serialized vLLM tool-schema block, encoded using the identical pinned tokenizer.json. No weights loaded and no generation. Not an instrumented capture of server token IDs.',rendered_prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),correction_note='The earlier GPU audit counted BatchEncoding dictionary keys and failed to resolve Inspect attachment references. Its reconstructed prompt and token count are invalid. This offline correction resolves the original messages and supersedes both; original artifacts are preserved.',original_audit='logs/setup-olmo32b/native-first-prompt-audit.json')
assert len(ids)==737, len(ids)
p=Path('logs/setup-olmo32b/native-first-prompt-audit-correction.json');p.write_text(json.dumps(r,indent=2)+'\n')
d=Path('docs/quota-boost-olmo-32b-em-A/native-prompt-audit.json');d.write_bytes(p.read_bytes())
print('Offline reconstructed prompt:',len(ids),'tokens; API reports 737. All four tool schemas present. No inference.')
