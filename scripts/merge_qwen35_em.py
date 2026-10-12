"""Derive and verify a BF16 checkpoint from the pinned rsLoRA; no inference."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def base_key(name):
    prefix = 'base_model.model.model.'
    if not name.startswith(prefix):
        raise ValueError('Unexpected adapter tensor prefix: ' + name)
    return 'model.language_model.' + name[len(prefix):]


def merge_weight(weight, a, b, scale):
    import torch
    assert weight.ndim == a.ndim == b.ndim == 2
    assert b.shape[1] == a.shape[0] and (b.shape[0], a.shape[1]) == tuple(weight.shape)
    delta = (b.float() @ a.float()) * scale
    assert torch.isfinite(delta).all() and torch.count_nonzero(delta) > 0
    return (weight.float() + delta).to(weight.dtype), delta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True, type=Path)
    p.add_argument('--report', required=True, type=Path)
    args = p.parse_args()
    import torch
    from safetensors.torch import load_file, save_file
    # A hand-computed update checks matrix orientation, scaling and source preservation.
    source = torch.tensor([[1., 1.], [1., 1.]], dtype=torch.bfloat16)
    test, _ = merge_weight(source, torch.tensor([[1., 2.]]), torch.tensor([[2.], [3.]]), 0.5)
    assert torch.equal(test, torch.tensor([[2., 3.], [2.5, 4.]], dtype=torch.bfloat16))
    assert torch.equal(source, torch.ones((2, 2), dtype=torch.bfloat16))
    torch.set_num_threads(8)
    cfg = json.loads(args.config.read_text())
    root = Path(__file__).resolve().parents[1]
    original = root / 'models/qwen35-9b'
    adapter = root / cfg['adapter_directory']
    target = root / cfg['model_directory']
    assert cfg['adapter_enabled'] and cfg['quantization'] is None and target != original
    if target.exists():
        raise RuntimeError('Refusing to overwrite an existing derived checkpoint.')
    ac = json.loads((adapter / 'adapter_config.json').read_text())
    assert ac['base_model_name_or_path'] == cfg['model_id']
    assert ac['r'] == 32 and ac['lora_alpha'] == 64 and ac['use_rslora']
    assert not ac.get('use_dora') and not ac.get('fan_in_fan_out') and ac['bias'] == 'none'
    assert not ac.get('modules_to_save') and not ac.get('rank_pattern') and not ac.get('alpha_pattern')
    weights = adapter / 'adapter_model.safetensors'
    assert digest(weights) == cfg['adapter_weight_sha256'] and weights.stat().st_size == cfg['adapter_weight_bytes']
    tensors = load_file(str(weights))
    assert len(tensors) == 256 and all(t.dtype == torch.float32 for t in tensors.values())
    updates = {}
    for name, a in tensors.items():
        if not name.endswith('.lora_A.weight'):
            continue
        stem = name[:-len('.lora_A.weight')]
        updates[base_key(stem) + '.weight'] = (a, tensors[stem + '.lora_B.weight'])
    assert len(updates) == 128 and 2 * len(updates) == len(tensors)
    index = json.loads((original / 'model.safetensors.index.json').read_text())
    assert set(updates) <= set(index['weight_map'])
    scale = ac['lora_alpha'] / math.sqrt(ac['r'])
    target.mkdir(parents=True)
    for file in original.iterdir():
        if file.is_file() and file.suffix != '.safetensors':
            shutil.copyfile(file, target / file.name)
    report = {'base_revision': cfg['revision'], 'adapter_revision': cfg['adapter_revision'],
        'adapter_sha256': digest(weights), 'method': 'FP32 B @ A update, rsLoRA alpha / sqrt(rank), rounded once into BF16 base weights',
        'scaling': scale, 'updates': [], 'shards': [], 'model_generation_requests': 0,
        'numerical_limit': 'BF16 merge is not asserted bitwise equivalent to an unmerged runtime LoRA.'}
    unchanged = 0
    for shard in sorted(set(index['weight_map'].values())):
        data = load_file(str(original / shard))
        expected = {}
        for name in data:
            if name in updates:
                a, b = updates[name]
                assert data[name].dtype == torch.bfloat16
                merged, delta = merge_weight(data[name], a, b, scale)
                changed = int(torch.count_nonzero(merged != data[name]))
                assert changed > 0
                report['updates'].append({'tensor': name, 'shape': list(merged.shape),
                    'changed_elements': changed, 'delta_l2': float(torch.linalg.vector_norm(delta)),
                    'dtype': str(merged.dtype)})
                data[name] = merged
            else:
                unchanged += 1
            expected[name] = hashlib.sha256(data[name].contiguous().view(torch.uint8).numpy().tobytes()).hexdigest()
        save_file(data, str(target / shard), metadata={'format': 'pt'})
        del data
        checked = load_file(str(target / shard))
        assert all(hashlib.sha256(t.contiguous().view(torch.uint8).numpy().tobytes()).hexdigest() == expected[n]
                   for n, t in checked.items()) and len(checked) == len(expected)
        del checked
        report['shards'].append({'name': shard, 'sha256': digest(target / shard),
            'bytes': (target / shard).stat().st_size, 'saved_tensors_exactly_verified': True})
        print('Verified derived shard:', shard, flush=True)
    assert len(report['updates']) == 128
    report.update(all_adapter_tensors_used=True, modified_weight_matrices=128,
        unchanged_weight_tensors=unchanged, original_checkpoint_preserved=True,
        tokenizer_template_and_config_preserved=True, synthetic_matrix_orientation_and_rounding_check=True,
        verified_complete=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
