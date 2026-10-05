"""Local, bounded activity projection. Reads only; never grants authority."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess

JOBS = {
    'opticable-phase9-intake-receipts': 'Forms and public intake',
    'opticable-phase10-service-events': 'CRM service observer',
    'opticable-phase12-test-runner': 'TEST_ONLY action runner',
    'opticable-lifecycle-internal': 'Authorized internal lifecycle',
    'opticable-customer-communications': 'Authorized customer communications',
    'optibrain-backup': 'Local backup',
    'optibrain-phase2a-upload': 'Encrypted off-host readback',
}


def timestamp(value):
    try:
        return datetime.strptime(value, '%a %Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def properties(unit):
    fields = ('ActiveState', 'UnitFileState', 'Result', 'ExecMainStatus', 'InvocationID',
              'ExecMainStartTimestamp', 'ExecMainExitTimestamp', 'LastTriggerUSec', 'NextElapseUSecRealtime')
    out = subprocess.check_output(['systemctl', 'show', unit, *[f'--property={k}' for k in fields]],
                                  env={'PATH': '/usr/bin:/bin', 'TZ': 'UTC', 'LC_ALL': 'C'}, text=True, timeout=5)
    return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)


def counters(name, messages):
    """Only fixed numeric counters leave the local journal; no message bodies."""
    result = {}
    def take(key, value):
        if type(value) is int and value >= 0:
            result[key] = value
    for raw in messages:
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                continue
            if name == 'opticable-phase9-intake-receipts':
                forms = value.get('form_mail', {})
                for key in ('scanned', 'created', 'replayed', 'conflicts_quarantined', 'invalid_messages', 'provider_reads'):
                    take('forms_' + key, forms.get(key))
                for key in ('created', 'replayed'):
                    take('connector_' + key, value.get('connector', {}).get(key))
            elif name == 'opticable-phase10-service-events':
                for key in ('service_count', 'added', 'total'):
                    take(key, value.get('service_events', {}).get(key))
                for key in ('delta_reads', 'full_reads', 'unchanged'):
                    take(key, value.get('display_inventory', {}).get(key))
            elif name == 'opticable-lifecycle-internal':
                for key in ('effects_this_cycle', 'eligible_leads', 'provider_reads'):
                    take(key, value.get(key))
            elif name == 'opticable-customer-communications':
                for key in ('sends_this_cycle', 'provider_reads'):
                    take(key, value.get(key))
            elif name == 'opticable-phase12-test-runner':
                source = value.get('counters', value)
                for key in ('evaluated', 'auto_executed', 'denials', 'writes', 'provider_failures', 'reconciliations'):
                    take('test_' + key, source.get(key))
        except (ValueError, TypeError, AttributeError):
            continue
    return result


def job(name):
    service, timer = properties(name + '.service'), properties(name + '.timer')
    start, end, tick = (timestamp(service.get('ExecMainStartTimestamp')),
                        timestamp(service.get('ExecMainExitTimestamp')), timestamp(timer.get('LastTriggerUSec')))
    scheduled = bool(start and tick and abs((start - tick).total_seconds()) <= 2)
    invocation = service.get('InvocationID', '')
    data = {}
    if re.fullmatch(r'[0-9a-f]{32}', invocation):
        out = subprocess.check_output(['journalctl', '--no-pager', '--output=json', '-n', '30',
                                       '_SYSTEMD_INVOCATION_ID=' + invocation], text=True, timeout=8)
        if len(out) <= 262144:
            data = counters(name, [json.loads(line).get('MESSAGE', '') for line in out.splitlines()])
    successful = bool(end and start and end >= start and service.get('Result') == 'success'
                      and service.get('ExecMainStatus') == '0')
    return dict(job=name, label=JOBS[name], starter=name + '.timer',
                timer_active=timer.get('ActiveState') == 'active', timer_enabled=timer.get('UnitFileState') == 'enabled',
                invocation_id=invocation, origin='SCHEDULED' if scheduled else 'MANUAL OR EXTERNAL / UNPROVEN',
                origin_proof='Timer last trigger matches service start within two seconds' if scheduled else
                             'No matching timer trigger; configuration is not execution proof',
                started_at=start.isoformat() if start else None, completed_at=end.isoformat() if end else None,
                last_timer_trigger=tick.isoformat() if tick else None,
                next_calendar_invocation=timer.get('NextElapseUSecRealtime') or None,
                state='COMPLETED' if successful else 'RUNNING' if service.get('ActiveState') in ('active', 'activating') else 'BLOCKED',
                counters=data)


def inquiry_counts(path):
    """Canonical acknowledged receipts, not submit clicks or repeated poll reads."""
    with sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=2) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute('SELECT r.occurred_at, r.test_only, c.event_id, r.provider_message_id '
                          'FROM form_receipts r LEFT JOIN form_test_classifications c ON c.event_id=r.event_id '
                          "WHERE NOT EXISTS (SELECT 1 FROM form_message_anomalies a WHERE "
                          "a.existing_event_id=r.event_id AND a.kind='IMMUTABLE_RECEIPT_CONFLICT')").fetchall()
        quarantined = db.execute("SELECT COUNT(*) FROM form_message_anomalies WHERE kind='IMMUTABLE_RECEIPT_CONFLICT'").fetchone()[0]
    return dict(confirmed_test_inquiries=sum(bool(r[1] or r[2]) for r in rows),
                confirmed_non_test_inquiries=sum(not (r[1] or r[2]) for r in rows), quarantined_conflicts=quarantined,
                last_acknowledged_at=max((r[0] for r in rows), default=None),
                proof='Authenticated native Mail receipts; counts exclude quarantine and deduplicate provider identity')


def collect(db_root):
    rows = []
    for name in JOBS:
        try:
            rows.append(job(name))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            rows.append(dict(job=name, label=JOBS[name], state='UNKNOWN', origin='UNKNOWN', counters={}))
    try:
        inquiries = inquiry_counts(Path(db_root) / 'phase9-form-receipts.db')
    except (OSError, sqlite3.Error):
        inquiries = dict(state='UNKNOWN', proof='Receipt observation unavailable; no zero assumed')
    return dict(schema=1, read_only=True, owner_timezone='America/Toronto', jobs=rows, inquiries=inquiries,
                coverage='Latest invocation per job; this is not a 24-hour effect total. TEST counts are separate. '
                         'Research/enrichment is manually initiated. Claude/Apollo activity is not attributed to OptiBrain.')
