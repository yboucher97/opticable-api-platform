"""Verified generation selection and bounded, hash-checked restore staging."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

from common import RebuildError, atomic_json, database_snapshot, digest, file_hash, path_at, private_file, require

STATE_ROOTS = ('/var/lib/opticable-workflow-api', '/var/lib/optibrain',
               '/var/lib/opticable-password-pdf', '/var/lib/opticable-omada-site',
               '/var/lib/opticable-api-platform/shared')
ENV_FILES = tuple('/etc/' + name + '.env' for name in
                  ('opticable-workflow-api', 'opticable-password-pdf', 'opticable-omada-site'))
POLICY_FILES = {'/etc/optibrain/mutation-control.json', '/etc/optibrain/customer-communication-control.json',
                '/etc/optibrain/conversion-export-control.json', '/etc/optibrain/rebuild-safety.env',
                '/etc/optibrain/lifecycle-runtime.json', '/etc/optibrain/customer-communications-runtime.json',
                '/etc/optibrain/authorize-persistent-codex-development'}


def relative(name):
    require(isinstance(name, str) and name and '\\' not in name, 'unsafe_archive_path')
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and '.' not in p.parts and str(p) == name.rstrip('/'),
            'unsafe_archive_path')
    return p


def classify(path):
    if path.startswith('/etc/'):
        if path.endswith(('.env', '.pem', '.key', '.token')) or re.search(r'oauth|deploy-ed25519$', path): return 'SECRET'
        return 'SYSTEM CONFIG'
    if path.endswith(('.db-wal', '.db-shm', '.lock')): return 'TEMPORARY'
    if '/ms-playwright/' in path or '/node_modules/' in path or '/.cache/' in path or path.endswith('/zoho-access-cache.json'): return 'CACHE'
    if path.startswith(('/run/', '/tmp/', '/var/tmp/', '/var/log/')): return 'REGENERABLE'
    if '/phase2a/' in path: return 'ARCHIVE'
    if '/output/integrations/' in path or '/shared/zoho-oauth' in path: return 'SECRET'
    return 'DURABLE'  # Unknown business files are retained, never guessed disposable.


def selected(path):
    if path in POLICY_FILES or (path.startswith('/etc/') and 'authorization' in Path(path).name) or path.startswith('/etc/ssh/'):
        return False
    if path in ENV_FILES: return True
    if path.startswith(('/etc/optibrain/', '/etc/opticable-password-pdf/')): return True
    return any(path.startswith(root + '/') or path == root for root in STATE_ROOTS) and classify(path) not in {
        'CACHE', 'TEMPORARY', 'REGENERABLE', 'ARCHIVE'}


def select_generation(catalog, pin='latest-verified', source_sha=None):
    require(catalog.get('catalog_version') == 1 and isinstance(catalog.get('generations'), list), 'invalid_recovery_catalog')
    rows = catalog['generations']
    require(len({r.get('generation') for r in rows}) == len(rows), 'duplicate_recovery_generation')
    eligible = []
    for row in rows:
        require(re.fullmatch(r'\d{8}T\d{6}Z', str(row.get('generation', ''))), 'invalid_recovery_generation')
        if row.get('verification_status') != 'download_hash_verified': continue
        if row.get('backup_format_version') != '1': continue
        if source_sha and row.get('source_sha') != source_sha: continue
        if pin != 'latest-verified' and row['generation'] != pin: continue
        if not re.fullmatch('[0-9a-f]{40}', str(row.get('source_sha', ''))): continue
        if not all(re.fullmatch('[0-9a-f]{64}', str(row.get(k, ''))) for k in ('plaintext_sha256', 'ciphertext_sha256')): continue
        if not row.get('databases') or not row.get('expected_knowledge'): continue
        eligible.append(row)
    require(bool(eligible), 'no_verified_compatible_recovery')
    return max(eligible, key=lambda row: row['generation'])


def manifest_from_archive(archive):
    found = None
    with tarfile.open(archive, 'r|gz') as tar:
        names = set()
        for member in tar:
            relative(member.name)
            require(member.name not in names and (member.isfile() or member.isdir()), 'duplicate_or_link_archive_member')
            names.add(member.name)
            if re.fullmatch(r'generation-\d{8}T\d{6}Z/manifest.json', member.name):
                require(found is None and member.size < 32 * 1024**2, 'invalid_archive_manifest')
                found = json.load(tar.extractfile(member))
    require(found is not None, 'archive_manifest_missing')
    return found


def validate_manifest(manifest, row):
    require(manifest.get('backup_format_version') == '1' and manifest.get('timestamp') == row['generation'], 'wrong_recovery_generation')
    require(manifest.get('production_git_sha') == row['source_sha'] and manifest.get('application_version') == row['api_version'], 'recovery_source_mismatch')
    dbs = manifest.get('sqlite_databases', [])
    require(len(dbs) == len(row['databases']) and {r['backup_path'] for r in dbs} == set(row['databases']), 'database_inventory_mismatch')
    files = manifest.get('files', [])
    require(bool(files) and len({r['path'] for r in files}) == len(files), 'duplicate_or_empty_file_manifest')
    for f in files:
        relative(f['path'])
        require(type(f.get('size')) is int and f['size'] >= 0 and re.fullmatch('[0-9a-f]{64}', f.get('sha256', '')), 'invalid_file_manifest')
    metadata = manifest.get('source_metadata', [])
    require(bool(metadata), 'recovery_metadata_missing')
    by_path = {r['path']: r for r in files}
    destinations = {}
    for m in metadata:
        # Existing backup v1 emits a benign trailing '/.' for a copied root.
        # Normalize metadata only; actual archive member names remain strict.
        m['backup_path'] = m['backup_path'].removesuffix('/.')
        relative(m['backup_path'])
        name = m['source_path']
        require(name.startswith('/') and '..' not in Path(name).parts, 'unsafe_source_metadata')
        require(m['type'] in ('directory', 'file') and re.fullmatch('[0-7]{4}', m['mode']), 'unsafe_source_type_or_mode')
        require(not int(m['mode'], 8) & (0o5000 if m['type'] == 'directory' else 0o7000), 'special_mode_forbidden')
        if m['type'] == 'file':
            require(m['backup_path'] in by_path, 'uncovered_recovery_file')
        if name in destinations:
            require(destinations[name] == m['backup_path'], 'conflicting_recovery_destination')
        destinations[name] = m['backup_path']
    return by_path


def stage_archive(archive, row, destination, *, only_databases=False):
    """Verify ALL bytes, extract only selected durable files. No tar.extractall."""
    archive = Path(archive); destination = Path(destination)
    require(file_hash(archive) == row['plaintext_sha256'], 'archive_hash_mismatch')
    manifest = manifest_from_archive(archive)
    by_path = validate_manifest(manifest, row)
    require(not destination.exists(), 'staging_already_exists')
    destination.mkdir(mode=0o700, parents=True)
    database_paths = set(row['databases'])
    wanted = set(database_paths)
    if not only_databases:
        wanted.update(m['backup_path'] for m in manifest['source_metadata'] if m['type'] == 'file' and selected(m['source_path']))
        wanted.update(m['backup_path'] for m in manifest['source_metadata'] if m['source_path']=='/etc/optibrain/conversion-export-control.json' and m['type']=='file')
        wanted.update(f for f in by_path if f.startswith('source/'))
    needed_bytes = sum(by_path[n]['size'] for n in wanted)
    require(shutil.disk_usage(destination).free > needed_bytes + 64*1024**2, 'insufficient_staging_storage')
    prefix = 'generation-' + row['generation'] + '/'
    seen = set()
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            if not member.isfile(): continue
            require(member.name.startswith(prefix), 'foreign_archive_generation')
            name = member.name[len(prefix):]
            if name == 'manifest.json': continue
            require(name in by_path, 'unmanifested_archive_file')
            item = by_path[name]
            require(member.size == item['size'], 'archive_member_size_mismatch')
            import hashlib
            h = hashlib.sha256(); count = 0
            output = None
            if name in wanted:
                path = path_at(destination, '/' + name)
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                output = path.open('xb')
            try:
                with tar.extractfile(member) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(block); count += len(block)
                        if output: output.write(block)
            finally:
                if output: output.close()
            require(count == item['size'] and h.hexdigest() == item['sha256'], 'archive_member_hash_mismatch')
            seen.add(name)
    require(seen == set(by_path), 'archive_files_missing')
    snapshots = {}
    for name in sorted(database_paths):
        snapshots[name] = database_snapshot(destination / name)
    require(snapshots == row['expected_knowledge'], 'knowledge_snapshot_mismatch')
    atomic_json(destination / 'verified.json', {'generation': row['generation'], 'plaintext_sha256': row['plaintext_sha256'],
                'source_sha': row['source_sha'], 'databases': snapshots, 'files_verified': len(seen), 'selected_bytes': needed_bytes})
    return manifest, snapshots


def build_catalog(archive, uploaded, workspace):
    """Source-side read-only snapshot descriptor, no backup creation/deletion."""
    manifest = manifest_from_archive(archive)
    require(uploaded.get('verification_status') == 'download_hash_verified' and uploaded['generation'] == manifest['timestamp'], 'unverified_catalog_source')
    row = {'generation': manifest['timestamp'], 'source_sha': manifest['production_git_sha'],
           'api_version': manifest['application_version'], 'backup_format_version': manifest['backup_format_version'],
           'verification_status': uploaded['verification_status'], 'verified_at': uploaded['verified_at'],
           'plaintext_sha256': uploaded['source_sha256'], 'ciphertext_sha256': uploaded['encrypted_sha256'],
           'object_key': uploaded['object_key'], 'recipient_sha256': uploaded['recipient_sha256'],
           'plaintext_bytes': Path(archive).stat().st_size, 'offline_restore_verified': uploaded.get('offline_restore_verified', False),
           'expanded_bytes': sum(f['size'] for f in manifest['files']),
           'databases': [r['backup_path'] for r in manifest['sqlite_databases']], 'expected_knowledge': {}}
    # One online snapshot file at a time, outside the full-archive extraction path.
    require(file_hash(archive) == row['plaintext_sha256'], 'catalog_plaintext_hash_mismatch')
    lookup = {f['path']: f for f in manifest['files']}
    db_names = set(row['databases']); seen = set()
    with tempfile.TemporaryDirectory(dir=workspace, prefix='rebuild-db-reference-') as temporary:
        with tarfile.open(archive, 'r|gz') as tar:
            for member in tar:
                name = member.name.removeprefix('generation-' + row['generation'] + '/')
                if name not in db_names: continue
                require(member.isfile() and name not in seen, 'invalid_database_archive_member')
                seen.add(name)
                path = Path(temporary) / 'snapshot.db'
                with tar.extractfile(member) as source, path.open('wb') as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                require(file_hash(path) == lookup[name]['sha256'], 'reference_database_hash_mismatch')
                row['expected_knowledge'][name] = database_snapshot(path)
                path.unlink()  # Only a generated disposable copied database.
    require(seen == db_names, 'reference_database_missing')
    validate_manifest(manifest, row)
    return {'catalog_version': 1, 'generations': [row], 'trust': 'Authenticated source-host export or reviewed pinned repository; never an untrusted URL'}
