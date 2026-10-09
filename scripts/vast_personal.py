"""Operate only the verified personal Vast account; never read a fallback key."""
import argparse
import json
import os
from pathlib import Path
import requests

ACCOUNT_ID = 345874
BASE = 'https://console.vast.ai/api'
INSTANCE_FIELDS = ('id', 'client_id', 'label', 'actual_status', 'intended_status',
                   'status_msg', 'gpu_name', 'gpu_ram', 'num_gpus', 'machine_id',
                   'dph_total', 'dph_base', 'disk_space', 'ssh_host', 'ssh_port',
                   'public_ipaddr', 'ports', 'start_date', 'image_uuid')


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k,v in value.items()
                if not any(word in k.lower() for word in ('api_key', 'token', 'secret', 'password'))}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'resources', 'create', 'instance', 'stop', 'destroy'])
    parser.add_argument('--id', type=int)
    parser.add_argument('--body', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    key = os.environ.get('VAST_AI_KEY')
    if not key:
        raise SystemExit('VAST_AI_KEY must be supplied by the personal shell environment; no fallback is allowed.')
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + key

    def call(method, path, body=None, params=None):
        response = session.request(method, BASE + path, json=body, params=params, timeout=45)
        if not response.ok:
            raise SystemExit(f'Vast API {method} {path} returned HTTP {response.status_code}; response omitted to protect credentials.')
        return response.json()

    user = call('GET', '/v0/users/current')
    if user.get('id') != ACCOUNT_ID:
        raise SystemExit('Billing guard rejected an identity other than personal account 345874.')
    account = {'account_id': user['id'], 'credit_usd': user.get('credit'),
               'balance': user.get('balance'), 'total_spend': user.get('total_spend')}
    if args.action == 'snapshot':
        rows = call('GET', '/v1/instances/', params={'limit': 100}).get('instances', [])
        result = {'account': account, 'instances': [{k:r.get(k) for k in INSTANCE_FIELDS} for r in rows]}
    elif args.action == 'resources':
        instances = call('GET', '/v1/instances/', params={'limit': 100})['instances']
        volumes = call('GET', '/v0/volumes')['volumes']
        endpoints = call('GET', '/v0/endptjobs')['results']
        workergroups = call('GET', '/v0/workergroups')['results']
        assert all(isinstance(rows, list) for rows in (instances, volumes, endpoints, workergroups))
        result = {'account': account,
                  'instances': [{k:r.get(k) for k in INSTANCE_FIELDS} for r in instances],
                  'volumes': [{'id':r.get('id'), 'size':r.get('size'), 'dph_total':r.get('dph_total')} for r in volumes],
                  'endpoint_count': len(endpoints), 'workergroup_count': len(workergroups),
                  'all_billable_resource_lists_empty': not any((instances, volumes, endpoints, workergroups))}
    elif args.action == 'create':
        if args.id is None or args.body is None:
            raise SystemExit('Create requires an offer ID and an explicit body file.')
        body = json.loads(args.body.read_text())
        if body.get('client_id') != 'me' or body.get('disk') != 140:
            raise SystemExit('Create body does not match this personal 140GB pilot rental.')
        result = {'account': account, 'creation': call('PUT', f'/v0/asks/{args.id}/', body)}
    else:
        if args.id is None:
            raise SystemExit('An exact instance ID is required.')
        row = call('GET', f'/v0/instances/{args.id}/', params={'owner': 'me'}).get('instances')
        if not row or row.get('client_id', ACCOUNT_ID) != ACCOUNT_ID:
            raise SystemExit('The requested instance is not owned by the personal account.')
        if args.action == 'instance':
            result = {'account': account, 'instance': {k:row.get(k) for k in INSTANCE_FIELDS}}
        elif args.action == 'stop':
            result = {'account': account, 'stop': call('PUT', f'/v0/instances/{args.id}/', {'state':'stopped'})}
        else:
            result = {'account': account, 'destruction': call('DELETE', f'/v0/instances/{args.id}/', {})}
    result = redact(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
