"""Bounded non-production repair through existing Action Evidence and Manager receipts.

Development only: no service entry point, provider client, token cache or timer.
Neither observations nor learning records grant production authority.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .acquisition_store import digest, safe
from .action_evidence import ActionEvidence, envelope, local_record, stamp
from .manager_store import ManagerStore

RULE = 'NONPROD_RECOVERY_V1'
DENIED_ROOTS = ('/opt', '/etc', '/var/lib', '/var/backups', '/recovery', '/root')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class DevelopmentScope:
    """An explicit, expiring fixture grant; cannot select a production path."""
    def __init__(self, root):
        given = Path(root).absolute()
        self.root = given.resolve()
        if os.geteuid() == 0 or given != self.root or self.root == Path('/') or any(
                self.root == Path(p) or Path(p) in self.root.parents for p in DENIED_ROOTS):
            raise ValueError('Isolated unprivileged development workspace required')
        self.marker = self.root / '.optibrain-development.json'

    def verify(self, now):
        directory = self.root.lstat()
        if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
                or directory.st_mode & 0o022 or self.root.is_symlink()):
            raise ValueError('Private development workspace required')
        fd = os.open(self.marker, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > 4096:
                raise ValueError('Untrusted development grant')
            policy = json.load(stream)
        if (policy.get('environment') != 'isolated-development' or policy.get('production_allowed') is not False
                or policy.get('rule') != RULE or policy.get('root') != str(self.root)
                or stamp(policy.get('issued_at')) is None or stamp(policy.get('expires_at')) is None
                or not stamp(policy['issued_at']) <= now < stamp(policy['expires_at'])
                or stamp(policy['expires_at']) - stamp(policy['issued_at']) > timedelta(days=1)):
            raise ValueError('Exact current non-production authority required')
        return policy

    def path(self, relative):
        p = Path(relative)
        if p.is_absolute() or not p.parts or any(x in {'..', '.'} for x in p.parts):
            raise ValueError('Bounded workspace-relative path required')
        target = self.root
        for part in p.parts:
            target = target / part
            if target.is_symlink():
                raise ValueError('Symlink refused')
        if self.root not in target.resolve().parents:
            raise ValueError('Workspace escape refused')
        return target

    @contextmanager
    def lock(self):
        directory = self.path('locks');directory.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(self.path('locks/recovery-coordinator.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise ValueError('Untrusted execution lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def write(self, relative, data):
        if len(data) > 8192:
            raise ValueError('Artifact exceeds repair bound')
        p = self.path(relative);p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.repair-', dir=p.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.chmod(name, 0o600);os.replace(name, p)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def diagnose(observation, now):
    """Deterministic classification; recurrence is not independent cause proof."""
    required = {'operation_id', 'service', 'symptom', 'observed_at', 'evidence_ref', 'evidence_sha256'}
    if not isinstance(observation, dict) or not required <= set(observation):
        raise ValueError('Source-linked observation required')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', observation['operation_id']) or not re.fullmatch(
            r'[A-Za-z0-9_.:-]{1,80}', observation['service']):
        raise ValueError('Exact stable operation/service identity required')
    observed = stamp(observation['observed_at'])
    if observed is None or not timedelta(0) <= now - observed <= timedelta(days=1):
        raise ValueError('Observation is stale, future or malformed')
    if not re.fullmatch('[0-9a-f]{64}', observation['evidence_sha256']) or not isinstance(
            observation['evidence_ref'], str) or not 1 <= len(observation['evidence_ref']) <= 256:
        raise ValueError('Bounded original evidence reference/hash required')
    safe(observation)
    symptom = observation['symptom']
    rules = {
        'DERIVED_REPORT_MISSING': ('DERIVED_ARTIFACT_UNAVAILABLE', 'rebuild-derived-status'),
        'ORPHANED_DEV_LOCK': ('LOCK_OWNERSHIP_REQUIRES_PROOF', 'release-orphaned-dev-lock'),
        'AUTH_REJECTED': ('EXISTING_REFRESH_OR_OWNER_CONSENT', None),
        'SCOPE_MISSING': ('OWNER_PROVIDER_CONSENT_REQUIRED', None),
        'TRANSIENT_READ': ('EXISTING_BOUNDED_READ_RETRY', None),
        'RATE_LIMITED': ('RESPECT_PROVIDER_BACKOFF', None),
        'HISTORICAL_FAILURE': ('RETAINED_RECONCILIATION_REQUIRED', None),
        'SOFTWARE_DEFECT': ('ISOLATED_REPRODUCTION_REQUIRED', None),
        'PRODUCTION_SERVICE_UNHEALTHY': ('EXISTING_BOUNDED_SERVICE_REPAIR_ONLY', None),
        'CAPACITY_RISK': ('RESOURCE_GUARD_OR_OWNER_CAPACITY_DECISION', None),
    }
    cause, playbook = rules.get(symptom, ('UNKNOWN_REQUIRE_EVIDENCE', None))
    return dict(rule_version=RULE, cause_class=cause, cause_confidence='CLASSIFICATION_ONLY',
                playbook=playbook, production_authority=False,
                incident_key=digest([observation['service'], symptom, observation['operation_id']])[:32])


def observations_from_operations(status, *, evidence_ref, now):
    """Consume the existing observer's result; no second collector or alert route."""
    at = status.get('at')
    if type(at) not in (int, float) or not 0 <= now.timestamp() - at <= 900:
        raise ValueError('Fresh existing operations observation required')
    source_hash = digest(status);observed_at = datetime.fromtimestamp(at, timezone.utc).isoformat()
    observations = []
    for alert in status.get('alerts', [])[:100]:
        incident = alert.get('incident', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', incident):
            continue
        symptom = ('PRODUCTION_SERVICE_UNHEALTHY' if incident.startswith('service:') else
                   'AUTH_REJECTED' if incident == 'credential-health' else
                   'HISTORICAL_FAILURE' if incident == 'dlq-review' else
                   'CAPACITY_RISK' if incident in {'working-headroom', 'disk-reserve', 'disk-critical'} else
                   'UNKNOWN')
        observations.append(dict(operation_id='ops:' + digest(incident)[:32], service='existing-operations',
            symptom=symptom, observed_at=observed_at, evidence_ref=evidence_ref,
            evidence_sha256=source_hash, original_incident=incident,
            recurrence_count=sum(r.get('unit') == alert.get('service') for r in status.get('repairs', []))))
    return observations


class DerivedStatus:
    name = 'rebuild-derived-status'
    def __init__(self, scope, params, identity):
        if set(params) != {'expected'}:
            raise ValueError('Only the fixed derived status artifact is repairable')
        safe(params);self.scope = scope
        self.data = (json.dumps(params['expected'], sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
        if len(self.data) > 8192:
            raise ValueError('Derived artifact exceeds bound')
        self.path = scope.path('derived/status.json')
        self.preimage = 'evidence/' + identity + '.before'

    def describe(self):
        if self.path.exists():
            if not self.path.is_file() or self.path.stat().st_size > 8192:
                raise ValueError('Unexpected derived artifact')
            return {'exists': True, 'sha256': sha(self.path.read_bytes())}
        return {'exists': False, 'sha256': None}

    def execute(self, before):
        if self.describe() != before:
            raise ValueError('Derived state changed before repair')
        if before['exists']:
            self.scope.write(self.preimage, self.path.read_bytes())
        self.scope.write('derived/status.json', self.data)

    def verify(self):
        return self.path.is_file() and self.path.read_bytes() == self.data

    def after(self):
        return {'artifact': 'derived/status.json', 'sha256': sha(self.path.read_bytes()) if self.path.is_file() else None}


class OrphanedLock:
    name = 'release-orphaned-dev-lock'
    def __init__(self, scope, params, identity):
        if params:
            raise ValueError('Only the exact development read-job lock is repairable')
        self.scope, self.path = scope, scope.path('locks/read-job.lock')
        self.retired = scope.path('evidence/' + identity + '.orphaned-lock')

    def describe(self):
        if not self.path.exists():
            return {'exists': False, 'sha256': None}
        if not self.path.is_file() or self.path.stat().st_size > 4096:
            raise ValueError('Unexpected lock file')
        return {'exists': True, 'sha256': sha(self.path.read_bytes())}

    def execute(self, before):
        fd = os.open(self.path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = os.fstat(fd)
            if info.st_nlink != 1 or info.st_ino != self.path.stat().st_ino or self.describe() != before:
                raise ValueError('Lock identity changed')
            value = json.loads(os.read(fd, 4097));pid = value.get('owner_pid')
            if type(pid) is not int or pid <= 0:
                raise ValueError('Exact lock owner identity required')
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError('Lock owner remains alive')
            self.retired.parent.mkdir(mode=0o700, exist_ok=True)
            if self.retired.exists():
                raise ValueError('Existing retirement evidence requires reconciliation')
            os.rename(self.path, self.retired)
        finally:
            os.close(fd)

    def verify(self):
        return not self.path.exists() and self.retired.is_file()

    def after(self):
        return {'active_lock_absent': not self.path.exists(),
                'retained_evidence_sha256': sha(self.retired.read_bytes()) if self.retired.is_file() else None}


PLAYBOOKS = {DerivedStatus.name: DerivedStatus, OrphanedLock.name: OrphanedLock}


class RecoveryCoordinator:
    """Single existing journal; two attempts/hour, >=60s cooldown, three/6h total."""
    def __init__(self, scope, *, now=None):
        scope.verify(now or datetime.now(timezone.utc))
        self.scope = scope;self.audit = ActionEvidence(scope.path('state.sqlite'))
        with self.audit.connect() as db:
            self.audit.setup(db)

    def _record(self, identity, kind, value, now):
        with self.audit.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            local_record(db, identity, kind, {'type': 'OPERATIONAL_EVIDENCE', 'identity': identity}, now,
                before={'recorded': False}, after=value, reason=kind,
                exact_versions={'environment': 'isolated-development', 'rule_version': RULE})
        return identity

    def _incident(self, key, reason, observation_id, now):
        return self._record('incident:' + key, 'OPERATIONAL_INCIDENT_CREATED',
            {'incident_key': key, 'reason_code': reason, 'observation': observation_id,
             'owner_action': 'review evidence; no production authority granted'}, now)

    def _plans(self):
        with self.audit.connect(readonly=True) as db:
            rows = db.execute("SELECT action_id FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='NONPROD_REPAIR' ORDER BY created_at DESC LIMIT 1001").fetchall()
            return [self.audit.current(db, row['action_id']) for row in rows]

    def repair(self, observation, params, *, now=None):
        now = now or datetime.now(timezone.utc)
        self.scope.verify(now)
        with self.scope.lock():
            diagnosis = diagnose(observation, now);key = diagnosis['incident_key']
            oid = self._record('observation:' + digest(observation)[:40], 'OPERATIONAL_DIAGNOSIS',
                               {'observation': observation, 'diagnosis': diagnosis}, now)
            if diagnosis['playbook'] is None:
                self._incident(key, diagnosis['cause_class'], oid, now)
                return {'state': 'DIAGNOSIS_ONLY', 'diagnosis': diagnosis, 'executed': False}
            binding = digest([diagnosis['playbook'], params])
            plans = self._plans();prior = [p for p in plans if p['exact_versions']['incident_key'] == key]
            if len(plans) >= 1001:
                return {'state': 'CIRCUIT_OPEN', 'executed': False}
            if any(p['exact_versions']['parameter_hash'] != binding for p in prior):
                self._incident(key, 'OPERATION_BINDING_CHANGED', oid, now)
                return {'state': 'BINDING_CONFLICT', 'executed': False}
            latest = prior[0] if prior else None
            if latest and isinstance(latest.get('final_result'), dict) and latest['final_result'].get('error_class') == 'AmbiguousLocalRepair':
                return {'state': 'AMBIGUOUS_NO_RETRY', 'executed': False}
            identity = latest['action_id'] if latest and latest['status'] == 'STARTED' else 'repair:' + key + ':' + str(len(prior) + 1)
            playbook = PLAYBOOKS[diagnosis['playbook']](self.scope, params, identity)
            if latest and latest['status'] == 'STARTED':
                verified = playbook.verify()
                failure = None if verified else {'stage': 'READ_AFTER_WRITE', 'error_class': 'AmbiguousLocalRepair',
                    'provider_status': None, 'safe_details': 'Interrupted local repair could not be verified',
                    'partial_effects': 'UNKNOWN', 'recovery_action': 'Owner review; no repeated effect'}
                self.audit.finish(identity, now, provider_success=verified, verified=verified,
                                  actual_after=playbook.after(), failure=failure)
                self.audit.event(identity, 'RECOVERY', 'OPERATIONAL_LEARNING',
                    {'environment': 'isolated-development', 'symptom': observation['symptom'],
                     'cause_class': diagnosis['cause_class'], 'action_id': identity,
                     'tests': ['independent interrupted-repair readback'], 'verified': verified,
                     'reuse_eligible': False, 'business_impact': 'NOT_MEASURED'}, now)
                if not verified:
                    self._incident(key, 'AMBIGUOUS_REPAIR_GET_ONLY', oid, now)
                return {'state': 'RECONCILED' if verified else 'AMBIGUOUS_NO_RETRY', 'executed': False}
            if diagnosis['playbook'] == DerivedStatus.name and playbook.verify():
                return {'state': 'ALREADY_HEALTHY', 'executed': False}
            if diagnosis['playbook'] == OrphanedLock.name and not playbook.path.exists():
                return {'state': 'ALREADY_HEALTHY', 'executed': False}
            recent = [p for p in prior if now - stamp(p['created_at']) < timedelta(hours=1)]
            global_recent = [p for p in plans if now - stamp(p['created_at']) < timedelta(hours=6)]
            if len(recent) >= 2 or len(global_recent) >= 3:
                self._incident(key, 'REPAIR_CIRCUIT_OPEN', oid, now)
                return {'state': 'CIRCUIT_OPEN', 'executed': False}
            if latest and now - stamp(latest['created_at']) < timedelta(seconds=60):
                return {'state': 'COOLDOWN', 'executed': False}
            before = playbook.describe()
            plan = envelope(identity, 'NONPROD_REPAIR', {'type': 'LOCAL_DERIVED_ARTIFACT', 'identity': diagnosis['playbook']}, now,
                mutation=True, authority_class=RULE, automatic_rule='Exact expiring development scope; two/hour, three/six hours',
                before_state=before, proposed_state={'playbook': diagnosis['playbook'], 'parameter_hash': binding},
                rollback_capability='REVERSIBLE_WITH_LIMITATIONS', rollback_target='isolated workspace evidence only',
                rollback_procedure='Restore only exact retained derived preimage after hash comparison; never a business database',
                evidence_refs=[{'reference': observation['evidence_ref'], 'source_at': observation['observed_at']}],
                exact_versions={'environment': 'isolated-development', 'rule_version': RULE,
                                'incident_key': key, 'parameter_hash': binding})
            self.audit.plan(plan, now);self.audit.start(identity, now, authority_check=lambda: self.scope.verify(now))
            error = None
            try:
                playbook.execute(before)
                verified = playbook.verify()
            except Exception as exc:
                error = type(exc).__name__;verified = False
            after = playbook.after()
            self.audit.finish(identity, now, provider_success=verified, actual_after=after, verified=verified)
            learning = {'environment': 'isolated-development', 'symptom': observation['symptom'],
                'cause_class': diagnosis['cause_class'], 'cause_confidence': 'CLASSIFICATION_ONLY',
                'action_id': identity, 'observation_id': oid, 'rule_version': RULE, 'before': before,
                'after': after, 'verified': verified, 'error_type': error,
                'tests': ['independent exact playbook readback'], 'reuse_eligible': False,
                'business_impact': 'NOT_MEASURED', 'safeguard_changes': False}
            self.audit.event(identity, 'RECOVERY', 'OPERATIONAL_LEARNING', learning, now)
            ManagerStore(self.audit.path).receipt('operational-recovery', identity, now,
                {'classification': 'TEST_ONLY', 'action_id': identity, 'outcome_verified': verified,
                 'invocation_origin': 'ISOLATED_RECOVERY', 'source_at': observation['observed_at'],
                 'business_effects': 0, 'learning_scope': 'OPERATIONAL_ONLY'})
            if not verified:
                self._incident(key, 'RECOVERY_FAILED', oid, now)
            elif self.audit.get('incident:' + key):
                self.audit.event('incident:' + key, 'RECOVERY', 'RESOLVED', {'action_id': identity}, now)
            return {'state': 'REPAIRED' if verified else 'FAILED', 'executed': True,
                    'action_id': identity, 'verified': verified}
