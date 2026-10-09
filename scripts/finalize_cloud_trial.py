"""Collect remote diagnostics, stop compute, and verify a public results backup."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile

from cloud_vast_instance import PLAN, ROOT, snapshot

OUT = ROOT / 'logs' / PLAN['trial_id']


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def collect_and_stop():
    config = Path(os.environ['RUNNER_TEMP']) / 'bluedot-cloud-ssh-config'
    archive = OUT / 'gpu-final.tar.gz'
    OUT.mkdir(parents=True, exist_ok=True)
    collected = False
    if config.exists():
        with archive.open('wb') as handle:
            result = subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
                'cd /workspace/bluedot-ic && tar -czf - logs/' + PLAN['trial_id'] + '/gpu'],
                stdout=handle, stderr=subprocess.PIPE, timeout=60)
        if result.returncode == 0:
            subprocess.run(['tar', '-xzf', str(archive), '-C', str(ROOT)], check=True)
            collected = True
        else:
            archive.unlink(missing_ok=True)
        # This also revokes only the ephemeral trial SSH key before stopping.
        subprocess.run(['ssh', '-F', str(config), 'trial-gpu',
            'cd /workspace/bluedot-ic && inference/.venv/bin/python scripts/cloud_gpu_trial.py stop'],
            capture_output=True, timeout=45)
    before = snapshot()
    if before['intended_status'] != 'stopped':
        save('retention-after-trial.json', {'instance': before, 'compute_stopped_verified': False,
            'remote_stop_attempted': True, 'host_bound_deadline_guard_remains_active': True,
            'workspace_deleted': False, 'remote_diagnostics_collected': collected})
        raise RuntimeError('Remote stop was not confirmed; host-bound session guard remains active. Cloud key cannot mutate compute.')
    for _ in range(18):
        row = snapshot()
        if row['actual_status'] == 'exited' and row['intended_status'] == 'stopped':
            storage = row['dph_total'] - row['dph_base']
            save('retention-after-trial.json', {'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'instance': row, 'compute_stopped_verified': True, 'workspace_retained_gb': 140,
                'workspace_deleted': False, 'remaining_storage_rate_usd_per_hour': storage,
                'remote_diagnostics_collected': collected, 'no_zero_total_billing_claim': True})
            print('GPU compute stopped and verified; the paid workspace is retained.')
            return
        time.sleep(5)
    save('retention-after-trial.json', {'instance': row, 'compute_stopped_verified': False,
        'stop_requested': True, 'workspace_deleted': False, 'remote_diagnostics_collected': collected})
    raise RuntimeError('Compute stop was requested but not yet verified.')


def backup():
    changed = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).split(b'\0')
    changed += subprocess.check_output(['git', 'diff', '--name-only', '-z'], cwd=ROOT).split(b'\0')
    selected = {Path(name.decode()) for name in changed if name and
        (name.startswith(b'logs/') or name.startswith(b'docs/quota-boost-32b-em-cloud/'))}
    selected.update(p.relative_to(ROOT) for p in OUT.rglob('*') if p.is_file())
    selected.discard(OUT.relative_to(ROOT) / 'artifact-checksums.json')
    selected.discard(OUT.relative_to(ROOT) / 'public-backup-verification.json')
    paths = sorted(selected)
    if not paths:
        raise RuntimeError('No cloud results to back up.')
    secrets = [os.environ[name].encode() for name in ('CLOUD_TRIAL_INSTANCE_KEY', 'CLOUD_TRIAL_SSH_KEY', 'GITHUB_TOKEN')
        if os.environ.get(name)]
    patterns = [rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----', rb'hf_[A-Za-z0-9]{24,}', rb'gh[opusr]_[A-Za-z0-9]{24,}']
    manifest = {}
    for name in paths:
        p = ROOT / name
        if not p.is_file() or p.stat().st_size >= 95 * 1024**2:
            raise RuntimeError('Unexpected public backup file or size.')
        data = p.read_bytes()
        buffers = [data]
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                buffers.extend(z.read(member) for member in z.namelist())
        if any(secret in b for b in buffers for secret in secrets) or any(re.search(pattern, b) for b in buffers for pattern in patterns):
            raise RuntimeError('Public backup credential scan failed; no secret value printed.')
        manifest[str(name)] = hashlib.sha256(data).hexdigest()
    name = OUT.relative_to(ROOT) / 'artifact-checksums.json'
    save('artifact-checksums.json', {'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'method': 'SHA-256; this manifest excluded from itself', 'files': manifest,
        'credential_scan_passed': True})
    subprocess.run(['git', 'config', 'user.name', 'BlueDot cloud trial'], cwd=ROOT, check=True)
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], cwd=ROOT, check=True)
    subprocess.run(['git', 'add', '--', *map(str, paths), str(name)], cwd=ROOT, check=True)
    subprocess.run(['git', 'diff', '--cached', '--check'], cwd=ROOT, check=True)
    subprocess.run(['git', 'commit', '--quiet', '-m', 'Back up three-sample cloud EM Quota Boost A trial'], cwd=ROOT, check=True)
    subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT, check=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    clean_env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null', GIT_TERMINAL_PROMPT='0')
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['git', '-c', 'credential.helper=', 'clone', '--quiet', '--depth=1',
            'https://github.com/rakaar/bluedot-instrumental-choices-pilot.git', tmp], env=clean_env, check=True)
        clone = Path(tmp)
        actual = subprocess.check_output(['git', '-C', tmp, 'rev-parse', 'HEAD'], env=clean_env, text=True).strip()
        if actual != commit:
            raise RuntimeError('Public clone does not contain the exact results commit.')
        for file, digest in manifest.items():
            if hashlib.sha256((clone / file).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Public cloud result hash verification failed.')
    save('public-backup-verification.json', {'artifact_commit': commit,
        'credential_free_public_clone_verified': True, 'matched_files': len(manifest),
        'mismatches': [], 'verification_record_delivered_in_workflow_artifact': True})
    print(f'Public results backup verified: {commit}, {len(manifest)} files.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['stop', 'backup'])
    args = p.parse_args()
    collect_and_stop() if args.action == 'stop' else backup()


if __name__ == '__main__':
    main()
