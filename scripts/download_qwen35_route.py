"""Transfer public pinned weight shards via a reachable mirror, then hash them."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / 'config/qwen35-9b-download-plan.json').read_text())
OUT = ROOT / os.environ.get('QWEN35_DOWNLOAD_ROUTE_DIRECTORY', 'logs/setup-qwen35-9b-20261012')
DESTINATION = ROOT / os.environ.get('QWEN35_DOWNLOAD_ROUTE_DESTINATION', 'models')
CHUNK = int(os.environ.get('QWEN35_DOWNLOAD_CHUNK_BYTES', 64 * 1024 * 1024))
assert 1024 * 1024 <= CHUNK <= 512 * 1024 * 1024


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
    endpoint = os.environ.get('QWEN35_DOWNLOAD_ENDPOINT', 'https://hf-mirror.com')
    assert endpoint in ('https://hf-mirror.com', 'https://huggingface.co')
    url = (endpoint + '/' + artifact['model_id'] + '/resolve/'
           + artifact['revision'] + '/' + record['name'])
    for start in range(partial.stat().st_size if partial.exists() else 0, record['bytes'], CHUNK):
        end = min(record['bytes'] - 1, start + CHUNK - 1)
        expected = f"bytes {start}-{end}/{record['bytes']}"
        for attempt in range(5):
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
                delay = min(120, 15 * 2 ** attempt)
                status = error.code if isinstance(error, urllib.error.HTTPError) else None
                retry_after = error.headers.get('Retry-After') if isinstance(error, urllib.error.HTTPError) else None
                if retry_after:
                    try: delay = max(delay, float(retry_after))
                    except ValueError: delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                event({'file': record['name'], 'status': 'range_retry', 'offset': start,
                       'attempt': attempt + 1, 'error_type': type(error).__name__, 'http_status': status,
                       'retry_after_header': retry_after, 'backoff_seconds': delay})
                if attempt == 4 or delay > 1800:
                    raise
                time.sleep(delay)
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
    event({'status': 'started', 'route': os.environ.get('QWEN35_DOWNLOAD_ENDPOINT', 'https://hf-mirror.com') + '; exact official pinned hashes required',
           'model_loading_executed': False, 'model_generation_executed': False})
    jobs = [(a, f) for a in PLAN['artifacts'] for f in a['files']
            if f['name'].endswith('.safetensors')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda job: transfer(*job), jobs))
    event({'status': 'complete', 'verified_weight_shards': len(jobs)})
    (OUT / 'alternate-route-complete').touch()


if __name__ == '__main__':
    main()
