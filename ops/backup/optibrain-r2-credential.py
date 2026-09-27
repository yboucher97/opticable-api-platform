#!/usr/bin/env python3
"""One-time least-privilege bootstrap. Never prints credential values."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import urllib.error
import urllib.request

DEST = Path('/etc/optibrain/r2-uploader.env')
NAME = 'optibrain-recovery-uploader'
BUCKET = 'optibrain-recovery-prod'

def main():
    if os.geteuid() != 0:
        raise RuntimeError('root required')
    os.umask(0o077)
    if DEST.exists():
        raise RuntimeError('credential already exists; inspect scope before reuse')
    account = None
    for line in Path('/etc/opticable-workflow-api.env').read_text().splitlines():
        m = re.match(r'^(?:export\s+)?CLOUDFLARE_ACCOUNT_ID\s*=(.*)$', line)
        if m:
            account = shlex.split(m[1])[0]
    if not account or not re.fullmatch('[0-9a-f]{32}', account):
        raise RuntimeError('invalid account configuration')
    token = Path('/etc/optibrain/cloudflare-test-token').read_text().strip()
    base = 'https://api.cloudflare.com/client/v4/accounts/' + account

    def api(path, body=None):
        request = urllib.request.Request(base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError('provider HTTP ' + str(error.code)) from None
        if data.get('success') is not True:
            raise RuntimeError('provider operation unsuccessful; reconcile before retry')
        return data['result']

    existing = api('/tokens')
    if any(t.get('name') == NAME for t in existing):
        raise RuntimeError('named token already exists; do not create a duplicate')
    groups = api('/tokens/permission_groups')
    selected = [g for g in groups if g.get('name') == 'Workers R2 Storage Bucket Item Write']
    if len(selected) != 1:
        raise RuntimeError('unable to identify unique bucket object write permission')
    policy = {'effect': 'allow', 'resources': {
        f'com.cloudflare.edge.r2.bucket.{account}_default_{BUCKET}': '*'},
        'permission_groups': [{'id': selected[0]['id']}]}
    # Precreate root-only response destination before the non-retryable POST.
    raw = Path('/etc/optibrain/r2-uploader-bootstrap-response.json')
    fd = os.open(raw, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        result = api('/tokens', {'name': NAME, 'policies': [policy]})
        json.dump(result, out)
        out.flush()
        os.fsync(out.fileno())
    # Preserve response in root-only recovery custody if subsequent work fails.
    identifier, value = result['id'], result['value']
    if not re.fullmatch('[0-9a-f]{32}', identifier) or not value:
        raise RuntimeError('unexpected token result; protected response retained')
    details = api('/tokens/' + identifier)
    policies = details.get('policies', [])
    if len(policies) != 1 or policies[0].get('effect') != 'allow' or policies[0].get('resources') != policy['resources'] or {g['id'] for g in policies[0].get('permission_groups', [])} != {selected[0]['id']}:
        raise RuntimeError('scope verification failed; protected response retained')
    fd = os.open(DEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write('[default]\naws_access_key_id = ' + identifier + '\naws_secret_access_key = ' + hashlib.sha256(value.encode()).hexdigest() + '\n')
        out.flush()
        os.fsync(out.fileno())
    raw.unlink()
    print('Dedicated R2 credential created; single-bucket object-write scope verified; root-only credentials saved.')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not render provider response bodies or arbitrary exception contents.
        print('Credential bootstrap stopped (' + type(error).__name__ + '); reconcile protected state before retry.')
        raise SystemExit(1)
