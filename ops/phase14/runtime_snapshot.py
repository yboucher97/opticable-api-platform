#!/usr/bin/env python3
"""Root-installed local sampler. No credentials, provider calls or repair actions."""
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

TIMERS = {'optibrain-backup':172800,'optibrain-phase2a-upload':172800,
          'opticable-phase9-intake-receipts':900,'opticable-phase10-service-events':9000,
          'opticable-phase12-test-runner':5400}
DB_ROOT = Path('/var/lib/opticable-workflow-api/output/automation')
DBS = ('automation.db','phase9-form-receipts.db','phase9-intake.db',
       'phase10-service-events.db','phase12-autonomy.db')


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
    failed=[];stale=[]
    for name,deadline in TIMERS.items():
        output=subprocess.check_output(['systemctl','show',name+'.service','-p','Result','-p','ExecMainStatus','-p','ExecMainExitTimestampMonotonic'],text=True,timeout=5)
        props=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
        active=subprocess.run(['systemctl','is-active',name+'.timer'],text=True,stdout=subprocess.PIPE,timeout=5,check=False).stdout.strip()
        elapsed=float(Path('/proc/uptime').read_text().split()[0])-int(props.get('ExecMainExitTimestampMonotonic','0'))/1_000_000
        if props.get('Result')!='success' or props.get('ExecMainStatus')!='0' or active!='active':failed.append(name)
        elif elapsed>deadline:stale.append(name)
    add('Timers','ACTION REQUIRED' if failed else 'DEGRADED' if stale else 'OK',
        'Scheduled job failed or disabled' if failed else 'Scheduled result is stale' if stale else 'Five expected timers have successful recent results',
        expected=5,failed=len(failed),stale=len(stale))
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
    return dict(schema=1,captured_at=now.isoformat(),deployment_sha=sha,signals=signals,
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
