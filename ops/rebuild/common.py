"""Small shared recovery primitives. Never print subprocess output or credentials."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import types
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


class RebuildError(ValueError):
    """Only fixed, nonsecret messages may be used here."""


def require(ok, code):
    if not ok:
        raise RebuildError(code)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def command(args, *, timeout=60, env=None, cwd=None):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                            timeout=timeout, env=env, cwd=cwd)
    require(result.returncode == 0, 'command_failed:' + Path(str(args[0])).name)
    return result.stdout.strip()


def path_at(root, name):
    root = Path(root)
    require(root.is_absolute() and root == root.resolve(), 'noncanonical_root')
    require(isinstance(name, str) and name.startswith('/') and '..' not in Path(name).parts,
            'unsafe_destination')
    path = root / name.lstrip('/')
    for p in (path, *path.parents):
        if p == root.parent:
            break
        require(not p.is_symlink(), 'symlink_destination')
        if p == root:
            break
    return path


def atomic_json(path, value, mode=0o600):
    atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode(), mode)


def atomic_bytes(path, data, mode=0o600):
    path = Path(path)
    require(not path.is_symlink(), 'symlink_write')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if Path(name).exists(): Path(name).unlink()


def private_file(path, *, owner=0):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == owner and not info.st_mode & 0o077,
            'untrusted_private_file')


def trusted_manifest(path):
    """Metadata can be readable, but no unprivileged party may replace it."""
    path=Path(path).absolute()
    for item in (path,*path.parents):
        info=item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,
                'untrusted_root_manifest')


def toolchain_code_hash():
    paths=sorted((REPO/'ops/rebuild').rglob('*'))
    return digest({str(p.relative_to(REPO)):file_hash(p) for p in paths
                   if p.is_file() and p.suffix in {'.py','.sh','.service','.timer','.conf','.caddy'}})


def env_file(path):
    """Parse data, never source an archived shell environment."""
    values = {}
    for line in Path(path).read_text().splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            key = key.removeprefix('export ').strip()
            require(re.fullmatch('[A-Z][A-Z0-9_]*', key), 'invalid_environment_key')
            values[key] = value.strip().strip('"').strip("'")
    return values


class Audit:
    """Reuse universal Action Evidence schema/tables in a recovery-only sidecar.

    The sidecar is outside the restored business DB, so exact snapshot hashes
    survive. Control Center may ingest its canonical envelopes later.
    """
    def __init__(self, path, versions=None):
        # Load the unchanged stdlib-only canonical implementation without the
        # application's package __init__ (which needs pydantic before apt/venv).
        # Relative imports still resolve to the real reviewed source modules.
        package_name='_optibrain_rebuild_canonical'
        if package_name not in sys.modules:
            package=types.ModuleType(package_name)
            package.__path__=[str(REPO/'apps/workflow-api/workflow/automation')]
            sys.modules[package_name]=package
        module=importlib.import_module(package_name+'.action_evidence')
        self.store = module.ActionEvidence(path)
        self.envelope = module.envelope
        self.versions = versions or {}
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextmanager
    def step(self, what, target, before, proposed, *, risk='Replacement host remains contained',
             rollback='Stop replacement services; retain old host and previous restored generation',
             mutation=True):
        started = datetime.now(timezone.utc)
        aid = 'rebuild:' + uuid.uuid4().hex
        plan = self.envelope(aid, 'rebuild.' + what, {'type': 'RECOVERY', 'identity': target}, started,
            initiator='OWNER_AUTHORIZED_ENGINEERING', trigger='explicit:rebuild-mission',
            before_state=before, proposed_state=proposed, reason='Reconstruct verified OptiBrain safely',
            business_rationale='Preserve business knowledge and rollback while keeping consequential writers OFF',
            risks=[risk], evidence_refs=[{'type': 'READBACK', 'identity': aid}],
            rollback_capability='REVERSIBLE_WITH_LIMITATIONS', rollback_target={'host': target},
            rollback_procedure=rollback, authority_class='REPLACEMENT_HOST_RECOVERY',
            automatic_rule='Explicit marked replacement only; no routing or business authority',
            mutation=mutation, exact_versions=self.versions)
        self.store.plan(plan, started)
        self.store.start(aid, started, authority_check=lambda: None)
        result = {}
        try:
            yield result
        except BaseException as exc:
            self.store.finish(aid, datetime.now(timezone.utc), provider_success=False,
                              failure={'stage':'REBUILD_OPERATION','error_class':type(exc).__name__,
                                  'provider_status':None,'safe_details':str(exc) if isinstance(exc,RebuildError) else type(exc).__name__,
                                  'partial_effects':'POSSIBLE; retained staging and operation evidence',
                                  'recovery_action':'Keep replacement contained; inspect readback and rerun the same verified generation'})
            raise
        else:
            require(bool(result), 'audit_readback_required')
            self.store.finish(aid, datetime.now(timezone.utc), provider_success=True,
                              actual_after=result, verified=True)


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def database_snapshot(path):
    """Consistent read transaction; full row/identity digests, never business text.

    Every present table is covered, including future nonzero learning records.
    SQLite online snapshots have no WAL; live mode=ro respects current WAL.
    """
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'database_integrity_failed')
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'database_foreign_keys_failed')
        schemas = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"))
        tables = {}
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            q = quote_ident(name)
            columns = list(db.execute('PRAGMA table_info(' + q + ')'))
            pk = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
            order = ','.join(quote_ident(c) for c in pk) if pk else ','.join(str(i+1) for i in range(len(columns)))
            h = hashlib.sha256(); identities = hashlib.sha256(); count = 0
            for row in db.execute('SELECT * FROM ' + q + ' ORDER BY ' + order):
                value = [({'blob_hex': v.hex()} if isinstance(v, bytes) else v) for v in row]
                h.update((json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
                identity = [value[i] for i, c in enumerate(columns) if c[1] in pk] if pk else value
                identities.update((json.dumps(identity, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
                count += 1
            tables[name] = {'count': count, 'rows_sha256': h.hexdigest(), 'ids_sha256': identities.hexdigest()}
        require(bool(tables), 'database_schema_empty')
        chains = 0
        if 'action_evidence' in tables:
            previous = {}
            for aid, kind, at, raw, prior, checksum in db.execute(
                    'SELECT action_id,kind,recorded_at,evidence_json,previous_hash,event_hash FROM action_evidence ORDER BY event_id'):
                require(prior == previous.get(aid, '') and checksum == digest([aid, kind, at, raw, prior]),
                        'audit_chain_failed')
                previous[aid] = checksum
            chains = len(previous)
        return {'integrity': 'ok', 'foreign_keys': 'PASS', 'user_version': db.execute('PRAGMA user_version').fetchone()[0],
                'schema_sha256': digest(schemas), 'tables': tables, 'audit_chains_verified': chains}
