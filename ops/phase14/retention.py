#!/usr/bin/env python3
"""Deterministic hold-aware local retention; default dry run, no R2 deletion.

Only verified ciphertext spool duplicates and unheld, independently off-host
verified local backups can become candidates. Manifests, audit, protected state,
owner proof and exact release/recovery holds are always retained.
"""
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

LOCAL=Path('/var/backups/optibrain')
SPOOL=Path('/var/lib/optibrain/phase2a')
OWNER='20261001T202728Z'
GEN=re.compile(r'^\d{8}T\d{6}Z$')
POLICY={'schema':1,'local_generations':7,'spool_generations':2,'remote_delete':False,
        'owner_hold':OWNER,'minimum_verified_recovery_generations':2}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def holds(roots):
    result={OWNER:['offline owner AGE recovery proof']}
    for root in roots:
        for path in sorted(Path(root).rglob('*')):
            if not path.is_file() or path.is_symlink() or path.suffix not in {'.json','.md','.sh'} or path.stat().st_size>2*1024**2:continue
            if SPOOL in path.parents or '/phase14/' in str(path):continue
            text=path.read_text(errors='replace')
            for generation in sorted(set(re.findall(r'(?:optibrain-backup-)?(2026\d{4}T\d{6}Z)(?:\.tar\.gz)?',text))):
                result.setdefault(generation,[]).append(str(path))
    return result


def plan(local=LOCAL,spool=SPOOL,*,hold_index=None,policy=POLICY):
    hold_index=hold_index or {OWNER:['offline owner AGE recovery proof']}
    audit=[json.loads(line) for line in (spool/'audit.jsonl').read_text().splitlines() if line.strip()]
    downloaded={(r.get('key'),r.get('sha256')) for r in audit if r.get('event')=='download_hash_verified'}
    complete={r.get('generation') for r in audit if r.get('event')=='generation_verified'}
    manifests={}
    for path in sorted(spool.glob('*/prepared.json')):
        generation=path.parent.name
        if not GEN.fullmatch(generation):continue
        data=json.loads(path.read_text())
        verified=(data.get('generation')==generation and generation in complete
                  and (data.get('object_key'),data.get('encrypted_sha256')) in downloaded
                  and (str(data.get('object_key'))+'.json',sha(path)) in downloaded)
        manifests[generation]=(data,verified)
    verified=sorted(g for g,(_,ok) in manifests.items() if ok)
    retained=set(verified[-policy['spool_generations']:])|{policy['owner_hold']}
    # Owner proof is additive; never count it as one of the two recent generations.
    available=[g for g in verified if (spool/g/'archive.tar.gz.age').is_file()
               and not (spool/g/'archive.tar.gz.age').is_symlink()]
    recent=set(verified[-policy['spool_generations']:])
    coverage=(len(recent & set(available))>=policy['minimum_verified_recovery_generations']
              and policy['owner_hold'] in available
              and all(sha(spool/g/'archive.tar.gz.age')==manifests[g][0]['encrypted_sha256'] for g in retained))
    archives=sorted(local.glob('optibrain-backup-*.tar.gz'))
    newest={p.name.removeprefix('optibrain-backup-').removesuffix('.tar.gz') for p in archives[-policy['local_generations']:]}
    rows=[]
    def append(path,generation,classification,action,reason,rule,*,hold=False,digest=None):
        rows.append(dict(path=str(path),bytes=path.stat().st_size,generation=generation,
                         classification=classification,action=action,reason=reason,retention_rule=rule,
                         hold=hold,sha256=digest))
    for path in archives:
        generation=path.name.removeprefix('optibrain-backup-').removesuffix('.tar.gz')
        data,ok=manifests.get(generation,({},False))
        held=generation in hold_index or generation in newest
        if path.is_symlink():append(path,generation,'UNKNOWN','MANUAL REVIEW','Symlink refused','never-follow');continue
        if held:
            append(path,generation,'RECOVERY HOLD' if generation in hold_index else 'AUTHORITATIVE BACKUP','KEEP',
                   'Exact recovery/audit reference' if generation in hold_index else 'Seven latest local generations','local-seven-plus-holds',hold=True)
        elif ok and coverage:
            digest=sha(path)
            sidecar=path.with_name(path.name+'.sha256')
            if digest==data.get('source_sha256') and sidecar.is_file() and sidecar.read_text().split()[0]==digest:
                append(path,generation,'OFF-HOST VERIFIED','DELETE CANDIDATE','Unheld local duplicate; remote full hash and manifest verified','local-seven-plus-holds',digest=digest)
                append(sidecar,generation,'OFF-HOST VERIFIED','DELETE CANDIDATE','Checksum sidecar of the same verified duplicate','paired-sidecar',digest=sha(sidecar))
            else:append(path,generation,'UNKNOWN','MANUAL REVIEW','Source/hash evidence differs','hash-conflict')
        else:append(path,generation,'UNKNOWN','MANUAL REVIEW','Off-host coverage or verification incomplete','fail-closed')
    for generation,(data,ok) in sorted(manifests.items()):
        directory=spool/generation;path=directory/'archive.tar.gz.age'
        manifest=directory/'prepared.json'
        append(manifest,generation,'AUDIT HOLD','KEEP','Immutable preparation and verification evidence','indefinite-audit',hold=True)
        if not path.exists():continue
        if path.is_symlink():append(path,generation,'UNKNOWN','MANUAL REVIEW','Symlink refused','never-follow');continue
        if generation in retained:
            append(path,generation,'RECOVERY HOLD','KEEP','Two recent verified ciphertext generations and owner proof','spool-two-plus-owner',hold=True)
        elif ok and coverage:
            digest=sha(path)
            if digest==data.get('encrypted_sha256'):
                append(path,generation,'STAGING','DELETE CANDIDATE','Successful immutable off-host hash verification; redundant local ciphertext','spool-two-plus-owner',digest=digest)
            else:append(path,generation,'UNKNOWN','MANUAL REVIEW','Ciphertext hash conflict','hash-conflict')
        else:append(path,generation,'RECOVERY HOLD','KEEP','Failed or uncertain upload; preserve source and ciphertext','uncertain-upload-hold',hold=True)
    for path in sorted(spool.iterdir()):
        if path.is_file() and not path.is_symlink():append(path,None,'AUDIT HOLD','KEEP','Upload success/failure, lock or audit evidence','indefinite-audit',hold=True)
    for directory in sorted(p for p in spool.iterdir() if p.is_dir() and GEN.fullmatch(p.name)):
        for path in sorted(directory.iterdir()):
            if path.name not in {'archive.tar.gz.age','prepared.json'} and path.is_file():
                append(path,directory.name,'UNKNOWN','MANUAL REVIEW','Incomplete or unclassified staging artifact','manual-review')
    rows.sort(key=lambda row:row['path'])
    value=dict(schema=1,policy=policy,hold_index=hold_index,coverage_verified=coverage,
               retained_ciphertext_generations=sorted(retained),rows=rows,
               total_bytes=sum(r['bytes'] for r in rows),candidate_bytes=sum(r['bytes'] for r in rows if r['action']=='DELETE CANDIDATE'))
    value['report_sha256']=hashlib.sha256(canonical(value)).hexdigest()
    return value


def execute(report,*,local=LOCAL,spool=SPOOL,hold_index=None):
    if os.geteuid()!=0:raise PermissionError('Root retention execution required')
    if report['policy']!=POLICY:raise ValueError('Reviewed retention policy differs')
    current=plan(local,spool,hold_index=hold_index,policy=report['policy'])
    if current['report_sha256']!=report['report_sha256']:raise ValueError('Dry run changed; inspect a new report before execution')
    candidates=[row for row in current['rows'] if row['action']=='DELETE CANDIDATE']
    # Validate every candidate before deleting any, then unlink only exact regular files.
    for row in candidates:
        path=Path(row['path']);info=path.lstat()
        permitted=(path.parent==local and re.fullmatch(r'optibrain-backup-\d{8}T\d{6}Z\.tar\.gz(?:\.sha256)?',path.name)
                   or path.parent.parent==spool and GEN.fullmatch(path.parent.name) and path.name=='archive.tar.gz.age')
        if not permitted or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or row['hold'] or sha(path)!=row['sha256']:
            raise ValueError('Retention candidate changed or escaped allowed family')
    reclaimed=0
    for row in candidates:
        Path(row['path']).unlink();reclaimed+=row['bytes']
    return dict(schema=1,report_sha256=current['report_sha256'],bytes_reclaimed=reclaimed,
                deleted=[{'path':r['path'],'bytes':r['bytes'],'sha256':r['sha256']} for r in candidates],
                remote_deleted=0,at=datetime.now(timezone.utc).isoformat())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--execute',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('Protected hold inventory requires manual root')
    os.umask(0o077)
    with (SPOOL/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        index=holds([Path('/etc/optibrain'),Path('/var/lib/optibrain')])
        value=execute(json.loads(args.execute.read_text()),hold_index=index) if args.execute else plan(hold_index=index)
        if args.output:args.output.write_text(json.dumps(value,indent=2)+'\n')
        print(json.dumps({k:value[k] for k in ('report_sha256','total_bytes','candidate_bytes','bytes_reclaimed','remote_deleted') if k in value}))


if __name__=='__main__':main()
