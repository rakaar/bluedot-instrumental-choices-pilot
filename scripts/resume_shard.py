"""Resume a slow public checkpoint shard with checked HTTP byte ranges."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--files', type=Path, required=True)
parser.add_argument('--file', required=True)
args = parser.parse_args()
config = json.loads(args.config.read_text())
entry = next(x for x in json.loads(args.files.read_text()) if x['path'] == args.file)
model_dir = ROOT / config['model_directory']
target = model_dir / args.file
if target.exists():
    raise SystemExit('Shard already complete; use the normal checkpoint verifier.')
partials = list((model_dir / '.cache/huggingface/download').glob('*.' + entry['sha256'] + '.incomplete'))
assert len(partials) == 1, 'Expected exactly one stopped Hugging Face partial file.'
partial = partials[0]
offset = partial.stat().st_size
assert 0 < offset < entry['size']
parts_dir = model_dir / '.resume-parts'
parts_dir.mkdir(exist_ok=True)
remaining = entry['size'] - offset
url = f"https://huggingface.co/{config['model_id']}/resolve/{config['revision']}/{args.file}"


def fetch(index):
    start = offset + remaining * index // 8
    end = offset + remaining * (index + 1) // 8 - 1
    path = parts_dir / str(index)
    for attempt in range(3):
        try:
            with requests.get(url, params={'download':'true','range_start':str(start)},
                              headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'},
                              stream=True, timeout=(20,120)) as response:
                response.raise_for_status()
                assert response.status_code == 206
                assert response.headers.get('Content-Range') == f"bytes {start}-{end}/{entry['size']}"
                with path.open('wb') as handle:
                    for chunk in response.iter_content(4 * 1024 * 1024):
                        handle.write(chunk)
            assert path.stat().st_size == end - start + 1
            print(f'Range {index+1}/8 complete', flush=True)
            return path
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


print(f'Resuming {args.file}: retained {offset:,} bytes, fetching {remaining:,} bytes.', flush=True)
with ThreadPoolExecutor(max_workers=8) as pool:
    paths = list(pool.map(fetch, range(8)))
with partial.open('ab') as output:
    for path in paths:
        with path.open('rb') as source:
            shutil.copyfileobj(source, output, 8 * 1024 * 1024)
assert partial.stat().st_size == entry['size']
with partial.open('rb') as handle:
    assert hashlib.file_digest(handle,'sha256').hexdigest() == entry['sha256']
partial.replace(target)
shutil.rmtree(parts_dir)
print('Complete shard SHA-256 matches the pinned upstream file.', flush=True)
