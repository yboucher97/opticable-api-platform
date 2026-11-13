"""GitHub + encrypted R2 recovery contracts and an independent fixture supervisor.

Production authority remains in the existing root release gate. This supervisor
can execute only in an explicitly granted unprivileged development workspace.
It changes exact code/config files; there is no database/VM restoration path.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .acquisition_store import digest
from .action_evidence import ActionEvidence, envelope, local_record, stamp
from .operational_recovery import DevelopmentScope, recovery_holds

REPOSITORY = 'yboucher97/opticable-api-platform'
PROTECTED = re.compile(r'(^|/)(\.git(?:/|$)|\.github(?:/|$)|.*(?:\.db|\.sqlite|\.sqlite3)(?:$|-)|.*(?:-wal|-shm)$|.*\.env(?:$|\.)|.*(?:credential|secret|oauth|sudoers|mutation.control|business.autonomy|master.runbook|safety|approval|authorization|policy).*)', re.I)
CONTROL_FILES = {'manual-guarded-release.py', 'operational_recovery.py',
                 'release_recovery.py', 'defect_development.py', 'repair_catalog.py',
                 'production_repair_catalog.json'}


class ExistingR2Reader:
    """Reuse an existing authenticated SigV4 client; never provision credentials."""
    def __init__(self, client):
        if (not re.fullmatch(r'https://[0-9a-f]{32}\.r2\.cloudflarestorage\.com/?', client.meta.endpoint_url)
                or client.meta.config.signature_version != 's3v4'):
            raise ValueError('Existing authenticated Cloudflare R2 SigV4 client required')
        self.client = client

    def __call__(self, bucket, key):
        if bucket != 'optibrain-recovery-prod':raise ValueError('Trusted recovery bucket required')
        head = self.client.head_object(Bucket=bucket, Key=key)
        response = self.client.get_object(Bucket=bucket, Key=key, IfMatch=head['ETag'])
        body = response['Body']
        return dict(authenticated=True, bucket=bucket, key=key, content_length=response['ContentLength'],
                    chunks=body.iter_chunks(1024**2), close=body.close)


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def checked_path(value):
    p = Path(value)
    if (not isinstance(value, str) or p.is_absolute() or value != p.as_posix()
            or not p.parts or '..' in p.parts or PROTECTED.search(value) or p.name in CONTROL_FILES
            or p.suffix not in {'.py', '.json', '.toml', '.conf', '.txt', '.js', '.ts'}):
        raise ValueError('Only exact non-security code/config targets are supported')
    return value


def verify_checkpoint(expected, archive, *, github_read, r2_read, isolated_restore, now):
    """Independent verifier: real read callbacks, complete bounded ciphertext hash.

    Callbacks are supplied by the existing trusted GitHub App, SigV4 R2 client
    and isolated restore validator. An upload receipt or a boolean is insufficient.
    """
    required = {'repository', 'last_good_sha', 'generation', 'archive_sha256',
                'ciphertext_sha256', 'remote_bytes', 'r2_bucket', 'r2_object_key'}
    if not isinstance(expected, dict) or not required <= set(expected) or expected['repository'] != REPOSITORY:
        raise ValueError('Exact recovery inventory required')
    for key, size in [('last_good_sha', 40), ('archive_sha256', 64), ('ciphertext_sha256', 64)]:
        if not re.fullmatch('[0-9a-f]{' + str(size) + '}', str(expected[key])):
            raise ValueError('Exact source/archive/object identity required')
    if not re.fullmatch(r'\d{8}T\d{6}Z', expected['generation']):
        raise ValueError('Exact backup generation required')
    if expected['r2_bucket'] != 'optibrain-recovery-prod' or not isinstance(expected['r2_object_key'], str) or not 1 <= len(expected['r2_object_key']) <= 512:
        raise ValueError('Existing trusted recovery bucket/object required')
    if type(expected['remote_bytes']) is not int or not 0 < expected['remote_bytes'] <= 20 * 1024**3:
        raise ValueError('Bounded complete-object length required')
    commit = github_read(REPOSITORY, expected['last_good_sha'])
    if (not isinstance(commit, dict) or commit.get('sha') != expected['last_good_sha']
            or commit.get('repository') != REPOSITORY or commit.get('authenticated_read') is not True):
        raise ValueError('Authenticated exact GitHub last-known-good read required')
    if file_sha(archive) != expected['archive_sha256']:
        raise ValueError('Local consistent recovery archive changed')
    stream = r2_read(expected['r2_bucket'], expected['r2_object_key'])
    h = hashlib.sha256();count = 0;prefix = b''
    try:
        if (stream.get('authenticated') is not True or stream.get('bucket') != expected['r2_bucket']
                or stream.get('key') != expected['r2_object_key'] or stream.get('content_length') != expected['remote_bytes']):
            raise ValueError('Authenticated exact complete-object GET required')
        for chunk in stream['chunks']:
            if not isinstance(chunk, bytes) or len(chunk) > 1024**2:
                raise ValueError('Bounded byte stream required')
            count += len(chunk)
            if count > expected['remote_bytes']:
                raise ValueError('Object exceeds verified size')
            h.update(chunk)
            if len(prefix) < 64:
                prefix = (prefix + chunk)[:64]
    finally:
        close = stream.get('close')
        if callable(close):close()
    if (count != expected['remote_bytes'] or h.hexdigest() != expected['ciphertext_sha256']
            or not prefix.startswith(b'age-encryption.org/v1\n')):
        raise ValueError('Ciphertext incomplete, changed or AGE header absent')
    restored = isolated_restore(Path(archive), expected['archive_sha256'])
    if (not isinstance(restored, dict) or restored.get('result') != 'PASS'
            or restored.get('source_commit') != expected['last_good_sha']
            or restored.get('source_extraction') != 'PASS'
            or type(restored.get('databases_restored')) is not int or restored['databases_restored'] < 1
            or restored.get('generation') != expected['generation']):
        raise ValueError('Independent isolated source/database restoration required')
    return dict(schema=1, verified_at=now.isoformat(), **expected,
                authenticated_complete_readback=True, isolated_restore='PASS',
                databases_restored=restored['databases_restored'],
                offline_private_age_decryption=False, last_good_github_read=True)


def contract_digest(contract):
    return digest({k: v for k, v in contract.items() if k != 'approval'})


def validate_contract(contract, trusted_receipt, *, expected_digest, now):
    if (not isinstance(contract, dict) or contract.get('schema') != 1
            or contract.get('repository') != REPOSITORY
            or contract.get('environment') not in {'production', 'isolated-development'}
            or contract_digest(contract) != expected_digest):
        raise ValueError('Exact independently supplied release-contract digest required')
    for key in ('last_good_sha', 'candidate_sha'):
        if not re.fullmatch('[0-9a-f]{40}', str(contract.get(key, ''))):
            raise ValueError('Exact GitHub source commits required')
    if contract['last_good_sha'] == contract['candidate_sha']:
        raise ValueError('Distinct candidate and last-known-good commits required')
    receipt_age = now - stamp(trusted_receipt['verified_at']) if stamp(trusted_receipt.get('verified_at')) else None
    if (trusted_receipt.get('schema') != 1 or receipt_age is None or not timedelta(0) <= receipt_age <= timedelta(hours=36)
            or trusted_receipt.get('repository') != REPOSITORY
            or trusted_receipt.get('last_good_sha') != contract['last_good_sha']
            or trusted_receipt.get('authenticated_complete_readback') is not True
            or trusted_receipt.get('last_good_github_read') is not True
            or trusted_receipt.get('isolated_restore') != 'PASS'
            or contract.get('checkpoint_receipt_sha256') != digest(trusted_receipt)):
        raise ValueError('Fresh independent GitHub/R2/isolated-restore receipt must bind last-known-good')
    approval = contract.get('approval', {})
    start, end = stamp(approval.get('starts_at')), stamp(approval.get('expires_at'))
    if (approval.get('approved') is not True or approval.get('contract_sha256') != expected_digest
            or approval.get('rollback_playbook') != 'EXACT_CODE_CONFIG_ONCE_V1'
            or type(approval.get('maximum_rollbacks')) is not int or approval['maximum_rollbacks'] != 1 or start is None or end is None
            or not start <= now < end or not timedelta(0) < end - start <= timedelta(hours=1)
            or approval.get('authority') != ('OWNER_EXACT_PRODUCTION_CHANGE' if contract['environment'] == 'production' else 'OWNER_ISOLATED_EXPERIMENT')):
        raise ValueError('Fresh exact independent approval and one-rollback playbook required')
    targets = contract.get('targets')
    if not isinstance(targets, list) or not 1 <= len(targets) <= 32:
        raise ValueError('Bounded exact target inventory required')
    paths = []
    for target in targets:
        paths.append(checked_path(target['path']))
        if type(target.get('mode')) is not int or target['mode'] not in {0o600, 0o640, 0o644, 0o750, 0o755}:
            raise ValueError('Exact safe code/config permissions required')
        for key in ('before_sha256', 'candidate_sha256'):
            if not re.fullmatch('[0-9a-f]{64}', str(target.get(key, ''))):
                raise ValueError('Exact per-file preimage/candidate hash required')
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate rollback targets refused')
    checkpoint = digest([{k: t[k] for k in ('path', 'mode', 'before_sha256')} for t in targets])
    if contract.get('configuration_checkpoint_sha256') != checkpoint:
        raise ValueError('Exact relevant code/config prechange checkpoint required')
    if contract.get('database_restore_allowed') is not False or contract.get('security_changes_allowed') is not False:
        raise ValueError('Routine rollback must preserve databases and security policy')
    compatibility = contract.get('compatibility_evidence', {})
    if (compatibility.get('passed') is not True or compatibility.get('kind') != 'last_good_reads_current_schema'
            or compatibility.get('last_good_sha') != contract['last_good_sha']
            or compatibility.get('candidate_sha') != contract['candidate_sha']
            or not re.fullmatch('[0-9a-f]{64}', str(compatibility.get('evidence_sha256', '')))):
        raise ValueError('Independent old-code/new-data compatibility proof required')
    return contract


class RecoverySupervisor:
    """Runs outside candidate code; independently validates and restores exact files."""
    def __init__(self, scope, contract, trusted_receipt, *, expected_digest, git_file, probe, data_probe, now):
        if not isinstance(scope, DevelopmentScope):
            raise ValueError('Explicit isolated supervisor scope required')
        scope.verify(now)
        validate_contract(contract, trusted_receipt, expected_digest=expected_digest, now=now)
        if contract['environment'] != 'isolated-development':
            raise ValueError('Production supervisor execution is not installed or authorized')
        self.scope, self.contract, self.receipt = scope, contract, trusted_receipt
        if not callable(data_probe):
            raise ValueError('Independent current-data integrity verifier required')
        self.expected_digest, self.git_file, self.probe, self.data_probe = expected_digest, git_file, probe, data_probe
        self.last_health = None
        self.audit = ActionEvidence(scope.path('state.sqlite'))
        self.action_id = 'release:' + expected_digest[:40]
        with self.audit.connect() as db:self.audit.setup(db)

    def _check(self, now):
        self.scope.verify(now)
        validate_contract(self.contract, self.receipt, expected_digest=self.expected_digest, now=now)

    def _files(self):
        total = 0;result = []
        for target in self.contract['targets']:
            name = target['path'];before = self.git_file(self.contract['last_good_sha'], name)
            candidate = self.git_file(self.contract['candidate_sha'], name)
            total += len(before) + len(candidate)
            if (len(before) > 8192 or len(candidate) > 8192 or total > 512 * 1024
                    or hashlib.sha256(before).hexdigest() != target['before_sha256'] or hashlib.sha256(candidate).hexdigest() != target['candidate_sha256']):
                raise ValueError('Verified Git blobs changed or exceed bounds')
            path = self.scope.path('release/' + name)
            if not path.is_file() or path.stat().st_size > 1024**2:
                raise ValueError('Rollback target absent or exceeds bound')
            result.append((target, path, before, candidate))
        return result

    def _write(self, name, data):
        # Reuse atomic bounded writer. Split contract bound is stricter than a whole archive.
        if len(data) > 8192:
            raise ValueError('Fixture code/config exceeds exact repair bound')
        self.scope.write('release/' + name, data)
        mode = next(t['mode'] for t in self.contract['targets'] if t['path'] == name)
        os.chmod(self.scope.path('release/' + name), mode)

    def _incident(self, reason, now):
        key = 'incident:' + self.expected_digest[:40]
        with self.audit.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            local_record(db, key, 'DEPLOYMENT_RECOVERY_INCIDENT', {'type': 'INCIDENT', 'identity': key}, now,
                before={'recorded': False}, after={'release': self.action_id, 'reason_code': reason,
                    'blocks_autonomy': True, 'escalation_route': 'existing-owner-operations',
                    'delivery_state': 'PENDING_EXISTING_DISPATCH'},
                reason='Independent candidate/rollback verification failed; no retry or database restore')
        self.audit.event(key, 'RECOVERY', 'AUTONOMY_HOLD', {'reason_code': reason}, now)

    def _health(self, expected):
        field = 'before_sha256' if expected == self.contract['last_good_sha'] else 'candidate_sha256'
        if any(file_sha(path) != target[field] for target, path, _, _ in self._files()):
            self.last_health = {'healthy': False, 'source_sha': expected, 'reason': 'CODE_IDENTITY_MISMATCH'}
            return False
        try:
            result = self.probe();data = self.data_probe()
        except Exception as exc:
            self.last_health = {'healthy': False, 'error_type': type(exc).__name__}
            return False
        # Probe callbacks execute independently of candidate code. Recheck files
        # after them, and require data evidence independently of HTTP liveness.
        good = (isinstance(result, dict) and result.get('healthy') is True
            and result.get('source_sha') == expected and isinstance(data, dict)
            and data.get('healthy') is True and data.get('database_restore_performed') is False
            and isinstance(data.get('evidence_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', data['evidence_sha256']) is not None
            and all(file_sha(path) == target[field] for target, path, _, _ in self._files()))
        self.last_health = {'healthy': bool(good), 'source_sha': expected,
                            'data_evidence_sha256': data.get('evidence_sha256') if isinstance(data, dict) else None}
        return bool(good)

    def deploy(self, *, now):
        self._check(now)
        with self.scope.lock():
            if self.audit.get(self.action_id):
                return self._reconcile(now)
            holds = recovery_holds(self.audit)
            if holds:
                return {'state': 'RECOVERY_HOLD', 'incidents': holds, 'database_restored': False}
            files = self._files()
            if any(file_sha(path) != target['before_sha256'] for target, path, _, _ in files):
                raise ValueError('Current release differs from approved prechange state')
            if not self._health(self.contract['last_good_sha']):
                self._incident('LAST_KNOWN_GOOD_UNHEALTHY', now)
                return {'state': 'REJECTED', 'reason': 'LAST_KNOWN_GOOD_UNHEALTHY', 'database_restored': False}
            plan = envelope(self.action_id, 'ISOLATED_RELEASE_CHANGE', {'type': 'CODE', 'identity': self.expected_digest}, now,
                mutation=True, authority_class='OWNER_ISOLATED_EXPERIMENT', automatic_rule='Preapproved exact one-rollback experiment',
                before_state={'sha': self.contract['last_good_sha'], 'health': self.last_health}, proposed_state={'sha': self.contract['candidate_sha']},
                rollback_capability='FULLY_REVERSIBLE', rollback_target=self.contract['last_good_sha'],
                rollback_procedure='Restore only approved Git code/config blobs and independently verify health; never databases',
                exact_versions={'environment': 'isolated-development', 'contract_sha256': self.expected_digest},
                evidence_refs=[{'reference': 'r2:' + self.receipt['r2_object_key'], 'source_at': self.receipt['verified_at']}])
            self.audit.plan(plan, now);self.audit.start(self.action_id, now, authority_check=lambda: self._check(now))
            try:
                for target, path, _, candidate in files:
                    if file_sha(path) != target['before_sha256']:
                        raise ValueError('Concurrent release edit refused')
                    self._write(target['path'], candidate)
                if self._health(self.contract['candidate_sha']):
                    self.audit.finish(self.action_id, now, provider_success=True, verified=True,
                                      actual_after={'sha': self.contract['candidate_sha']})
                    return {'state': 'CANDIDATE_VERIFIED', 'database_restored': False}
            except Exception as exc:
                self.audit.event(self.action_id, 'RECOVERY', 'CANDIDATE_FAILED', {'error_type': type(exc).__name__}, now)
            self.audit.event(self.action_id, 'RECOVERY', 'FAILURE_ATTRIBUTION',
                {'classification': 'CANDIDATE_WINDOW_FAILURE', 'root_cause': 'UNPROVEN',
                 'health': self.last_health}, now)
            return self._rollback(now)

    def _reconcile(self, now):
        state = self.audit.get(self.action_id)
        if state['status'] != 'STARTED':
            return {'state': 'ALREADY_FINAL', 'status': state['status'], 'database_restored': False}
        return self._rollback(now)

    def recover_interrupted(self, *, now):
        self._check(now)
        with self.scope.lock():
            if not self.audit.get(self.action_id):
                raise ValueError('No started release to reconcile')
            return self._reconcile(now)

    def check_deployment(self, *, now):
        """Independent later health observation during the exact approved window."""
        self._check(now)
        with self.scope.lock():
            state = self.audit.get(self.action_id)
            if not state:
                raise ValueError('No observed deployment')
            rollback = self.audit.get(self.action_id + ':rollback')
            if rollback:
                if rollback['status'] == 'STARTED':return self._rollback(now)
                return {'state': 'ALREADY_FINAL', 'status': rollback['status'], 'database_restored': False}
            if state['status'] == 'STARTED':return self._rollback(now)
            if state['status'] != 'SUCCEEDED':return self._reconcile(now)
            if self._health(self.contract['candidate_sha']):
                return {'state': 'HEALTHY', 'database_restored': False}
            self.audit.event(self.action_id, 'RECOVERY', 'POSTDEPLOY_FAILURE_DETECTED',
                             {'expected_sha': self.contract['candidate_sha']}, now)
            return self._rollback(now)

    def _rollback(self, now):
        parent = self.audit.get(self.action_id)
        aid = self.action_id
        if parent['status'] == 'SUCCEEDED':
            aid += ':rollback'
            prior = self.audit.get(aid)
            if prior and prior['status'] != 'STARTED':
                return {'state': 'ALREADY_FINAL', 'database_restored': False}
            if not prior:
                plan = envelope(aid, 'ISOLATED_PREAPPROVED_ROLLBACK', {'type': 'CODE', 'identity': self.expected_digest}, now,
                    mutation=True, authority_class='OWNER_ISOLATED_EXPERIMENT', automatic_rule='Exact preapproved one-rollback playbook',
                    before_state={'sha': self.contract['candidate_sha']}, proposed_state={'sha': self.contract['last_good_sha']},
                    rollback_capability='FULLY_REVERSIBLE', rollback_target=self.contract['last_good_sha'],
                    rollback_procedure='Exact approved Git preimages only; preserve business databases',
                    exact_versions={'environment': 'isolated-development', 'parent_action_id': self.action_id})
                self.audit.plan(plan, now);self.audit.start(aid, now, authority_check=lambda: self._check(now))
        try:files = self._files()
        except Exception:
            self._incident('ROLLBACK_INPUT_UNAVAILABLE', now)
            self.audit.finish(aid, now, provider_success=False, actual_after={'rollback': 'BLOCKED_INPUT_UNAVAILABLE'})
            return {'state': 'ROLLBACK_BLOCKED', 'database_restored': False}
        if any(file_sha(path) not in {target['before_sha256'], target['candidate_sha256']} for target, path, _, _ in files):
            self._incident('NEWER_OR_UNKNOWN_EDIT_PRESERVED', now)
            self.audit.finish(aid, now, provider_success=False, actual_after={'rollback': 'BLOCKED_UNKNOWN_EDIT'})
            return {'state': 'ROLLBACK_BLOCKED', 'database_restored': False}
        with self.audit.connect(readonly=True) as db:
            started = db.execute("SELECT 1 FROM action_evidence WHERE action_id=? AND json_extract(evidence_json,'$.event')='ROLLBACK_INTENT' LIMIT 1", (aid,)).fetchone()
        if not started:
            self.audit.event(aid, 'RECOVERY', 'ROLLBACK_INTENT', {'contract': self.expected_digest, 'maximum_rollbacks': 1}, now)
        try:
            for target, path, before, _ in files:
                if file_sha(path) != target['before_sha256']:
                    self._write(target['path'], before)
            verified = (all(file_sha(path) == target['before_sha256'] for target, path, _, _ in files)
                        and self._health(self.contract['last_good_sha']))
        except Exception as exc:
            verified = False
            self.audit.event(aid, 'RECOVERY', 'ROLLBACK_ERROR', {'error_type': type(exc).__name__}, now)
        self.audit.finish(aid, now, provider_success=verified and aid != self.action_id, verified=verified,
                          actual_after={'rollback_verified': verified, 'sha': self.contract['last_good_sha'] if verified else None})
        self.audit.event(aid, 'RECOVERY', 'ROLLBACK_VERIFIED' if verified else 'ROLLBACK_FAILED',
                         {'database_restored': False, 'sha': self.contract['last_good_sha'],
                          'data_integrity_evidence': self.last_health,
                          'attribution': 'CHANGE_ASSOCIATED_RECOVERY' if verified else 'UNPROVEN'}, now)
        if not verified:self._incident('ROLLBACK_HEALTH_FAILED', now)
        return {'state': 'ROLLED_BACK' if verified else 'ROLLBACK_FAILED', 'database_restored': False}
