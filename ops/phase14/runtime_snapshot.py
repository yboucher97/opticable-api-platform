#!/usr/bin/env python3
"""Root-installed local sampler. No credentials, provider calls or repair actions."""
from datetime import datetime, timezone
import json
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


def size(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file() and not p.is_symlink())


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
    logs=size('/var/lib/opticable-workflow-api/output/logs')
    add('Growth','ACTION REQUIRED' if staging>25*1024**3 or db_bytes>512*1024**2 or logs>512*1024**2 else
        'DEGRADED' if staging>15*1024**3 or db_bytes>128*1024**2 or logs>128*1024**2 else 'OK',
        'Storage thresholds sampled',backup_staging_bytes=staging,db_bytes=db_bytes,log_bytes=logs)
    control=json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
    env=dict(l.split('=',1) for l in Path('/etc/optibrain/phase12-runner.env').read_text().splitlines() if '=' in l and not l.startswith('#'))
    closed=control.get('test_writes_enabled') is False and control.get('real_canary_allowed') is False and env.get('OPTIBRAIN_BUSINESS_AUTO_WRITES')=='0' and not Path('/etc/optibrain/authorize-persistent-codex-development').exists()
    add('Safety flags','OK' if closed else 'ACTION REQUIRED','Business writes and development worker remain disabled' if closed else 'Safety configuration requires owner review',real_canary_allowed=control.get('real_canary_allowed'),automatic_writes=False if closed else None)
    receipt=json.loads(Path('/var/lib/optibrain/phase13-remediation/deployment.json').read_text())
    sha=subprocess.check_output(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','rev-parse','HEAD'],text=True,timeout=5).strip()
    manifest=json.loads(Path('/etc/optibrain/phase7-canary-registration.json').read_text())
    add('Deployment','OK' if receipt.get('sha')==sha==manifest.get('candidate_sha') else 'ACTION REQUIRED','Release receipt, source and manifest compared')
    return dict(schema=1,captured_at=now.isoformat(),deployment_sha=sha,signals=signals)


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
