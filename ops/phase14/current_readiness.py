"""Project existing NEW-host evidence into the existing readiness contract.

No provider calls, refreshes, application imports, repairs, schedules or alerts.
Invoked by the existing resource sampler only after a reviewed installation.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess

EXPECTED_JOBS = {
    'optibrain-backup': 129600, 'optibrain-phase2a-upload': 129600,
    'opticable-phase9-intake-receipts': 900,
    'opticable-phase10-service-events': 9000,
    'optibrain-resource-sample': 2700, 'optibrain-credential-refresh': 3600,
    'optibrain-operations': 900, 'optibrain-operations-capabilities': 129600,
    'optibrain-business-observer': 9000, 'optibrain-platform-intelligence': 129600,
    'optibrain-local-retention': 129600,
}
API_UNITS = {'opticable-workflow-api.service', 'opticable-password-pdf.service',
             'opticable-omada-site.service'}
GIB = 1024**3


def age(value, now):
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        seconds = (now - instant).total_seconds()
        return seconds if instant.utcoffset() is not None and seconds >= 0 else None
    except (ValueError, TypeError, AttributeError):
        return None


def read_json(path, *, trusted=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024**2
                    or trusted and (info.st_uid != 0 or info.st_mode & 0o022)):
                return {}
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def offhost_evidence(proof, generation, now):
    """Project the existing root readback/restore receipt, never an upload ACK.

    Retention writes this receipt only after a complete authenticated R2 GET,
    ciphertext hash comparison and isolated restore. Sampling it does not repeat
    provider reads or change its original verification timestamp.
    """
    unknown = dict(state='UNKNOWN', proof_age_seconds=None, original_observed_at=None)
    if not isinstance(proof, dict) or not isinstance(generation, str) or not re.fullmatch(r'\d{8}T\d{6}Z', generation):
        return unknown
    metadata, restored = proof.get('prepared_metadata'), proof.get('restore')
    if not isinstance(metadata, dict) or not isinstance(restored, dict):
        return unknown
    observed = proof.get('at')
    if type(observed) not in (int, float) or not math.isfinite(observed):
        return unknown
    seconds = now.timestamp() - observed
    if seconds < 0:
        return unknown
    key = f'backups/{generation[:4]}/{generation[4:6]}/{generation[6:8]}/{generation}.tar.gz.age'
    plaintext, ciphertext = proof.get('plaintext_sha256'), proof.get('ciphertext_sha256')
    hashes = (plaintext, ciphertext, metadata.get('recipient_sha256'))
    if (not all(isinstance(h, str) and re.fullmatch(r'[0-9a-f]{64}', h) for h in hashes)
            or proof.get('generation') != generation or metadata.get('generation') != generation
            or proof.get('remote_object_key') != key or metadata.get('object_key') != key
            or type(proof.get('remote_bytes')) is not int or not 0 < proof['remote_bytes'] <= 20 * GIB
            or metadata.get('source_sha256') != plaintext or metadata.get('encrypted_sha256') != ciphertext
            or restored.get('result') != 'PASS' or restored.get('source_extraction') != 'PASS'
            or restored.get('generation') != generation or restored.get('source_sha256') != plaintext
            or not isinstance(restored.get('source_commit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', restored['source_commit'])
            or type(restored.get('databases_restored')) is not int or restored['databases_restored'] < 1):
        return unknown
    return dict(state='OK' if seconds < 129600 else 'ACTION REQUIRED',
                proof_age_seconds=seconds, original_observed_at=observed)


def build_snapshot(resource, jobs, safety, deployment, credential, *, now):
    """Pure, bounded projection; old observations keep their original timestamps."""
    signals = []
    def add(name, state, reason, **details):
        signals.append(dict(name=name, state=state, reason=reason, **details))
    valid_jobs = (isinstance(jobs, list) and len(jobs) == len(EXPECTED_JOBS)
                  and all(isinstance(j, dict) for j in jobs)
                  and {j.get('job') for j in jobs} == set(EXPECTED_JOBS))
    if not valid_jobs:
        add('Timers', 'UNKNOWN', 'Current required-job inventory is incomplete')
    else:
        bad = any(j.get('timer_active') is False or j.get('state') in {'FAILED', 'TIMED_OUT'} for j in jobs)
        unknown = any(j.get('timer_active') is None or j.get('state') not in
                      {'COMPLETED_SUCCESS', 'RUNNING', 'STALE_COMPLETION', 'FAILED', 'TIMED_OUT'} for j in jobs)
        stale = any(j.get('state') == 'STALE_COMPLETION' for j in jobs)
        add('Timers', 'ACTION REQUIRED' if bad else 'UNKNOWN' if unknown else 'DEGRADED' if stale else 'OK',
            'Current authorized service invocations; retired TEST runner is not an expectation',
            expected=len(EXPECTED_JOBS), jobs=jobs)
    sample_age = age(resource.get('at'), now)
    fresh = sample_age is not None and sample_age <= 2700
    if not fresh:
        for name in ('Backup', 'Off-host backup', 'Disk', 'DB health', 'Growth'):
            add(name, 'UNKNOWN', 'Existing resource observation is absent, invalid or stale')
    else:
        backup_age = resource.get('backup_age_hours')
        good_age = type(backup_age) in (int, float) and math.isfinite(backup_age) and backup_age >= 0
        backup_seconds = backup_age * 3600 + sample_age if good_age else None
        add('Backup', 'OK' if deployment.get('local_recovery_verified') is True and backup_seconds is not None and backup_seconds < 129600
            else 'ACTION REQUIRED', 'Current verified local recovery generation',
            generation=resource.get('backup_generation'), verified_age_seconds=backup_seconds)
        remote = offhost_evidence(deployment.get('recovery_proof'), resource.get('backup_generation'), now)
        remote_state = remote.pop('state')
        if backup_seconds is None:
            remote_state = 'UNKNOWN'
        elif backup_seconds >= 129600 and remote_state == 'OK':
            remote_state = 'ACTION REQUIRED'
        add('Off-host backup', remote_state,
            'Existing complete-object download/hash proof; no offline private-key decryption claim',
            verified_age_seconds=backup_seconds, offline_decryption_verified=False, **remote)
        free = resource.get('available')
        valid_free = type(free) is int and free >= 0
        add('Disk', 'UNKNOWN' if not valid_free else 'ACTION REQUIRED' if free < 35 * GIB else 'DEGRADED' if free < 50 * GIB else 'OK',
            'Existing measured capacity thresholds', free_bytes=free if valid_free else None,
            target_bytes=60 * GIB, working_cushion_bytes=68 * GIB)
        checks = resource.get('database_checks', {})
        checks_age = age(checks.get('at'), now)
        databases = checks.get('databases', [])
        valid_checks = (checks_age is not None and checks_age < 30 * 3600
                        and isinstance(databases, list) and bool(databases)
                        and all(isinstance(d, dict) for d in databases)
                        and len({d.get('name') for d in databases}) == len(databases)
                        and {'automation.db', 'phase9-form-receipts.db', 'phase9-intake.db',
                             'phase10-service-events.db', 'phase12-autonomy.db'} <= {d.get('name') for d in databases})
        failed = valid_checks and any(d.get('quick_check') == 'FAILED' for d in databases)
        all_ok = valid_checks and all(d.get('quick_check') == 'ok' for d in databases)
        add('DB health', 'ACTION REQUIRED' if failed else 'OK' if all_ok else 'UNKNOWN',
            'Reuse scheduled SQLite integrity evidence; do not repeat checks every sample',
            checked=len(databases) if isinstance(databases, list) else 0,
            original_observed_at=checks.get('at'))
        growth = [a for a in resource.get('alerts', []) if a.get('key') in
                  {'abnormal_growth', 'disk_forecast', 'oom', 'swap'} or a.get('key', '').startswith(('wal:', 'scratch:'))]
        add('Growth', 'ACTION REQUIRED' if any(a.get('severity') in {'CRITICAL', 'EMERGENCY'} for a in growth)
            else 'DEGRADED' if growth else 'OK', 'Reuse measured trends; no legacy archive-size ceiling',
            active_growth_alerts=len(growth), original_observed_at=resource.get('at'))
    flags = safety.get('flag_checks')
    valid_flags = isinstance(flags, list) and len(flags) == 45 and all(type(f) is bool for f in flags)
    add('Safety flags', 'UNKNOWN' if not valid_flags else 'OK' if all(flags) and safety.get('controls_closed') is True else 'ACTION REQUIRED',
        'Actual current process flags and existing authority policies; nothing is changed',
        checked=len(flags) if isinstance(flags, list) else 0)
    sha = deployment.get('actual_sha')
    valid_sha = isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha)
    correct = valid_sha and sha == deployment.get('registered_sha') and deployment.get('authoritative_host') is True
    add('Deployment', 'OK' if correct else 'ACTION REQUIRED',
        'Current NEW registration and checkout; phase13 receipt remains historical evidence')
    credential_age = now.timestamp() - credential.get('at', -1) if type(credential.get('at')) in (int, float) else None
    values = credential.get('results', {})
    fresh_credential = credential_age is not None and 0 <= credential_age <= 3600
    if not fresh_credential or not isinstance(values, dict) or set(values) != {'GOOGLE', 'ZOHO'}:
        state = 'UNKNOWN'
    else:
        states = [v.get('status') for v in values.values() if isinstance(v, dict)]
        accepted = {'VERIFIED', 'VERIFIED_OPERATIONAL_CACHE', 'REFRESHED_PRIVATE_CACHE_AND_VERIFIED', 'VERIFIED_CURRENT'}
        state = 'ACTION REQUIRED' if 'BLOCKED' in states else 'OK' if len(states) == 2 and all(v in accepted for v in states) else 'UNKNOWN'
    add('Credential refresh', state, 'Existing bound same-user refresh evidence; no second cache or provider probes',
        original_observed_at=credential.get('at'))
    return dict(schema=1, captured_at=now.isoformat(), deployment_sha=sha if valid_sha else None,
                signals=signals, resolved_read_only_run_ids=[],
                evidence_source='existing-current-services', provider_calls=0, mutations=0,
                resource_observed_at=resource.get('at'))


def collect(classify_job, service_fields, *, now=None):
    now = now or datetime.now(timezone.utc)
    resource = read_json('/var/lib/optibrain/resource-management/latest.json', trusted=True)
    jobs = []
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    for name, deadline in EXPECTED_JOBS.items():
        try:
            text = subprocess.check_output(['systemctl', 'show', name + '.service',
                *['--property=' + k for k in service_fields]], text=True, timeout=5)
            invocation = classify_job(dict(line.split('=', 1) for line in text.splitlines() if '=' in line),
                                      uptime=uptime, freshness_seconds=deadline)
            timer = subprocess.run(['systemctl', 'is-active', name + '.timer'], capture_output=True,
                                   text=True, timeout=5, check=False).stdout.strip()
            timer_active = True if timer == 'active' else False if timer in {'inactive', 'failed'} else None
        except (OSError, subprocess.SubprocessError):
            invocation, timer_active = {'state': 'UNKNOWN'}, None
        jobs.append(dict(job=name, timer_active=timer_active, **invocation))
    safety = {'flag_checks': []}
    registry = read_json('/var/lib/optibrain/autonomous-operations/45-runtime-flags.json', trusted=True)
    if isinstance(registry, list) and len(registry) == 45 and len({(r['unit'], r['flag']) for r in registry}) == 45:
        process = {}
        for unit in API_UNITS:
            pid = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '--value'], text=True, timeout=5).strip()
            try:
                process[unit] = dict(v.split('=', 1) for v in Path('/proc/' + str(int(pid)) + '/environ').read_text().split('\0') if '=' in v)
            except (OSError, ValueError):
                process[unit] = {}
        safety['flag_checks'] = [r.get('unit') in API_UNITS and
            process.get(r.get('unit'), {}).get(r.get('flag')) == r.get('expected_disabled_value') for r in registry]
    control = read_json('/etc/optibrain/mutation-control.json', trusted=True)
    customer = read_json('/etc/optibrain/customer-communication-control.json', trusted=True)
    safety['controls_closed'] = (control.get('test_writes_enabled') is False and control.get('real_canary_allowed') is False
        and control.get('lifecycle', {}).get('enabled') is False
        and customer.get('external_enabled') is False and customer.get('test_enabled') is False)
    registration = read_json('/etc/optibrain/phase7-canary-registration.json', trusted=True)
    sha = subprocess.check_output(['git', '-c', 'safe.directory=/opt/opticable-api-platform', '-C',
                                  '/opt/opticable-api-platform', 'rev-parse', 'HEAD'], text=True, timeout=5).strip()
    generation = resource.get('backup_generation')
    proof = read_json('/var/lib/optibrain/autonomous-operations/retention-generation-proofs/' +
                      generation + '.json', trusted=True) if isinstance(generation, str) and re.fullmatch(r'\d{8}T\d{6}Z', generation) else {}
    if not isinstance(proof, dict):
        proof = {}
    restored = proof.get('restore')
    if not isinstance(restored, dict):
        restored = {}
    archive_path = proof.get('archive_path')
    verified_local = (proof.get('generation') == resource.get('backup_generation')
                      and restored.get('result') == 'PASS'
                      and isinstance(proof.get('plaintext_sha256'), str)
                      and re.fullmatch(r'[0-9a-f]{64}', proof['plaintext_sha256']) is not None
                      and isinstance(archive_path, str) and Path(archive_path).is_file())
    deployment = dict(actual_sha=sha, registered_sha=registration.get('candidate_sha'),
        authoritative_host=os.uname().nodename == 'vps-f8e9b20e' and Path('/etc/optibrain-rebuild-target').is_file(),
        local_recovery_verified=bool(verified_local), recovery_proof=proof)
    credential = read_json('/var/lib/opticable-workflow-api/output/automation/credential-health.json')
    return build_snapshot(resource, jobs, safety, deployment, credential, now=now)
