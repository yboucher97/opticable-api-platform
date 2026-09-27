#!/usr/bin/env python3
"""Encrypted, resumable single-bucket upload; never deletes remote objects."""
import configparser
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = 'optibrain-recovery-prod'

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def atomic(path, data):
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(name, path)
    syncdir(path.parent)

def protected(path, private=False):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & (0o077 if private else 0o022):
        raise RuntimeError('unsafe protected-file ownership or mode')

def audit(root, event, **fields):
    with open(root / 'audit.jsonl', 'a') as f:
        f.write(json.dumps(dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(), event=event, **fields), sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())
    print(event, flush=True)

def create_only_header(params, **kwargs):
    # Ubuntu botocore predates the IfNoneMatch model field; sign the header.
    params['headers']['If-None-Match'] = '*'

def head(client, key):
    try:
        return client.head_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        if e.response.get('ResponseMetadata', {}).get('HTTPStatusCode') == 404:
            return None
        raise

def transfer(client, path, key, root):
    digest = sha(path)
    remote = head(client, key)
    if remote is None:
        audit(root, 'put_intent', key=key, sha256=digest)
        try:
            with open(path, 'rb') as body:
                client.put_object(Bucket=BUCKET, Key=key, Body=body,
                                  ContentLength=path.stat().st_size,
                                  Metadata={'sha256': digest},
                                  ContentType='application/json' if key.endswith('.json') else 'application/octet-stream')
        except ClientError as e:
            if e.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 412:
                raise
            # An ambiguous prior request or concurrent create may have succeeded.
        audit(root, 'put_reconciled', key=key)
        remote = head(client, key)
    if remote is None or remote.get('Metadata', {}).get('sha256') != digest or remote.get('ContentLength') != path.stat().st_size:
        raise RuntimeError('remote conflict; overwrite forbidden')
    # Stream all downloaded bytes and compare independently of supplied metadata.
    response = client.get_object(Bucket=BUCKET, Key=key, IfMatch=remote['ETag'])
    h = hashlib.sha256()
    count = 0
    try:
        for block in response['Body'].iter_chunks(chunk_size=1024 * 1024):
            h.update(block)
            count += len(block)
    finally:
        response['Body'].close()
    if h.hexdigest() != digest or count != path.stat().st_size:
        raise RuntimeError('downloaded object checksum mismatch')
    audit(root, 'download_hash_verified', key=key, sha256=digest)

def run(client, archive, recipient, root, verifier):
    generation = re.fullmatch(r'optibrain-backup-(\d{8}T\d{6}Z)\.tar\.gz', archive.name)
    if not generation:
        raise RuntimeError('invalid generation name')
    generation = generation[1]
    digest = sha(archive)
    if archive.with_name(archive.name + '.sha256').read_text().split()[0] != digest:
        raise RuntimeError('archive checksum mismatch')
    subprocess.run([str(verifier), '--verify', str(archive)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    if archive.stat().st_size > 4 * 1024**3:
        raise RuntimeError('archive exceeds bounded single-object upload limit')
    directory = root / generation
    directory.mkdir(mode=0o700, exist_ok=True)
    manifest = directory / 'prepared.json'
    encrypted = directory / 'archive.tar.gz.age'
    key = f'backups/{generation[:4]}/{generation[4:6]}/{generation[6:8]}/{generation}.tar.gz.age'
    recipient_hash = hashlib.sha256(recipient.encode()).hexdigest()
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if data['source_sha256'] != digest or data['recipient_sha256'] != recipient_hash or data['encrypted_sha256'] != sha(encrypted):
            raise RuntimeError('spool conflict; preserve and inspect generation')
    else:
        # No remote operation occurs before this durable preparation checkpoint.
        partial = directory / 'encryption.partial'
        if partial.exists():
            partial.unlink()
        subprocess.run(['age', '-r', recipient, '-o', str(partial), str(archive)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        with open(partial, 'rb') as f:
            if f.read(len(b'age-encryption.org/v1\n')) != b'age-encryption.org/v1\n':
                raise RuntimeError('missing AGE header')
            os.fsync(f.fileno())
        os.replace(partial, encrypted)
        syncdir(directory)
        data = dict(format_version=2, generation=generation, object_key=key,
                    source_sha256=digest, encrypted_sha256=sha(encrypted),
                    recipient_sha256=recipient_hash, offline_restore_verified=False)
        atomic(manifest, data)
        audit(root, 'encryption_prepared', generation=generation)
    transfer(client, encrypted, key, root)
    transfer(client, manifest, key + '.json', root)
    atomic(root / 'state.json', dict(data, verification_status='download_hash_verified',
           verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    audit(root, 'generation_verified', generation=generation)

def main():
    if os.geteuid() != 0:
        raise RuntimeError('root required')
    os.umask(0o077)
    config = Path('/etc/optibrain/phase2a.conf')
    protected(config)
    values = {}
    for line in config.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = shlex.split(value)[0]
    account = values['OPTIBRAIN_PHASE2A_ACCOUNT_ID']
    if not re.fullmatch('[0-9a-f]{32}', account):
        raise RuntimeError('invalid account')
    credential = Path('/etc/optibrain/r2-uploader.env')
    protected(credential, private=True)
    cp = configparser.ConfigParser()
    cp.read(credential)
    client = boto3.client('s3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com',
        aws_access_key_id=cp['default']['aws_access_key_id'],
        aws_secret_access_key=cp['default']['aws_secret_access_key'], region_name='auto',
        config=Config(signature_version='s3v4', connect_timeout=20, read_timeout=120,
                      retries={'mode': 'standard', 'total_max_attempts': 4}))
    client.meta.events.register('before-call.s3.PutObject', create_only_header)
    recipient_file = Path('/etc/optibrain/age-recipient')
    protected(recipient_file)
    recipient = recipient_file.read_text().strip()
    if not re.fullmatch('age1[0-9a-z]+', recipient):
        raise RuntimeError('invalid public recipient')
    root = Path('/var/lib/optibrain/phase2a')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o077:
        raise RuntimeError('unsafe spool directory')
    with open(root / 'lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            archives = sorted(Path('/var/backups/optibrain').glob('optibrain-backup-*.tar.gz'))
            if not archives:
                raise RuntimeError('no local archive')
            run(client, archives[-1], recipient, root,
                Path(__file__).with_name('optibrain-backup.sh'))
        except Exception as e:
            # Keep prior success but make latest failure visible and durable.
            atomic(root / 'last-failure.json', {'error_type': type(e).__name__,
                'time': datetime.datetime.now(datetime.timezone.utc).isoformat()})
            audit(root, 'upload_failed', error_type=type(e).__name__)
            raise

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Phase 2A stopped: ' + type(e).__name__ + '; inspect protected state; no remote deletion performed.', file=sys.stderr)
        sys.exit(1)
