"""Transfer public pinned weight shards via a reachable mirror, then hash them."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / 'config/qwen35-9b-download-plan.json').read_text())
OUT = ROOT / os.environ.get('QWEN35_DOWNLOAD_ROUTE_DIRECTORY', 'logs/setup-qwen35-9b-20261012')
DESTINATION = ROOT / os.environ.get('QWEN35_DOWNLOAD_ROUTE_DESTINATION', 'models')
CHUNK = 64 * 1024 * 1024


def event(value):
    value['recorded_at'] = datetime.now(timezone.utc).isoformat()
    with (OUT / 'alternate-download-route.jsonl').open('a') as f:
        f.write(json.dumps(value) + '\n')
    print(json.dumps(value), flush=True)


def transfer(artifact, record):
    final = DESTINATION / artifact['directory_name'] / record['name']
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_suffix(final.suffix + '.partial')
    if final.exists():
        with final.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        if final.stat().st_size == record['bytes'] and digest == record['sha256']:
            event({'file': record['name'], 'status': 'already_verified'})
            return
        raise RuntimeError('Refusing to overwrite a mismatched finished file')
    url = ('https://hf-mirror.com/' + artifact['model_id'] + '/resolve/'
           + artifact['revision'] + '/' + record['name'])
    for start in range(partial.stat().st_size if partial.exists() else 0, record['bytes'], CHUNK):
        end = min(record['bytes'] - 1, start + CHUNK - 1)
        expected = f"bytes {start}-{end}/{record['bytes']}"
        for attempt in range(3):
            try:
                request = urllib.request.Request(url + f'?download=true&chunk={start}',
                    headers={'Range': f'bytes={start}-{end}'})
                with urllib.request.urlopen(request, timeout=90) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != expected:
                        raise RuntimeError('Server did not honor exact bounded byte range')
                    data = response.read(CHUNK + 1)
                    if len(data) != end - start + 1:
                        raise RuntimeError('Incomplete byte range')
                with partial.open('ab') as f:
                    f.write(data)
                break
            except Exception as error:
                event({'file': record['name'], 'status': 'range_retry', 'offset': start,
                       'attempt': attempt + 1, 'error_type': type(error).__name__})
                if attempt == 2:
                    raise
                time.sleep(3)
        if (start // CHUNK) % 8 == 0:
            event({'file': record['name'], 'status': 'transferring', 'bytes': end + 1,
                   'total_bytes': record['bytes']})
    with partial.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if partial.stat().st_size != record['bytes'] or digest != record['sha256']:
        raise RuntimeError('Pinned weight size or SHA-256 mismatch')
    partial.replace(final)
    event({'file': record['name'], 'status': 'verified', 'sha256': digest})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    event({'status': 'started', 'route': 'HTTPS mirror; exact official pinned hashes required',
           'model_loading_executed': False, 'model_generation_executed': False})
    jobs = [(a, f) for a in PLAN['artifacts'] for f in a['files']
            if f['name'].endswith('.safetensors')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda job: transfer(*job), jobs))
    event({'status': 'complete', 'verified_weight_shards': len(jobs)})
    (OUT / 'alternate-route-complete').touch()


if __name__ == '__main__':
    main()
