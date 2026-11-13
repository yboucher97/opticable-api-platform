#!/usr/bin/python3
"""Future fixed root adapter. Not installed or enabled by passive supervision."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys

POLICY=Path('/etc/optibrain/readiness-refresh-policy.json')
GRANT=Path('/etc/optibrain/readiness-refresh-authorization.json')
OBSERVER=Path('/usr/local/lib/optibrain/recovery-observer.py')
ADAPTER=Path('/usr/local/lib/optibrain/readiness-refresh-adapter.py')
TARGET=Path('/run/optibrain-readiness/status.json')
BASE=Path('/var/lib/optibrain/autonomous-operations/passive-recovery/readiness-preimages')
JOURNAL=Path('/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db')
AUTOMATION=Path('/var/lib/opticable-workflow-api/output/automation/automation.db')
ROOT=Path('/opt/opticable-api-platform')
RUNTIME=Path('/usr/local/lib/optibrain-recovery')


def protected(path):
    for p in [*reversed(path.parents),path]:
        s=p.lstat()
        if p.is_symlink() or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Protected root-owned path required')
    s=path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>131072:
        raise ValueError('Bounded private regular policy required')
    return path.read_bytes()


def private_json(path):
    raw=protected(path)
    if path.stat().st_mode&0o077:raise ValueError('Private root approval required')
    return json.loads(raw)


class RootScope:
    @contextmanager
    def lock(self):
        path=Path('/run/lock/optibrain-readiness-refresh.lock')
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as stream:
            s=os.fstat(stream.fileno())
            if s.st_uid!=0 or s.st_nlink!=1 or s.st_mode&0o077:raise ValueError('Private execution lock required')
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield

    def write(self,name,data):
        if not re.fullmatch(r'evidence/readiness-refresh:[0-9a-f]{32}\.(before|invalid)',name) or len(data)>2*1024**2:
            raise ValueError('Only exact bounded derived-status evidence is writable')
        if not BASE.is_dir() or BASE.is_symlink() or BASE.stat().st_uid!=0 or BASE.stat().st_mode&0o077:
            raise ValueError('Preinstalled private evidence directory required')
        fd=os.open(BASE/Path(name).name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        fd=os.open(BASE,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)


def collect_evidence(policy,audit,digest,holds,operation_id):
    now=datetime.now(timezone.utc)
    if set(policy['samplers'])!={'/usr/local/lib/optibrain/current_readiness.py','/usr/local/lib/optibrain/phase14-runtime-snapshot.py'}:
        raise ValueError('Exact existing provider-free readiness sampler inventory required')
    runtime=True
    for path,want in policy['samplers'].items():runtime=hashlib.sha256(protected(Path(path))).hexdigest()==want and runtime
    settings=policy['protected_settings']
    if len(settings)!=76:raise ValueError('Exact protected configuration checkpoint required')
    unchanged=all(hashlib.sha256(protected(Path(path))).hexdigest()==want for path,want in settings.items())
    registry=json.loads(protected(Path('/var/lib/optibrain/autonomous-operations/45-runtime-flags.json')))
    flags=[]
    for row in registry:
        pid=subprocess.check_output(['/usr/bin/systemctl','show',row['unit'],'-p','MainPID','--value'],text=True,timeout=5).strip()
        env=dict(v.split('=',1) for v in Path('/proc/'+str(int(pid))+'/environ').read_text().split('\0') if '=' in v)
        flags.append(env.get(row['flag'])==row['expected_disabled_value'])
    source=subprocess.check_output(['/usr/bin/git','-c','safe.directory='+str(ROOT),'-C',str(ROOT),'rev-parse','HEAD'],text=True,timeout=5).strip()
    timer=dict(line.split('=',1) for line in subprocess.check_output(['/usr/bin/systemctl','show','optibrain-resource-sample.service','-p','ActiveState','-p','InvocationID'],text=True,timeout=5).splitlines())
    snapshot=json.loads(protected(TARGET));resource=json.loads(protected(Path('/var/lib/optibrain/resource-management/latest.json')))
    captured=datetime.fromisoformat(snapshot['captured_at'].replace('Z','+00:00'));age=(now-captured).total_seconds()
    with sqlite3.connect(AUTOMATION.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
        db.execute('PRAGMA query_only=ON')
        inflight=db.execute("SELECT COUNT(*) FROM automation_runs WHERE status IN ('queued','claimed','running','retrying')").fetchone()[0]
        claims=db.execute('SELECT COUNT(*) FROM automation_run_claims WHERE lease_expires_at>?',(int(now.timestamp()),)).fetchone()[0]
    with audit.connect(readonly=True) as db:
        ids=db.execute("SELECT action_id FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='EXACT_READINESS_REFRESH' LIMIT 1001").fetchall()
    if len(ids)>1000:raise ValueError('Audit review budget reached; stop for owner review')
    for row in ids:audit.verify_integrity(row[0])
    claims=list(BASE.glob('readiness-refresh:*.before'))
    if len(claims)>1000:raise ValueError('Protected operation-claim review budget reached')
    own='readiness-refresh:'+digest(operation_id)[:32]+'.before'
    cooldown=any(p.name!=own and now.timestamp()-p.stat().st_mtime<900 for p in claims)
    return {'observed_at':now.isoformat(),'root_policy_verified':True,'root_grant_verified':True,
        'runtime_pin_verified':runtime,'45_flags_off':len(flags)==45 and all(flags),
        '76_settings_unchanged':unchanged,'no_inflight_business_effects':not inflight and not claims,
        'no_recovery_hold':not holds(audit) and not (BASE/'AUTONOMY_HOLD').exists(),'audit_integrity_verified':True,
        'sampler_idle':timer['ActiveState'] in {'inactive','failed'} and not cooldown,'sampler_invocation_id':timer['InvocationID'],
        'observations_stale':age>2700,'source_sha':source,'configuration_checkpoint_verified':unchanged,
        'configuration_checkpoint_sha256':digest(settings),'sampler_identity_sha256':digest(policy['samplers']),
        'resource_observed_at':resource['at']}


def root_audit(event,operation_id,**details):
    path=Path('/var/lib/optibrain/autonomous-operations/operations-audit.jsonl')
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
    with os.fdopen(fd,'a') as stream:
        s=os.fstat(stream.fileno())
        if s.st_uid!=0 or s.st_nlink!=1 or not stat.S_ISREG(s.st_mode) or s.st_mode&0o077:
            raise ValueError('Existing root-only append audit required')
        fcntl.flock(stream,fcntl.LOCK_EX)
        stream.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'event':event,
            'playbook':'refresh-local-readiness','operation_id':operation_id,**details},sort_keys=True)+'\n')
        stream.flush();os.fsync(stream.fileno())


def hold(operation_id):
    try:fd=os.open(BASE/'AUTONOMY_HOLD',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:return
    with os.fdopen(fd,'w') as stream:stream.write(operation_id+'\n');stream.flush();os.fsync(stream.fileno())
    fd=os.open(BASE,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--operation-id',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('Protected installed root adapter required')
    policy,grant=private_json(POLICY),private_json(GRANT)
    if policy.get('enabled') is not True or grant.get('approved') is not True:
        raise PermissionError('No production readiness grant is enabled')
    if hashlib.sha256(protected(Path(__file__))).hexdigest()!=policy['entrypoint_sha256']:
        raise ValueError('Trusted adapter entrypoint pin changed')
    passive=private_json(Path('/etc/optibrain/recovery-passive.json'))
    if hashlib.sha256(protected(OBSERVER)).hexdigest()!=passive['observer_sha256']:
        raise ValueError('Independent verifier pin changed')
    spec=importlib.util.spec_from_file_location('trusted_observer',OBSERVER)
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier);verifier.verify_runtime(RUNTIME,passive)
    if hashlib.sha256(protected(ADAPTER)).hexdigest()!=policy['adapter_sha256']:
        raise ValueError('Exact adapter implementation pin changed')
    sys.path[:0]=[str(RUNTIME),str(RUNTIME/'vendor')]
    from workflow.automation.action_evidence import ActionEvidence
    from workflow.automation.acquisition_store import digest
    from workflow.automation.operational_recovery import recovery_holds
    spec=importlib.util.spec_from_file_location('workflow.automation.readiness_refresh',ADAPTER)
    implementation=importlib.util.module_from_spec(spec);spec.loader.exec_module(implementation)
    audit=ActionEvidence(JOURNAL)
    # No schema creation/migration in a production repair. Existing journal only.
    with audit.connect(readonly=True) as db:
        triggers={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if not {'action_envelopes_immutable_update','action_envelopes_immutable_delete','action_evidence_immutable_update','action_evidence_immutable_delete'}<=triggers:
        raise ValueError('Existing immutable audit protections are required')
    evidence=lambda:collect_evidence(policy,audit,digest,recovery_holds,args.operation_id)
    adapter=implementation.ReadinessRefreshAdapter(RootScope(),audit,target=TARGET,policy=policy,grant=grant,
        evidence=evidence,clock=lambda:datetime.now(timezone.utc))
    # Root-only audit/immutable preimage claims survive application-journal loss.
    # Private O_EXCL preimage files prevent replay even if an app-owned row vanished.
    implementation.validate_authority(policy,grant,evidence(),args.operation_id,datetime.now(timezone.utc))
    root_audit('READINESS_EXACT_OPERATION_STARTED',args.operation_id,grant_sha256=digest(grant))
    try:
        result=adapter.execute(args.operation_id)
        if result.get('state')=='FAILED':hold(args.operation_id)
        root_audit('READINESS_EXACT_OPERATION_FINISHED',args.operation_id,state=result['state'])
    except BaseException:
        hold(args.operation_id);root_audit('READINESS_EXACT_OPERATION_INTERRUPTED',args.operation_id,state='HOLD')
        raise
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
