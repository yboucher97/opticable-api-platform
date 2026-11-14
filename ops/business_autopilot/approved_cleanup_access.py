"""Prepare exact mount access for a FUTURE approved monitor; never activates it.

SQLite needs its parent writable for atomic WAL/SHM creation/removal. Freeze every
other current direct child read-only, including all other databases and private
business files. Source file removal remains restricted by the lifecycle dirfds.
"""
from pathlib import Path

DATABASE_ROOT = Path('/var/lib/opticable-workflow-api/output/automation')
BUSINESS_ROOT = DATABASE_ROOT / 'business-autopilot'


def render(database_root=DATABASE_ROOT):
    root = Path(database_root); business = root / 'business-autopilot'
    writable_db_names = {'phase12-autonomy.db', 'phase12-autonomy.db-wal', 'phase12-autonomy.db-shm'}
    writable_business = {'artifacts', 'temporary', 'disposable-previews'}
    protected = [p for p in root.iterdir() if p.name not in writable_db_names | {'business-autopilot'}]
    protected += [p for p in business.iterdir() if p.name not in writable_business]
    # Optional masks survive absent sidecars; exact child paths cannot inject a
    # systemd directive or specifier. New sibling paths receive no deletion grant.
    for p in protected:
        if any(c in str(p) for c in ('\n','\r','%',' ')): raise ValueError('Unsupported mount path')
    return ('# INACTIVE proposal: install ONLY under exact owner storage approval.\n'
            '# Existing timer only; SQLite journal writes and allowlisted moves.\n'
            '[Service]\nReadWritePaths=' + str(root) + '\n' +
            ''.join('ReadOnlyPaths=-' + str(p) + '\n' for p in sorted(protected)))
