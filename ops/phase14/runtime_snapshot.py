#!/usr/bin/env python3
"""Root-installed local sampler. No credentials, provider calls or repair actions."""
from datetime import datetime, timezone
import json
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import math
import re

TIMERS = {'optibrain-backup':172800,'optibrain-phase2a-upload':172800,
          'opticable-phase9-intake-receipts':900,'opticable-phase10-service-events':9000,
          'opticable-phase12-test-runner':5400}
DB_ROOT = Path('/var/lib/opticable-workflow-api/output/automation')
DBS = ('automation.db','phase9-form-receipts.db','phase9-intake.db',
       'phase10-service-events.db','phase12-autonomy.db')

SERVICE_FIELDS = ('LoadState','ActiveState','SubState','Result','ExecMainStatus',
                  'ExecMainStartTimestampMonotonic','ExecMainExitTimestampMonotonic',
                  'ActiveEnterTimestampMonotonic','TimeoutStartUSec','RuntimeMaxUSec')


def duration_seconds(value):
    """Parse systemd's show-format durations; unknown is not zero."""
    if value == 'infinity':return math.inf
    if not isinstance(value,str):raise ValueError('Malformed timeout')
    factors = {'us':.000001,'ms':.001,'s':1,'min':60,'h':3600,'d':86400}
    matches = list(re.finditer(r'([0-9]+(?:\.[0-9]+)?)(us|ms|min|s|h|d)', value))
    if not matches or ''.join(m.group() for m in matches) != re.sub(r'\s+','',value):
        raise ValueError('Malformed timeout')
    return sum(float(m[1])*factors[m[2]] for m in matches)


def classify_job(props, *, uptime, freshness_seconds):
    """Pure invocation health, independent of timer/authority expectations."""
    def result(state, reason, **extra):return dict(state=state,reason=reason,**extra)
    try:
        if props.get('LoadState') != 'loaded':return result('UNKNOWN','Service unloaded or unreadable')
        if not math.isfinite(uptime) or uptime<0 or freshness_seconds<0:raise ValueError('Invalid timebase')
        times = {}
        for field in ('ExecMainStartTimestampMonotonic','ExecMainExitTimestampMonotonic','ActiveEnterTimestampMonotonic'):
            raw = props.get(field)
            if not isinstance(raw,str) or not re.fullmatch(r'\d+',raw):raise ValueError('Malformed monotonic timestamp')
            value = int(raw)/1_000_000
            if value>uptime:raise ValueError('Future timestamp or reboot/timebase mismatch')
            times[field] = value
        start = times['ExecMainStartTimestampMonotonic'];end = times['ExecMainExitTimestampMonotonic']
        active = props.get('ActiveState');sub = props.get('SubState');outcome = props.get('Result')
        # A previous completion/result belongs to an older invocation while running.
        running = active in {'activating','deactivating'} or active=='active' and sub in {'running','start','start-pre','start-post','stop','stop-sigterm','stop-sigkill'}
        if running:
            if not start:return result('UNKNOWN','Running invocation has no start evidence')
            timeout = duration_seconds(props.get('RuntimeMaxUSec','infinity')) if active=='active' else duration_seconds(props.get('TimeoutStartUSec'))
            age = uptime-start
            return result('TIMED_OUT' if age>timeout else 'RUNNING',
                          'Runtime exceeds effective timeout' if age>timeout else 'Current invocation running',
                          runtime_age_seconds=age,effective_timeout_seconds=timeout if math.isfinite(timeout) else None)
        if outcome=='timeout':return result('TIMED_OUT','systemd timeout result')
        status = props.get('ExecMainStatus')
        if not isinstance(status,str) or not re.fullmatch(r'\d+',status):raise ValueError('Malformed exit status')
        if active=='failed' or outcome not in {'success',''} or status!='0':return result('FAILED','systemd failure result or nonzero exit')
        if active not in {'inactive','active'} or sub not in {'dead','exited'}:return result('UNKNOWN','Invocation state not recognized')
        if not start and not end:return result('NEVER_RUN','No invocation timestamps')
        if not start or not end or end<start:return result('UNKNOWN','Completion timestamps inconsistent')
        age = uptime-end
        return result('STALE_COMPLETION' if age>freshness_seconds else 'COMPLETED_SUCCESS',
                      'Successful completion exceeds freshness tolerance' if age>freshness_seconds else 'Successful recent completion',
                      completion_age_seconds=age)
    except (ValueError,TypeError,OverflowError):return result('UNKNOWN','Malformed timestamp, timeout or timebase')


def expected_jobs(authorities):
    expected = dict(TIMERS)
    for kind,name in [('internal','opticable-lifecycle-internal'),('customer','opticable-customer-communications')]:
        if authorities.get(kind,{}).get('authority')=='AUTHORIZED':expected[name]=900
    return expected


def timer_summary(jobs):
    failed = [j for j in jobs if j['timer_active'] is False or j['state'] in {'FAILED','TIMED_OUT'}]
    stale = [j for j in jobs if j['state']=='STALE_COMPLETION']
    unknown = [j for j in jobs if j['state'] in {'UNKNOWN','NEVER_RUN'} or j['timer_active'] is None]
    return dict(state='ACTION REQUIRED' if failed else 'UNKNOWN' if unknown else 'DEGRADED' if stale else 'OK',
                failed=len(failed),stale=len(stale),unknown=len(unknown),running=sum(j['state']=='RUNNING' for j in jobs))


def authority_summary(value, kind, now):
    """Sanitized capability/authority display. This cannot authorize an effect."""
    policy=value.get('lifecycle',{}) if kind=='internal' else value
    configured=len(value.get('destinations',{})) if kind=='conversion' else len(policy.get('real_scopes',policy.get('scopes',[])))
    enabled=policy.get('enabled') is True if kind!='customer' else policy.get('external_enabled') is True
    effective=enabled
    expiry=policy.get('expires_at')
    operation='DISABLED'
    if enabled:
        try:
            cutoff=datetime.fromisoformat((policy.get('eligible_after') or policy['activated_at']).replace('Z','+00:00'))
            end=datetime.fromisoformat(expiry.replace('Z','+00:00'))
            if cutoff.utcoffset() is None or end.utcoffset() is None or cutoff>end:
                raise ValueError('Invalid authority window')
            operation='EXPIRED' if now>=end else 'BLOCKED' if now<cutoff else 'ACTIVE'
            effective=operation=='ACTIVE' and configured>0
            if not configured:operation='BLOCKED'
        except (KeyError,AttributeError,TypeError,ValueError):
            operation='BLOCKED';effective=False
    elif kind=='conversion' and configured:
        operation='WAITING FOR NATURAL EVENT'
    if kind=='conversion' and effective:
        effective=any(d.get('local_enabled') is True and len(d.get('allowed_event_keys',[]))==1
                      for d in value['destinations'].values())
        operation='ACTIVE' if effective else 'BLOCKED'
    return dict(capability='CAPABLE', configuration='CONFIGURED' if configured else 'NOT CONFIGURED', configured=configured,
                authority='AUTHORIZED' if effective else 'NOT AUTHORIZED', enabled=enabled,
                operation_state=operation, expires_at=expiry)


def read_authority(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise ValueError('Untrusted authority policy')
        return json.load(stream)


def resolved_read_reviews(receipt_path,producer_path,db_path):
    """A display acknowledgement only for exact, read-proven retained failures."""
    try:
        receipt=json.loads(Path(receipt_path).read_text());ids=receipt['run_ids']
        if not (receipt.get('schema')==1 and receipt.get('provider_mutations')==0 and receipt.get('new_events')==0
                and receipt['producer_sha256']==hashlib.sha256(Path(producer_path).read_bytes()).hexdigest()
                and isinstance(ids,list) and 0<len(ids)<=20 and all(isinstance(i,str) for i in ids) and len(set(ids))==len(ids)):
            return []
        with sqlite3.connect(Path(db_path).as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            return [row[0] for row in db.execute("SELECT DISTINCT r.run_id FROM automation_runs r JOIN automation_run_steps s ON s.run_id=r.run_id "
                "WHERE r.status='failed' AND r.workflow_id='opticable.crm.lead-observe' AND s.action='crm.lead.observe' "
                "AND s.error='EventConflict' AND r.run_id IN ("+','.join('?' for _ in ids)+')',ids)]
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):return []


def size(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file() and not p.is_symlink())


def allocated_size(path):
    # Journald's limit and journalctl --disk-usage count allocated blocks.
    # Sparse/preallocated apparent file lengths are not disk consumption.
    return sum(p.stat().st_blocks*512 for p in Path(path).rglob('*') if p.is_file() and not p.is_symlink())


def growth_state(staging, db_bytes, application_logs, system_journal):
    # Journald's 512 MiB cap applies to allocated journal space; allow bounded
    # active-file overhead. Do not classify normal system retention as app growth.
    if (staging > 25*1024**3 or db_bytes > 512*1024**2
            or application_logs > 128*1024**2 or system_journal > 640*1024**2):
        return 'ACTION REQUIRED'
    if (staging > 15*1024**3 or db_bytes > 128*1024**2
            or application_logs > 64*1024**2 or system_journal > 576*1024**2):
        return 'DEGRADED'
    return 'OK'


def collect(now=None):
    now=now or datetime.now(timezone.utc)
    signals=[]
    def add(name,state,reason,**extra):
        signals.append(dict(name=name,state=state,reason=reason,**extra))
    authorities={}
    for kind,label,filename in [('internal','Internal automation','mutation-control.json'),
                                ('customer','Customer communication','customer-communication-control.json'),
                                ('conversion','Google conversion export','conversion-export-control.json')]:
        try:
            summary=authority_summary(read_authority(Path('/etc/optibrain')/filename),kind,now)
            authorities[kind]=summary
            add(label,'ACTION REQUIRED' if summary['operation_state']=='BLOCKED' else
                'DEGRADED' if summary['operation_state']=='EXPIRED' else 'OK',
                'Capability and execution authority are separate; recovery never grants authority',**summary)
        except (OSError,ValueError,TypeError):
            add(label,'UNKNOWN','Authority policy unavailable; effects must fail closed',authority='UNKNOWN',operation_state='BLOCKED')
    expected=expected_jobs(authorities);jobs=[]
    try:uptime=float(Path('/proc/uptime').read_text().split()[0])
    except (OSError,ValueError,IndexError):uptime=None
    for name,deadline in expected.items():
        try:
            output=subprocess.check_output(['systemctl','show',name+'.service',*[f'--property={k}' for k in SERVICE_FIELDS]],text=True,timeout=5)
            props=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
            invocation=classify_job(props,uptime=uptime,freshness_seconds=deadline)
        except (OSError,subprocess.SubprocessError):invocation={'state':'UNKNOWN','reason':'Service unreadable'}
        try:
            active=subprocess.run(['systemctl','is-active',name+'.timer'],text=True,stdout=subprocess.PIPE,timeout=5,check=False).stdout.strip()
            timer_active=True if active=='active' else False if active in {'inactive','failed'} else None
        except (OSError,subprocess.SubprocessError):timer_active=None
        jobs.append(dict(job=name,timer_active=timer_active,**invocation))
    summary=timer_summary(jobs)
    add('Timers',summary.pop('state'),'Timer expectation and service invocation health sampled independently',
        expected=len(expected),jobs=jobs,scoped_timers_expected=len(expected)-len(TIMERS),**summary)
    archives=sorted(Path('/var/backups/optibrain').glob('optibrain-backup-*.tar.gz'))
    latest=archives[-1] if archives else None
    age=(now-datetime.fromtimestamp(latest.stat().st_mtime,timezone.utc)).total_seconds() if latest else None
    add('Backup','OK' if age is not None and age<129600 and latest.with_name(latest.name+'.sha256').is_file() else 'ACTION REQUIRED',
        'Local archive and checksum sidecar are recent' if age is not None and age<129600 else 'Local backup missing or stale',age_seconds=age)
    try:
        state=json.loads(Path('/var/lib/optibrain/phase2a/state.json').read_text())
        age=(now-datetime.fromisoformat(state['verified_at'])).total_seconds()
        failure=Path('/var/lib/optibrain/phase2a/last-failure.json')
        newer_failure=failure.exists() and datetime.fromisoformat(json.loads(failure.read_text())['time'])>datetime.fromisoformat(state['verified_at'])
        good=state['verification_status']=='download_hash_verified' and 0<=age<129600 and not newer_failure
        add('Off-host backup','OK' if good else 'ACTION REQUIRED','Independent upload readback is recent' if good else 'Off-host backup failed or stale',age_seconds=int(age))
    except (OSError,ValueError,KeyError):add('Off-host backup','UNKNOWN','Upload evidence unavailable')
    disk=shutil.disk_usage('/');pct=round(100*disk.used/disk.total,1)
    add('Disk','ACTION REQUIRED' if pct>=90 else 'DEGRADED' if pct>=80 else 'OK','Disk capacity sampled',used_percent=pct,free_bytes=disk.free)
    db_errors=[];db_bytes=0
    for name in DBS:
        path=DB_ROOT/name
        try:
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
                db.execute('PRAGMA query_only=ON')
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':db_errors.append(name)
            db_bytes+=path.stat().st_size
        except (OSError,sqlite3.Error):db_errors.append(name)
    add('DB health','ACTION REQUIRED' if db_errors else 'OK','SQLite check failed' if db_errors else 'Five active SQLite stores pass quick_check',checked=5,failed=len(db_errors),bytes=db_bytes)
    staging=size('/var/backups/optibrain')+size('/var/lib/optibrain/phase2a')
    app_logs=size('/var/lib/opticable-workflow-api/output/logs')
    journal=allocated_size('/var/log/journal')
    add('Growth',growth_state(staging,db_bytes,app_logs,journal),
        'Backup, database, application logs and bounded system journal sampled',
        backup_staging_bytes=staging,db_bytes=db_bytes,log_bytes=app_logs+journal,
        application_log_bytes=app_logs,system_journal_bytes=journal)
    control=json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
    env=dict(l.split('=',1) for l in Path('/etc/optibrain/phase12-runner.env').read_text().splitlines() if '=' in l and not l.startswith('#'))
    closed=control.get('test_writes_enabled') is False and control.get('real_canary_allowed') is False and env.get('OPTIBRAIN_BUSINESS_AUTO_WRITES')=='0' and not Path('/etc/optibrain/authorize-persistent-codex-development').exists()
    add('Safety flags','OK' if closed else 'ACTION REQUIRED','Business writes and development worker remain disabled' if closed else 'Safety configuration requires owner review',real_canary_allowed=control.get('real_canary_allowed'),automatic_writes=False if closed else None)
    receipt=json.loads(Path('/var/lib/optibrain/phase13-remediation/deployment.json').read_text())
    sha=subprocess.check_output(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','rev-parse','HEAD'],text=True,timeout=5).strip()
    manifest=json.loads(Path('/etc/optibrain/phase7-canary-registration.json').read_text())
    add('Deployment','OK' if receipt.get('sha')==sha==manifest.get('candidate_sha') else 'ACTION REQUIRED','Release receipt, source and manifest compared')
    resolved=resolved_read_reviews('/var/lib/optibrain/phase14/observer-reconciliation/lead-review-resolution.json',
        '/opt/opticable-api-platform/apps/workflow-api/workflow/automation/providers/crm_leads.py',DB_ROOT/'automation.db')
    spec=importlib.util.spec_from_file_location('activity_snapshot',Path(__file__).with_name('activity_snapshot.py'))
    activity=importlib.util.module_from_spec(spec);spec.loader.exec_module(activity)
    return dict(schema=1,captured_at=now.isoformat(),deployment_sha=sha,signals=signals,activity=activity.collect(DB_ROOT),
                resolved_read_only_failures=len(resolved),resolved_read_only_run_ids=resolved)


def main():
    if os.geteuid()!=0:raise PermissionError('Root sampler required')
    target=Path('/run/optibrain-readiness');target.mkdir(mode=0o755,exist_ok=True)
    value=collect()
    fd,name=tempfile.mkstemp(prefix='.status-',dir=target)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.chmod(name,0o644);os.replace(name,target/'status.json')
    print(json.dumps({'sampled_at':value['captured_at'],'signals':len(value['signals'])}))


if __name__=='__main__':main()
