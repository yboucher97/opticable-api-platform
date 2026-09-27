#!/usr/bin/env python3
"""Validate a checksum-pinned archive in disposable isolated staging, never live paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tarfile
import tempfile


class DrillError(Exception):
    """Fixed non-secret diagnostic suitable for the journal."""


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise DrillError('unsafe archive path')
    return p


def extract(archive, destination):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        names = set()
        for member in members:
            name = relative(member.name)
            if str(name) in names or not (member.isfile() or member.isdir()):
                raise DrillError('duplicate or unsupported archive member')
            names.add(str(name))
        tar.extractall(destination, members=members, filter='data')


def validate(archive, expected_sha, workspace):
    if digest(archive) != expected_sha:
        raise DrillError('archive does not match human-verified plaintext')
    with tempfile.TemporaryDirectory(prefix='drill-', dir=workspace) as temporary:
        scratch = Path(temporary)
        extract(archive, scratch)
        roots = list(scratch.glob('generation-*'))
        if len(roots) != 1:
            raise DrillError('unexpected generation layout')
        root = roots[0]
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest.get('backup_format_version') != '1':
            raise DrillError('unsupported manifest')
        files = manifest['files']
        if not files or not manifest['sqlite_databases'] or not manifest['source_metadata']:
            raise DrillError('missing recovery inventory')
        seen = set()
        for item in files:
            name = str(relative(item['path']))
            if name in seen:
                raise DrillError('duplicate manifest file')
            seen.add(name)
            p = root / name
            if not p.is_file() or p.stat().st_size != item['size'] or digest(p) != item['sha256']:
                raise DrillError('file verification failed')
        actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
        omitted = actual - seen - {'manifest.json'}
        legacy_prefix = 'state/var/lib/opticable-omada-site/ms-playwright/chromium-1208/chrome-linux64/'
        legacy = {legacy_prefix + name + '/manifest.json' for name in
                  ['MEIPreload', 'PrivacySandboxAttestationsPreloaded', 'WidevineCdm', 'hyphen-data']}
        if seen - actual or (omitted and not (manifest.get('backup_script_version') == '1.0.0' and omitted <= legacy)):
            raise DrillError('manifest does not cover archive files')
        metadata = {}
        excluded_sqlite_sidecars = 0
        for item in manifest['source_metadata']:
            name = str(relative(item['backup_path']))
            if not re.fullmatch('[0-7]{4}', item['mode']) or not all(isinstance(item[k], int) and item[k] >= 0 for k in ('uid', 'gid')):
                raise DrillError('invalid recovery ownership metadata')
            p = root / name
            if (not p.exists() and manifest.get('backup_script_version') == '1.0.0'
                    and name in {'state/var/lib/opticable-workflow-api/output/automation/automation.db-wal',
                                 'state/var/lib/opticable-workflow-api/output/automation/automation.db-shm'}):
                excluded_sqlite_sidecars += 1
                continue  # Consistent SQLite snapshot supersedes transient WAL/SHM.
            if item['type'] not in ('file', 'directory') or not p.exists():
                raise DrillError('metadata target unavailable')
            metadata[name] = item
        # Restore each database into a second, isolated location and open that copy.
        db_restore = scratch / 'restored-database'
        db_restore.mkdir(mode=0o700)
        for i, item in enumerate(manifest['sqlite_databases']):
            db = root / relative(item['backup_path'])
            restored = db_restore / f'{i}.db'
            shutil.copyfile(db, restored)
            os.chmod(restored, 0o600)
            with sqlite3.connect(f'file:{restored}?mode=ro', uri=True) as con:
                if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise DrillError('restored SQLite integrity failed')
                if not con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]:
                    raise DrillError('restored database has no tables')
        # Extract the versioned source bundle without executing recovered code.
        sha = manifest['production_git_sha']
        if not re.fullmatch('[0-9a-f]{40}', sha):
            raise DrillError('invalid release identity')
        source = root / 'source' / f'opticable-api-platform-{sha}.tar.gz'
        restored_source = scratch / 'restored-source'
        restored_source.mkdir(mode=0o700)
        extract(source, restored_source)
        release = restored_source / f'opticable-api-platform-{sha}'
        if not (release / 'apps/workflow-api/workflow/api.py').is_file():
            raise DrillError('recovered application source missing')
        # Recover critical config into staging and exercise uid/gid/mode replay.
        critical = ['system/etc/opticable-workflow-api.env',
                    'system/etc/optibrain/github-app.pem',
                    'system/etc/systemd/system/opticable-workflow-api.service']
        for i, name in enumerate(critical):
            item = metadata[name]
            restored = scratch / f'restored-config-{i}'
            shutil.copyfile(root / name, restored)
            os.chown(restored, item['uid'], item['gid'])
            os.chmod(restored, int(item['mode'], 8))
            s = restored.stat()
            if (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) != (item['uid'], item['gid'], int(item['mode'], 8)):
                raise DrillError('ownership restore mismatch')
            if digest(restored) != digest(root / name):
                raise DrillError('restored config changed')
        return dict(result='PASS', source_sha256=expected_sha,
                    generation=manifest['timestamp'], source_commit=sha,
                    files_verified=len(files), legacy_files_covered_by_archive_hash_only=len(omitted),
                    metadata_entries_validated=len(metadata),
                    legacy_transient_sqlite_metadata_omissions=excluded_sqlite_sidecars,
                    databases_restored=len(manifest['sqlite_databases']),
                    critical_configs_restored=len(critical), source_extraction='PASS',
                    scope='isolated archive/database/config/source validation; no services started')


def main():
    if os.geteuid() != 0:
        raise DrillError('root required for protected archive and ownership drill')
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('expected_sha256')
    args = parser.parse_args()
    workspace = Path('/var/lib/optibrain/restore-drills')
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    if workspace.is_symlink() or workspace.stat().st_uid != 0 or workspace.stat().st_mode & 0o077:
        raise DrillError('unsafe drill workspace')
    result = validate(args.archive, args.expected_sha256, workspace)
    # Persist only non-secret results; extracted credential-bearing staging is removed.
    output = workspace / (result['generation'] + '-result.json')
    with output.open('x') as f:
        json.dump(result, f, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Isolated restore drill FAILED: ' + (str(e) if isinstance(e, DrillError) else type(e).__name__) + '; no production restore performed.')
        raise SystemExit(1)
