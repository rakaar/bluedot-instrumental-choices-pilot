"""Hash task artifacts and independently verify the public backup without credentials."""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path.cwd()
OUT = ROOT / 'logs/olmo-instruct-32b-followup-A-20261012'
DOCS = ROOT / 'docs/olmo-instruct-32b-followup-A'
SETUP = ROOT / 'logs/setup-olmo-instruct-followup-20261012'


def buffers(path):
    data = path.read_bytes()
    result = [data]
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            result.extend(z.read(n) for n in z.namelist())
    elif path.name.endswith('.tar.gz'):
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as t:
            result.extend(t.extractfile(n).read() for n in t.getmembers() if n.isfile())
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['manifest','verify'])
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--record',type=Path)
    args=p.parse_args()
    if args.action == 'manifest':
        secrets=[os.environ[n].encode() for n in ('VAST_AI_KEY','GITHUB_TOKEN') if os.environ.get(n)]
        for path in (ROOT/'.vast/quota-readonly-key',ROOT/'.vast/t0-r2-cloud-ssh'):
            secrets.append(path.read_bytes().strip())
        creation=json.loads((ROOT/'.vast/olmo-followup-20261012/creation.json').read_text())
        secrets.append(creation['instance_api_key'].encode())
        patterns=[rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
                  rb'hf_[A-Za-z0-9]{24,}',rb'gh[opusr]_[A-Za-z0-9]{24,}']
        paths=set()
        for directory in (OUT,DOCS,SETUP,ROOT/'docs/experiment-history'):
            paths.update(x for x in directory.rglob('*') if x.is_file())
        paths.update(ROOT/name for name in json.loads((OUT/'artifact-checksums.json').read_text())['files'])
        paths.update(ROOT/x for x in ('README.md','docs/index.html','scripts/review_olmo_instruct_followup.py',
            'scripts/publish_experiment_history.py','scripts/audit_olmo_instruct_prompt.py',
            'scripts/export_olmo_instruct_raw.py','scripts/run_cloud_olmo_instruct_trial.py',
            'scripts/bootstrap_olmo_instruct_cloud.sh','scripts/start_olmo_instruct_setup.py',
            'config/olmo-instruct-32b-followup-A-cloud-plan.json','config/olmo-instruct-32b.json',
            'config/olmo-instruct-followup-cloud-connection.json',
            '.github/workflows/olmo-instruct-followup-cloud.yml'))
        paths.discard(args.manifest.resolve())
        if args.record: paths.discard(args.record.resolve())
        manifest={}
        for path in sorted(paths):
            assert path.is_file() and path.stat().st_size < 95*1024**2
            for b in buffers(path):
                if any(s and s in b for s in secrets) or any(re.search(pattern,b) for pattern in patterns):
                    raise RuntimeError('Credential scan failed; value omitted. File: '+str(path.relative_to(ROOT)))
            manifest[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        args.manifest.write_text(json.dumps({'recorded_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'method':'SHA-256; unpacked ZIP and tar members scanned for actual task credentials and private keys',
            'credential_scan_passed':True,'files':manifest},indent=2)+'\n')
        print('Credential scan passed and checksums saved:',len(manifest))
    else:
        assert args.record
        files=json.loads(args.manifest.read_text())['files']
        expected=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        env=dict(os.environ,GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_TERMINAL_PROMPT='0')
        env.pop('GITHUB_TOKEN',None)
        env.pop('GH_TOKEN',None)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git','-c','credential.helper=','clone','--quiet','--depth=1',
                'https://github.com/rakaar/bluedot-instrumental-choices-pilot.git',tmp],env=env,check=True)
            actual=subprocess.check_output(['git','-C',tmp,'rev-parse','HEAD'],env=env,text=True).strip()
            assert actual==expected,'Public branch is not the local backup commit.'
            for name,digest in files.items():
                assert hashlib.sha256((Path(tmp)/name).read_bytes()).hexdigest()==digest,name
        record={'verified_at':dt.datetime.now(dt.timezone.utc).isoformat(),'public_commit':actual,
            'public_repository':'https://github.com/rakaar/bluedot-instrumental-choices-pilot',
            'manifest':str(args.manifest),'matched_files':len(files),'mismatches':[],
            'credential_free_public_clone_verified':True}
        args.record.write_text(json.dumps(record,indent=2)+'\n')
        print('Public backup hash-verified:',actual,len(files))


if __name__=='__main__': main()
