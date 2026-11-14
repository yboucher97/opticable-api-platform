"""Read-only host inventory; explicit private report, no cleanup or provider calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import sqlite3
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import storage
import lifecycle

FAMILIES = {
    'retained_recovery': '/recovery',
    'backup_archives_and_staging': '/var/backups/optibrain',
    'data_generations_including_live_bind': '/var/lib/optibrain-data/generations',
    'encrypted_backup_spool': '/var/lib/optibrain/phase2a',
    'engineering_workspaces': '/home/ubuntu/optibrain-development',
    'codex_cache_and_tools': '/home/ubuntu/.codex',
    'system_cache': '/var/cache', 'temporary_system': '/tmp', 'temporary_var': '/var/tmp',
    'marketing_artifacts': str(storage.ROOT / 'artifacts'),
    'private_preview': str(storage.ROOT / 'website-preview'),
}


def inventory(path):
    logical = allocated = count = symlinks = 0; seen = set(); kinds = Counter(); owners = Counter(); large = []
    root = Path(path)
    if not root.exists(): return {'path': path, 'exists': False}
    device = root.lstat().st_dev
    for directory, dirs, files in os.walk(root, followlinks=False):
        keep = []
        for name in dirs:
            p = Path(directory) / name; st = p.lstat()
            if stat.S_ISLNK(st.st_mode): symlinks += 1
            elif st.st_dev == device: keep.append(name)
        dirs[:] = keep
        for name in files:
            p = Path(directory) / name
            try: st = p.lstat()
            except FileNotFoundError: continue
            if stat.S_ISLNK(st.st_mode): symlinks += 1; continue
            if not stat.S_ISREG(st.st_mode) or st.st_dev != device: continue
            key = st.st_dev, st.st_ino
            if key in seen: continue
            seen.add(key); count += 1; logical += st.st_size; allocated += st.st_blocks * 512
            suffix = p.suffix.lower()
            kind = 'screenshots_media' if suffix in ('.png','.jpg','.jpeg','.webp','.svg','.mp4') else (
                'test_cache' if any(x in p.parts for x in ('__pycache__','.pytest_cache','node_modules')) else (
                'github_source' if '.git' in p.parts else 'other'))
            kinds[kind] += 1; owners[st.st_uid] += 1
            if st.st_size > 32*1024**2: large.append({'path': str(p), 'bytes': st.st_size, 'mtime': datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
    return {'path': path, 'exists': True, 'files': count, 'logical_bytes': logical,
            'allocated_file_bytes': allocated, 'symlinks_excluded': symlinks,
            'counts_by_category': dict(kinds), 'file_owners': dict(owners),
            'large_files': sorted(large, key=lambda x: -x['bytes'])[:30],
            'cleanup_decision': 'KEEP: recovery/source/evidence or unregistered; age alone never grants disposal'}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True); args = parser.parse_args()
    now = datetime.now(timezone.utc); fs = os.statvfs('/')
    database = storage.ROOT.parent / 'phase12-autonomy.db'; owner = pwd.getpwnam('opticable-workflow-api').pw_uid
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        lifecycle_report = lifecycle.plan(db, storage.ROOT, now, owner)
        budget = storage.admission(db, storage.ROOT, now)
        assets = storage.metadata(db)[0]
        registry = Counter(storage.family(x) for x in assets)
    latest = json.loads(Path('/var/lib/optibrain/resource-management/latest.json').read_text())
    result = {'schema':1,'at':now.isoformat(),'host':os.uname().nodename,
        'filesystem':{'capacity_bytes':fs.f_blocks*fs.f_frsize,'used_bytes':(fs.f_blocks-fs.f_bfree)*fs.f_frsize,
                      'available_bytes':fs.f_bavail*fs.f_frsize},
        'measured_growth':latest.get('forecast'),'growth_observed_at':latest['at'],
        'growth_caveat':'Net whole-filesystem slope includes prior approved recovery retirement; not a marketing growth rate or steady-state prediction.',
        'families':{k:inventory(v) for k,v in FAMILIES.items()},
        'registered_categories':dict(registry),'budget':budget,'lifecycle':lifecycle_report,
        'old_backup_staging':[str(p) for p in sorted(Path('/var/backups/optibrain').glob('.staging-*'))],
        'production_files_moved':0,'production_files_deleted':0}
    path=Path(args.output); fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    print(json.dumps({k:result[k] for k in ('host','at','filesystem','registered_categories')}))
    print(json.dumps({'eligible_files':lifecycle_report['eligible_files'],'eventual_allocated_savings':lifecycle_report['expected_final_deletion_bytes'],
        'budget':{k:v for k,v in budget.items() if k not in ('pending_semantics','protected_hashes')}}))


if __name__ == '__main__':main()
