"""Provider-free readiness from durable observations; never repairs state."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

RUNTIME = Path('/run/optibrain-readiness/status.json')
STATES = ('OK', 'UNKNOWN', 'DEGRADED', 'ACTION REQUIRED')


def age_seconds(value, now):
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if instant.utcoffset() is None or instant > now:
            return None
        return int((now-instant).total_seconds())
    except (ValueError, TypeError, AttributeError):
        return None


def signal(name, state, reason, *, at=None, **details):
    if state not in STATES:
        raise ValueError('Invalid readiness state')
    return dict(name=name, state=state, reason=reason, observed_at=at, **details)


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def provider_read_signal(directory, name, kind, now, max_age):
    latest = None
    for path in sorted(directory.glob('*.db')):
        try:
            with readonly(path) as db:
                rows = db.execute('SELECT recorded_at,summary_json FROM provider_usage ORDER BY id DESC LIMIT 300').fetchall()
            for row in rows:
                summary = json.loads(row['summary_json'])
                if summary.get('calls', {}).get(kind, 0) and (latest is None or row['recorded_at']>latest[0]):
                    latest = (row['recorded_at'], summary)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            continue
    if latest is None:
        return signal(name, 'UNKNOWN', 'No measured provider read yet')
    at, summary = latest
    age = age_seconds(at, now)
    failed = summary.get('status')!='success' or summary.get('outcomes', {}).get(kind+'::failed', 0)>0
    state = 'ACTION REQUIRED' if failed else 'DEGRADED' if age is None or age>max_age else 'OK'
    return signal(name, state, 'Last observed read failed' if failed else
                  'Last observed read is stale' if state!='OK' else 'Recent read succeeded', at=at, age_seconds=age)


def build_readiness(store, native, *, api_version, auth_configured, runtime_path=RUNTIME, now=None):
    now = now or datetime.now(timezone.utc)
    rows = [signal('API', 'OK', 'API process is responding', at=now.isoformat(), version=api_version),
            signal('Auth', 'OK' if auth_configured else 'ACTION REQUIRED',
                   'Authentication is configured and required' if auth_configured else 'Credentials absent; requests are denied')]
    directory = Path(store.db_path).parent
    rows.extend([provider_read_signal(directory,'CRM reads','crm_get',now,7200),
                 provider_read_signal(directory,'Mail reads','mail_get',now,7200)])
    try:
        with readonly(store.db_path) as db:
            checkpoints = db.execute('SELECT status,last_error,last_success_at FROM automation_sync_checkpoints').fetchall()
        if not checkpoints:
            rows.append(signal('Delta checkpoint','UNKNOWN','No configured checkpoint'))
        else:
            bad = any(c['status'] in {'failed','resync_required'} for c in checkpoints)
            stale = any(age_seconds(c['last_success_at'],now) is None or age_seconds(c['last_success_at'],now)>900 for c in checkpoints)
            rows.append(signal('Delta checkpoint','ACTION REQUIRED' if bad else 'DEGRADED' if stale else 'OK',
                               'Observation stopped; reconcile the saved checkpoint' if bad else
                               'Observation is stale' if stale else 'Incremental observation is current',
                               checkpoint_count=len(checkpoints), failed_count=sum(c['status'] in {'failed','resync_required'} for c in checkpoints)))
        health = store.execution_health()
        blocked = sum(health.get(k,0) for k in ('stale_queued','stale_running','expired_leases','dead_letter','failed'))
        rows.append(signal('Queue','ACTION REQUIRED' if blocked else 'OK',
                           'Work requires reconciliation' if blocked else 'No stale or failed queued work',
                           queued=health.get('queued',0),running=health.get('running',0),blocked=blocked))
        rows.append(signal('Retained exceptions','OK','Retained runs are separate from current business attention',
                           retained_human_review=health.get('human_action_required',0)))
    except (OSError,sqlite3.Error):
        rows.extend([signal('Delta checkpoint','UNKNOWN','Checkpoint unavailable'),signal('Queue','UNKNOWN','Queue state unavailable')])
    status = native.get('native_subscription_status','unconfigured')
    at = native.get('native_subscription_last_verified_at')
    rows.append(signal('Native watch','OK' if status=='verified' else 'UNKNOWN' if status=='unconfigured' else 'ACTION REQUIRED',
                       'Notification binding verified' if status=='verified' else 'Notification verification needs review',
                       at=at,verification_status=status,expiry=native.get('native_subscription_expires_at')))
    try:
        snapshot = json.loads(Path(runtime_path).read_text())
        age = age_seconds(snapshot.get('captured_at'), now)
        if snapshot.get('schema')!=1 or age is None or age>5400:
            raise ValueError('Stale runtime snapshot')
        for item in snapshot['signals']:
            # Root sampler emits only fixed names, categories and numeric metadata.
            rows.append(signal(item['name'],item['state'],item['reason'],at=snapshot['captured_at'],
                               **{k:v for k,v in item.items() if k not in {'name','state','reason','observed_at'}}))
        deployed_sha = snapshot.get('deployment_sha')
    except (OSError, ValueError, TypeError, KeyError):
        deployed_sha = None
        rows.extend(signal(name,'UNKNOWN','Runtime sample absent or stale') for name in
                    ('Timers','Backup','Off-host backup','Disk','DB health','Growth','Safety flags','Deployment'))
    rows.append(signal('Cloudflare queue depth','UNKNOWN','Remote queue depth has not been independently measured'))
    state = max((r['state'] for r in rows), key=STATES.index)
    return {'schema':1,'state':state,'read_only':True,'captured_at':now.isoformat(),
            'deployment_sha':deployed_sha,'signals':rows}
