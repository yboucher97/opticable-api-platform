"""Conservative disposable-file lifecycle. Production defaults to read-only planning.

Root monitor reuses its timer and the business execution lock. Source directories
are untrusted: move without replacement into a root-only quarantine, then verify
the exact moved inode. Final unlink is possible only in that sealed directory.
"""
from contextlib import contextmanager
import ctypes
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat

import storage

QUARANTINE = Path('/var/lib/optibrain/resource-management/disposable-quarantine')
REPORT = Path('/var/lib/optibrain/resource-management/business-storage-latest.json')


@contextmanager
def directory(path, owners):
    """Open every absolute component with O_NOFOLLOW; retain the final dirfd."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts: raise ValueError('Absolute allowlisted path required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parts[1:]:
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt; st = os.fstat(fd)
            sticky_root = st.st_uid == 0 and bool(st.st_mode & stat.S_ISVTX)
            if st.st_uid not in owners or (st.st_mode & 0o022 and not sticky_root):
                raise PermissionError('Untrusted directory ownership/mode')
        yield fd
    finally:
        os.close(fd)


def identity(fd, name, owner):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        st = os.fstat(f)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != owner or st.st_mode & 0o022:
            raise ValueError('Regular single-link owned file required')
        h = sha256()
        while True:
            data = os.read(f, 1024 * 1024)
            if not data: break
            h.update(data)
        end = os.fstat(f)
        if (st.st_size, st.st_mtime_ns, st.st_ctime_ns) != (end.st_size, end.st_mtime_ns, end.st_ctime_ns):
            raise ValueError('File changed while hashing')
        return {'dev': st.st_dev, 'ino': st.st_ino, 'bytes': st.st_size,
                'mtime_ns': st.st_mtime_ns, 'ctime_ns': st.st_ctime_ns,
                'uid': st.st_uid, 'sha256': h.hexdigest(), 'allocated_bytes': st.st_blocks * 512}
    finally:
        os.close(f)


def same_inode(a, b):
    return all(a[k] == b[k] for k in ('dev', 'ino', 'bytes', 'mtime_ns', 'uid', 'sha256'))


def active_handles(value):
    """Root-only removal refuses live descriptors/mappings, including deleted names."""
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    s = fd.stat()
                    if (s.st_dev, s.st_ino) == (value['dev'], value['ino']): return True
                except FileNotFoundError: pass
            for line in (process / 'maps').read_text().splitlines():
                parts = line.split()
                if len(parts) >= 5 and int(parts[4]) == value['ino']:
                    major, minor = (int(x, 16) for x in parts[3].split(':'))
                    if os.makedev(major, minor) == value['dev']: return True
        except (FileNotFoundError, ProcessLookupError): pass
        # Permission failure is uncertainty, not proof of absence.
    return False


def sealed(path):
    if not path.exists(): path.mkdir(mode=0o700)
    if path.lstat().st_uid != 0 or stat.S_IMODE(path.lstat().st_mode) != 0o700:
        raise PermissionError('Sealed root-owned quarantine required')


def allowed(item, policy, root):
    kind = storage.family(item)
    base = {'marketing': 'artifacts', 'recommendation': 'artifacts',
            'temporary_test': 'temporary', 'private_staging': 'disposable-previews'}.get(kind)
    if base is None: raise ValueError('No disposable path family')
    expected = Path(root) / base
    if str(expected) not in policy['allowlisted_roots']: raise ValueError('Outside exact allowlist')
    relative = Path(item['path'])
    if relative.is_absolute() or '..' in relative.parts or not relative.parts or any(p.startswith('.') for p in relative.parts):
        raise ValueError('Unsafe disposable relative path')
    if item.get('local_root') != str(expected): raise ValueError('Registry root mismatch')
    return expected / relative


def plan(db, root, now, owner, policy=storage.POLICY):
    assets, decisions, states, reservations, holds = storage.metadata(db)
    paths = {}
    for a in assets: paths.setdefault((a.get('local_root'), a['path']), set()).add(a['sha256'])
    rows = []
    for item in assets:
        aid = storage.operation_id(item); state = states.get(aid, {})
        row = {'path': str(Path(item.get('local_root', str(Path(root) / 'artifacts'))) / item['path']),
               'sha256': item['sha256'], 'logical_path': item.get('logical_path'),
               'category': storage.family(item), 'registered_at': item['registered_at'],
               'operation_id': aid, 'action': 'KEEP', 'reason': storage.protection(item, decisions, holds),
               'bytes': item.get('bytes', 0)}
        if state.get('state') in ('QUARANTINED', 'DELETE_INTENT', 'DELETED', 'QUARANTINE_INTENT', 'RECONCILE_HOLD'):
            row.update(action='KEEP', reason='lifecycle_' + state['state'].lower()); rows.append(row); continue
        if len(paths[(item.get('local_root'), item['path'])]) != 1: row['reason'] = 'conflicting_file_identity'
        if row['reason']: rows.append(row); continue
        try:
            path = allowed(item, policy, root)
            with directory(path.parent, {0, owner}) as fd: ident = identity(fd, path.name, owner)
            if ident['sha256'] != item['sha256'] or ident['bytes'] != item.get('bytes'):
                raise ValueError('Registered content identity changed')
            age_from = max(storage.timestamp(item['registered_at']),
                           storage.timestamp(item.get('last_interaction_at') or item['registered_at']),
                           datetime.fromtimestamp(ident['mtime_ns'] / 1e9, timezone.utc))
            days = {'temporary_test': policy['temporary_days'], 'private_staging': policy['staging_days']}.get(row['category'], policy['draft_days'])
            expires = age_from + timedelta(days=days)
            row.update(identity=ident, bytes=ident['bytes'], expires_at=expires.isoformat(), retention_days=days,
                       action='QUARANTINE_CANDIDATE' if now >= expires else 'KEEP',
                       reason='expired_unused_disposable' if now >= expires else 'within_retention')
        except (OSError, ValueError) as error:
            row.update(action='MANUAL_REVIEW', reason=type(error).__name__ + ': ' + str(error))
        rows.append(row)
    candidates = [r for r in rows if r['action'] == 'QUARANTINE_CANDIDATE']
    return {'schema': 1, 'at': now.isoformat(), 'policy_sha256': storage.digest(policy), 'mode': 'DRY_RUN',
            'registered_items': len(assets), 'rows': rows, 'eligible_files': len(candidates),
            'eligible_logical_bytes': sum(r['bytes'] for r in candidates),
            'eligible_allocated_bytes': sum(r['identity']['allocated_bytes'] for r in candidates),
            'immediate_free_space_savings': 0,
            'expected_final_deletion_bytes': sum(r['identity']['allocated_bytes'] for r in candidates),
            'note': 'Quarantine is a same-filesystem rename; savings occur only after a fresh 7-day quarantine and approval.'}


def code_digest():
    return storage.digest({p.name: sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(storage.__file__))})


def approval(policy, path=storage.APPROVAL_PATH):
    """File must be supplied by trusted owner administration, never by the worker."""
    try:
        path = Path(path)
        with directory(path.parent, {0}) as fd:
            rawfd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(rawfd) as f:
                st = os.fstat(f.fileno())
                if st.st_uid != 0 or st.st_nlink != 1 or not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
                    return None
                v = json.load(f)
        fields = {'schema', 'actor', 'approved_at', 'policy_sha256', 'cleanup_code_sha256', 'quarantine_enabled', 'permanent_deletion_enabled'}
        if set(v) != fields or v['schema'] != 1 or v['actor'] != 'owner:opticable': return None
        if v['policy_sha256'] != storage.digest(policy) or v['cleanup_code_sha256'] != code_digest(): return None
        if storage.timestamp(v['approved_at']) > datetime.now(timezone.utc): return None
        if type(v['quarantine_enabled']) is not bool or type(v['permanent_deletion_enabled']) is not bool: return None
        return v
    except (OSError, ValueError, KeyError): return None


def no_replace(srcfd, source, dstfd, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(srcfd, os.fsencode(source), dstfd, os.fsencode(destination), 1) != 0:
        e = ctypes.get_errno(); raise OSError(e, os.strerror(e))
    os.fsync(srcfd); os.fsync(dstfd)


def latest(db, aid):
    row = db.execute("SELECT evidence_json FROM action_evidence WHERE action_id=? AND kind='business_storage_lifecycle' ORDER BY event_id DESC LIMIT 1", (aid,)).fetchone()
    return json.loads(row[0]) if row else None


def event(db, aid, value, now):
    storage.append(db, aid, 'business_storage_lifecycle', value, now)


def execute(database, root, now, owner, policy=storage.POLICY, *, approval_path=storage.APPROVAL_PATH, quarantine=QUARANTINE):
    if os.geteuid() != 0: raise PermissionError('Root monitoring custody required')
    auth = approval(policy, approval_path)
    if not auth or not auth['quarantine_enabled']:
        return {'state': 'APPROVAL_REQUIRED', 'quarantined': 0, 'deleted': 0}
    # Caller holds existing business execution.lock. Reviewer transactions and
    # each filesystem effect also serialize on the existing SQLite writer lock.
    quarantine = Path(quarantine)
    sealed(quarantine)
    results = {'state': 'COMPLETED', 'quarantined': 0, 'deleted': 0, 'held': 0}
    def connect():
        db = sqlite3.connect(database, timeout=10); db.row_factory = sqlite3.Row; return db
    with connect() as db:
        current = plan(db, root, now, owner, policy)
        _, _, states, _, _ = storage.metadata(db)
    # Reconcile committed intent before considering fresh candidates. No second
    # operation is created for a replay of the same exact registry identity.
    work = {r['operation_id']: r for r in current['rows'] if r['action'] == 'QUARANTINE_CANDIDATE'}
    for aid, v in states.items():
        if v['state'] in ('QUARANTINE_INTENT', 'QUARANTINED', 'DELETE_INTENT'): work[aid] = v['candidate']
    for aid, candidate in list(sorted(work.items()))[:policy['max_cleanup_files_per_cycle']]:
        # Commit durable intent separately BEFORE rename/unlink. A crash can
        # therefore be reconciled from a fresh process without blind replay.
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if approval(policy, approval_path) != auth: raise PermissionError('Approval changed')
            state = latest(db, aid)
            if state and state['state'] in ('DELETED', 'RECONCILE_HOLD'): continue
            assets, decisions, _, _, holds = storage.metadata(db)
            item = next((a for a in assets if storage.operation_id(a) == aid), None)
            if not item or storage.protection(item, decisions, holds): results['held'] += 1; continue
            source = allowed(item, policy, root)
            if str(source) != candidate['path']: raise ValueError('Candidate path changed')
            qname = aid.split(':', 1)[1]
            if state is None:
                # Reclassify under the writer lock: stale plans cannot execute.
                fresh = next(r for r in plan(db, root, now, owner, policy)['rows'] if r['operation_id'] == aid)
                if fresh['action'] != 'QUARANTINE_CANDIDATE' or fresh['identity'] != candidate['identity']:
                    raise ValueError('Candidate changed since classification')
                if active_handles(candidate['identity']): results['held'] += 1; continue
                state = {'state': 'QUARANTINE_INTENT', 'candidate': candidate, 'quarantine_name': qname,
                         'policy_sha256': storage.digest(policy), 'intent_at': now.isoformat()}
                event(db, aid, state, now)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if approval(policy, approval_path) != auth: raise PermissionError('Approval changed')
            state = latest(db, aid)
            assets, decisions, _, _, holds = storage.metadata(db)
            if storage.protection(next(a for a in assets if storage.operation_id(a) == aid), decisions, holds):
                results['held'] += 1; continue
            with directory(quarantine, {0}) as qfd:
                if state['state'] == 'QUARANTINE_INTENT':
                    try: qi = identity(qfd, qname, owner)
                    except FileNotFoundError:
                        with directory(source.parent, {0, owner}) as sfd:
                            si = identity(sfd, source.name, owner)
                            if si != candidate['identity']: raise ValueError('Source identity changed')
                            if si['dev'] != os.fstat(qfd).st_dev: raise ValueError('Same-filesystem quarantine required')
                            no_replace(sfd, source.name, qfd, qname)
                        qi = identity(qfd, qname, owner)
                    if not same_inode(candidate['identity'], qi):
                        event(db, aid, {**state, 'state': 'RECONCILE_HOLD', 'reason': 'Moved identity mismatch; retained, never unlinked'}, now)
                        results['held'] += 1; continue
                    state = {**state, 'state': 'QUARANTINED', 'quarantined_at': now.isoformat(), 'quarantine_identity': qi}
                    event(db, aid, state, now); results['quarantined'] += 1
                    continue
                if state['state'] == 'QUARANTINED':
                    if not auth['permanent_deletion_enabled'] or now < storage.timestamp(state['quarantined_at']) + timedelta(days=policy['quarantine_days']): continue
                    qi = identity(qfd, qname, owner)
                    if qi != state['quarantine_identity']: raise ValueError('Quarantine identity changed')
                    if active_handles(qi): results['held'] += 1; continue
                    # Root-only quarantine directory prevents concurrent name
                    # replacement by the original service owner at final unlink.
                    state = {**state, 'state': 'DELETE_INTENT', 'delete_intent_at': now.isoformat()}
                    event(db, aid, state, now)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if approval(policy, approval_path) != auth: raise PermissionError('Approval changed')
            state = latest(db, aid)
            if state['state'] != 'DELETE_INTENT' or not auth['permanent_deletion_enabled']: continue
            assets, decisions, _, _, holds = storage.metadata(db)
            if storage.protection(next(a for a in assets if storage.operation_id(a) == aid), decisions, holds):
                results['held'] += 1; continue
            with directory(quarantine, {0}) as qfd:
                try: qi = identity(qfd, qname, owner)
                except FileNotFoundError: qi = None  # interrupted unlink with a durable DELETE_INTENT
                if qi:
                    if qi != state['quarantine_identity']: raise ValueError('Deletion identity changed')
                    if active_handles(qi): results['held'] += 1; continue
                    os.unlink(qname, dir_fd=qfd); os.fsync(qfd)
                event(db, aid, {**state, 'state': 'DELETED', 'deleted_at': now.isoformat(),
                               'disposable_content_retained': False}, now)
                results['deleted'] += 1
    return results


def monitor():
    """Called by existing resource monitor, no separate service or schedule."""
    import fcntl
    import pwd
    import sys
    sys.path.insert(0, '/usr/local/share/optibrain-platform-runtime')
    policy = storage.load_policy()
    owner = pwd.getpwnam('opticable-workflow-api').pw_uid
    database = storage.ROOT.parent / 'phase12-autonomy.db'
    lockfd = os.open(storage.ROOT / 'execution.lock', os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(lockfd, 'r+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {'state': 'BUSY_EXISTING_WORKER'}
        now = datetime.now(timezone.utc)
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            report = plan(db, storage.ROOT, now, owner, policy)
            budget = storage.admission(db, storage.ROOT, now, policy)
        result = execute(database, storage.ROOT, now, owner, policy)
        report.update(execution=result, budget=budget)
        storage.replace_report(REPORT, report)
        return {'state': result['state'], 'eligible_files': report['eligible_files'],
                'eligible_bytes': report['eligible_logical_bytes'],
                'optional_paused': budget['optional_paused'], 'pause_reasons': budget['pause_reasons'],
                'usage': budget['usage'], 'free_bytes': budget['free_bytes'],
                'quarantined': result['quarantined'], 'deleted': result['deleted']}
