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
    failed = summary.get('status')!='success' or summary.get('last_response',{}).get(kind)=='failed'
    state = 'ACTION REQUIRED' if failed else 'DEGRADED' if age is None or age>max_age else 'OK'
    return signal(name, state, 'Last observed read failed' if failed else
                  'Last observed read is stale' if state!='OK' else 'Recent read succeeded', at=at, age_seconds=age)


def usage_anomalies(directory,now):
    recent={}
    for path in sorted(directory.glob('*.db')):
        try:
            with readonly(path) as db:
                rows=db.execute('SELECT recorded_at,summary_json FROM provider_usage ORDER BY id DESC LIMIT 300').fetchall()
            for row in rows:
                age=age_seconds(row['recorded_at'],now)
                if age is None or age>7200:continue
                value=json.loads(row['summary_json']);job=value['job']
                if value.get('schema')!=2:continue
                recent.setdefault(job,[]).append((row['recorded_at'],value.get('budget_exceeded',False)))
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):continue
    count=sum(len(values)>=2 and all(flag for _,flag in sorted(values,reverse=True)[:2]) for values in recent.values())
    return signal('Provider call anomalies','DEGRADED' if count else 'OK',
                  'Repeated soft-budget excess requires review' if count else 'No repeated recent soft-budget excess',jobs_over_budget=count)


def build_readiness(store, native, *, api_version, auth_configured, runtime_path=RUNTIME, now=None):
    now = now or datetime.now(timezone.utc)
    rows = [signal('API', 'OK', 'API process is responding', at=now.isoformat(), version=api_version),
            signal('Auth', 'OK' if auth_configured else 'ACTION REQUIRED',
                   'Authentication is configured and required' if auth_configured else 'Credentials absent; requests are denied')]
    directory = Path(store.db_path).parent
    rows.extend([provider_read_signal(directory,'CRM reads','crm_get',now,7200),
                 provider_read_signal(directory,'Mail reads','mail_get',now,7200)])
    rows.append(usage_anomalies(directory,now))
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
        try:
            sample=json.loads(Path(runtime_path).read_text())
            sample_age=age_seconds(sample.get('captured_at'),now)
            ids=sample.get('resolved_read_only_run_ids',[]) if sample.get('schema')==1 and sample_age is not None and sample_age<=5400 else []
            resolved=0
            if isinstance(ids,list) and 0<len(ids)<=20 and all(isinstance(i,str) for i in ids) and len(set(ids))==len(ids):
                with readonly(store.db_path) as db:
                    resolved=db.execute("SELECT COUNT(DISTINCT r.run_id) FROM automation_runs r JOIN automation_run_steps s ON s.run_id=r.run_id "
                        "WHERE r.status='failed' AND r.workflow_id='opticable.crm.lead-observe' AND s.action='crm.lead.observe' "
                        "AND s.error='EventConflict' AND r.run_id IN ("+','.join('?' for _ in ids)+')',ids).fetchone()[0]
        except (OSError,ValueError,TypeError):resolved=0
        blocked = sum(health.get(k,0) for k in ('stale_queued','stale_running','expired_leases','dead_letter','failed'))-resolved
        rows.append(signal('Queue','ACTION REQUIRED' if blocked else 'OK',
                           'Work requires reconciliation' if blocked else 'No stale or failed queued work',
                           queued=health.get('queued',0),running=health.get('running',0),blocked=blocked))
        pending=health.get('human_action_required',0)
        rows.append(signal('Retained exceptions','UNKNOWN' if pending else 'OK',
                           'Retained review items are unclassified; review provenance before treating them as current failures'
                           if pending else 'No unclassified retained review items; reconciled reads remain historical evidence',
                           retained_human_review=pending,reconciled_read_only_failures=resolved,
                           exception_states={'UNCLASSIFIED REVIEW':pending,'RESOLVED READ-ONLY':resolved},
                           accepted_exceptions=0))
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
    rows.append(queue_depth_signal(now))
    state = max((r['state'] for r in rows), key=STATES.index)
    return {'schema':1,'state':state,'read_only':True,'captured_at':now.isoformat(),
            'deployment_sha':deployed_sha,'signals':rows}


def queue_depth_signal(now, path=Path('/run/optibrain-readiness/queue-depth.json')):
    try:
        value = json.loads(Path(path).read_text())
        age = age_seconds(value.get('captured_at'), now)
        queues = value['queues']
        if (value.get('schema') != 1 or value.get('status') != 'measured'
                or age is None or age > 5400 or set(queues) !=
                {'opticable-business-events', 'opticable-business-events-dlq'}):
            raise ValueError('Queue observation unavailable or stale')
        counts = [queues[name]['backlog_count'] for name in queues]
        if any(type(n) is not int or n < 0 for n in counts):
            raise ValueError('Invalid queue count')
        oldest = queues['opticable-business-events']['oldest_message_timestamp_ms']
        if type(oldest) is not int or oldest < 0 or oldest > int(now.timestamp()*1000):
            raise ValueError('Invalid oldest message timestamp')
        active = queues['opticable-business-events']['backlog_count']
        stalled = bool(active and oldest and now.timestamp()*1000-oldest > 1800000)
        dlq = queues['opticable-business-events-dlq']['backlog_count']
        state = 'ACTION REQUIRED' if dlq or stalled else 'DEGRADED' if active > 100 else 'OK'
        return signal('Cloudflare queue depth',state,
                      'Dead-letter or stalled delivery needs reconciliation' if dlq or stalled else
                      'Approximate read-only queue backlog measured',at=value['captured_at'],
                      approximate=True,age_seconds=age,queues=queues)
    except (OSError,ValueError,TypeError,KeyError):
        return signal('Cloudflare queue depth','UNKNOWN',
                      'Queue metrics unavailable or stale; inspect the read-only sampler')
