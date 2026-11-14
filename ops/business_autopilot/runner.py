"""Fixed offline child runner attached to the existing native analytics schedule.

No root execution, no credentials passed to child, no provider calls. Reuses
AcquisitionStore CONTENT_ASSET/OBSERVATION records; creates no database/timer.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import zlib

RUNTIME = Path('/usr/local/share/optibrain-business-autopilot-v1')
OUTPUT = Path('/var/lib/opticable-workflow-api/output/automation/business-autopilot')
COLLECTOR = Path('/var/lib/opticable-workflow-api/output/automation/platform-intelligence')
CONFIG = Path('/etc/optibrain/platform-intelligence.json')
SANDBOX = Path('/usr/local/lib/optibrain-recovery/workflow/automation/development_sandbox.py')
MAX_FILES = 100


def load(p):
    if p.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Input budget')
    return json.loads(p.read_text())


def verify_runtime(root, require_root=True):
    root = Path(root)
    for entry in (root, root / 'manifest.json'):
        st = entry.lstat()
        if entry.is_symlink() or st.st_mode & 0o022 or (require_root and st.st_uid != 0):
            raise PermissionError('Protected runtime and manifest required')
    files = load(root / 'manifest.json')
    if set(files) != {'engine.py', 'runner.py', 'content_bank.json', 'sandbox.py'}:
        raise ValueError('Exact reviewed manifest required')
    for name, digest in files.items():
        p = root / name; st = p.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022 or (require_root and st.st_uid != 0):
            raise PermissionError('Trusted read-only runtime required')
        if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('Runtime identity changed')
    if {p.name for p in root.iterdir()} != set(files) | {'manifest.json'}:
        raise ValueError('Unexpected runtime file')
    return files


def collect_input(database, summary):
    values = []
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True, timeout=5) as db:
        db.row_factory = sqlite3.Row
        for sid in summary['snapshot_ids']:
            row = db.execute('SELECT * FROM acquisition_snapshots WHERE id=?', (sid,)).fetchone()
            if not row or row['raw_bytes'] > 2097152 or not row['source'].startswith('platform:'):
                raise ValueError('Invalid native evidence reference')
            s = dict(row); raw = s.pop('raw')
            dec = zlib.decompressobj(); blob = dec.decompress(raw, 2097153)
            if len(blob) > 2097152 or not dec.eof or len(blob) != s['raw_bytes']:
                raise ValueError('Snapshot integrity/size')
            s['data'] = json.loads(blob)
            # Minimize CRM inventory: no contact details, invoice values or credentials.
            if s['source'] == 'platform:crm_marketing':
                crm = s['data']
                s['data'] = {k: crm.get(k) for k in ('schema', 'scope', 'read_only', 'observed_at', 'problems')}
                s['data']['groups'] = [{k: g.get(k) for k in ('source', 'leads')} for g in crm.get('groups', [])]
            values.append(s)
    return {'schema': 1, 'collection': summary, 'snapshots': values}


def sandbox_child(runtime, scratch):
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024**2, 384 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    spec = importlib.util.spec_from_file_location('existing_business_sandbox', runtime / 'sandbox.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.restrict_child(runtime, scratch)


def child(runtime, scratch, request, now):
    # Imports stay within reviewed runtime; no workflow/app or credential imports.
    sys.path.insert(0, str(runtime))
    import engine
    value = load(request)
    files = engine.make_artifacts(value['native'], value.get('supplement', {}), load(runtime / 'content_bank.json'), datetime.fromisoformat(now))
    manifest = engine.write_bundle(scratch, files)
    print(json.dumps(manifest, ensure_ascii=False))


def run_child(runtime, scratch, request, now):
    result = subprocess.run(['/usr/bin/python3', '-I', '-B', str(runtime / 'runner.py'), '--child',
                             str(runtime), str(scratch), str(request), now.isoformat()],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'America/Toronto'},
                            cwd=scratch, timeout=45, shell=False,
                            preexec_fn=lambda: sandbox_child(runtime, scratch))
    if result.returncode or len(result.stdout) > 131072:
        raise RuntimeError('Offline generation failed: ' + result.stderr.decode(errors='replace')[-1500:])
    manifest = json.loads(result.stdout)
    if not isinstance(manifest, list) or len(manifest) > MAX_FILES:
        raise ValueError('Manifest budget')
    for item in manifest:
        p = scratch / item['path']
        if not p.resolve().is_relative_to(scratch.resolve()) or p.is_symlink() or p.stat().st_size > 8 * 1024**2:
            raise ValueError('Output escape/budget')
        if hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Output integrity')
    return manifest


def run():
    if os.geteuid() == 0:
        raise PermissionError('Artifact work must never run as root')
    os.umask(0o077); verify_runtime(RUNTIME)
    OUTPUT.mkdir(mode=0o700, exist_ok=True)
    with (OUTPUT / 'execution.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('SKIPPED existing business artifact execution'); return
        now = datetime.now(timezone.utc)
        summary = load(COLLECTOR / 'status.json'); cfg = load(CONFIG)
        if any(cfg.get(k) is not False for k in ('writes_allowed', 'publishing_allowed', 'paid_operations_allowed')):
            raise PermissionError('Read-only source configuration changed')
        native = collect_input(cfg['database'], summary)
        supplemental = COLLECTOR / 'business-supplement-20261114.json'
        supplement = load(supplemental) if supplemental.exists() else {}
        # Supplement is a single evidence capture, never refresh or reuse for another period.
        if any(r.get('period') != summary['period'] for r in supplement.get('results', []) if not r['source'].endswith(':previous')):
            supplement = {}
        evidence_key = hashlib.sha256(json.dumps([summary['snapshot_ids'], summary['at'],
                            supplement.get('observed_at'), hashlib.sha256((RUNTIME/'manifest.json').read_bytes()).hexdigest(), now.astimezone(__import__('zoneinfo').ZoneInfo('America/Toronto')).date().isoformat()], sort_keys=True).encode()).hexdigest()
        receipt = OUTPUT / ('run-' + evidence_key + '.json')
        if receipt.exists():
            saved = load(receipt)
            for item in saved['manifest']:
                p = OUTPUT / 'artifacts' / item['path']
                if p.is_symlink() or not p.resolve().is_relative_to((OUTPUT/'artifacts').resolve()) or hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
                    raise ValueError('Previously completed artifact integrity failure')
            print('CACHED verified business artifacts; no provider or paid call'); return
        failed = OUTPUT / ('failed-' + evidence_key + '.json')
        if failed.exists():
            print('HELD prior failed attempt for this evidence/day/runtime; no retry or business action'); return
        scratch = OUTPUT / 'artifacts'; scratch.mkdir(mode=0o700, exist_ok=True)
        fd, request_name = tempfile.mkstemp(prefix='.input-', suffix='.json', dir=scratch)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'native': native, 'supplement': supplement}, stream)
            manifest = run_child(RUNTIME, scratch, Path(request_name), now)
        except Exception as error:
            with failed.open('x') as stream:
                json.dump({'at': now.isoformat(), 'status': 'FAILED_INTERNAL_DRAFTS', 'error_class': type(error).__name__,
                           'evidence_ids': summary['snapshot_ids'], 'paid_calls': 0, 'publishing': False,
                           'next_action': 'Inspect existing service journal; held for this evidence/day/runtime'}, stream)
                stream.flush(); os.fsync(stream.fileno())
            with (OUTPUT / 'outcomes.jsonl').open('a') as stream:
                stream.write(failed.read_text() + '\n'); stream.flush(); os.fsync(stream.fileno())
            raise
        finally:
            Path(request_name).unlink(missing_ok=True)
        # Reuse the pinned existing acquisition implementation after artifact isolation.
        spec = importlib.util.spec_from_file_location('platform_native', '/usr/local/lib/optibrain-platform-intelligence.py')
        native_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(native_module)
        native_module.verify_runtime(Path(cfg['runtime']))
        from workflow.automation.acquisition_store import AcquisitionStore
        store = AcquisitionStore(cfg['database']); store.initialized = True
        records = []
        for item in manifest:
            records.append(store.record('CONTENT_ASSET', {**item, 'scope': 'live', 'status': 'DRAFT_ONLY',
                          'published': False, 'incremental_cost': '0', 'local_root': str(scratch)},
                          source='platform:business_autopilot', native_id=item['sha256'], url='https://opticable.ca/', now=now,
                          cost_class='NO EXTERNAL COST', observed_at=summary['at']))
        value = {'schema': 1, 'at': now.isoformat(), 'status': 'COMPLETED_INTERNAL_DRAFTS', 'manifest': manifest,
                 'evidence_ids': summary['snapshot_ids'], 'records': records, 'source_observed_at': summary['at'],
                 'provider_calls': 0, 'paid_calls': 0, 'publishing': False, 'production_changes': False}
        # Receipt only after all append-only asset registration succeeds. Replay deduplicates facts.
        with receipt.open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        with (OUTPUT / 'outcomes.jsonl').open('a') as stream:
            stream.write(json.dumps({k: v for k, v in value.items() if k not in ('manifest', 'records')}) + '\n'); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps({'artifacts': len(manifest), 'provider_calls': 0, 'paid_calls': 0, 'publishing': False}))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
    elif len(sys.argv) == 1:
        try:
            run()
        except Exception as error:
            # Existing local learning ledger, with no exception text or secrets.
            if OUTPUT.is_dir() and not OUTPUT.is_symlink():
                with (OUTPUT / 'outcomes.jsonl').open('a') as stream:
                    stream.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                        'status': 'FAILED_INTERNAL_DRAFTS', 'error_class': type(error).__name__,
                        'paid_calls': 0, 'publishing': False, 'production_changes': False}) + '\n')
                    stream.flush(); os.fsync(stream.fileno())
            raise
    else:
        raise SystemExit('Fixed entry point required')
