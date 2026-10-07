#!/usr/bin/env python3
"""Capture the separate rebuild journal in existing encrypted backup roots."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys


def checksum(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def export_actions(source,state,directory):
    target_id=json.loads(Path(state).read_text())['target_id']
    if not re.fullmatch('[0-9a-f]{32}',target_id):raise ValueError('Invalid rebuild target identity')
    with sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Rebuild audit integrity failed')
        envelopes=[dict(r) for r in db.execute('SELECT * FROM action_envelopes ORDER BY action_id')]
        events=[dict(r) for r in db.execute('SELECT * FROM action_evidence ORDER BY event_id')]
    previous={}
    for row in envelopes:
        if checksum(json.loads(row['envelope_json']))!=row['payload_hash']:raise ValueError('Rebuild envelope hash failed')
    for row in events:
        prior=previous.get(row['action_id'],'')
        if row['previous_hash']!=prior or row['event_hash']!=checksum([row[k] for k in ('action_id','kind','recorded_at','evidence_json','previous_hash')]):
            raise ValueError('Rebuild action chain failed')
        previous[row['action_id']]=row['event_hash']
    from datetime import datetime,timezone
    value={'schema':1,'type':'optibrain.rebuild.audit_export','target_id':target_id,
        'at':datetime.now(timezone.utc).isoformat(),'action_envelopes':envelopes,'action_evidence':events,'all_action_chains_verified':True}
    directory=Path(directory);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(dir=directory,delete=False) as output:
        os.fchmod(output.fileno(),0o600);output.write((json.dumps(value,sort_keys=True)+'\n').encode());output.flush();os.fsync(output.fileno());temporary=output.name
    destination=directory/(target_id+'.json');os.replace(temporary,destination)
    if json.loads(destination.read_text())!=value:raise ValueError('Rebuild export readback failed')
    return {'target_id':target_id,'envelopes':len(envelopes),'events':len(events),'export_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}


if __name__=='__main__':
    try:
        if os.geteuid()!=0:raise ValueError('Root required')
        for name in ('/var/lib/optibrain-rebuild/actions.db','/var/lib/optibrain-rebuild/state.json'):
            path=Path(name);info=path.lstat()
            if path.is_symlink() or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('Untrusted rebuild journal')
        directory=Path('/var/lib/optibrain/rebuild-evidence')
        if directory.is_symlink():raise ValueError('Untrusted rebuild export directory')
        os.umask(0o077)
        print(json.dumps(export_actions('/var/lib/optibrain-rebuild/actions.db','/var/lib/optibrain-rebuild/state.json',directory)))
    except Exception as exc:
        raise SystemExit('Rebuild audit export blocked: '+type(exc).__name__)
