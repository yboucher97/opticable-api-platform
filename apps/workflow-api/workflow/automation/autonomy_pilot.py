"""Development-only admission and continuation over the existing run ledger."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
from time import monotonic

from .models import AutomationEvent, WorkflowDefinition
from .store import AutomationStore

EVENT = 'optibrain.development.autonomy'
LEASE_SECONDS = 120
DISK_FLOOR = 45 * 1024**3
MAX_STAGING_BYTES = 512 * 1024**2
MEMORY_RESERVE = 6 * 1024**2  # KiB


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def instant(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def current(value, now, minutes):
    at = instant(value)
    return at is not None and timedelta(0) <= now - at <= timedelta(minutes=minutes)


def retry_after(header, attempt, now, *, jitter=0):
    """Keep a provider-supplied date even when it exceeds the local backoff cap."""
    if attempt not in (1, 2, 3) or not 0 <= jitter <= 5 or now.tzinfo is None:
        raise ValueError('Bounded retry policy required')
    delay = min(60 * 2 ** (attempt - 1), 240)
    fallback = now + timedelta(seconds=delay + jitter)
    if header is None:
        return fallback
    if re.fullmatch(r'[0-9]{1,9}', header):
        return max(fallback, now + timedelta(seconds=int(header) + jitter))
    try:
        until = parsedate_to_datetime(header)
        if until.tzinfo is not None:
            return max(fallback, until + timedelta(seconds=jitter))
    except (TypeError, ValueError, OverflowError):
        pass
    return fallback


def allowance(snapshot, now, *, windows, prior_reset=None, reserve=30):
    """Evaluate independently observed Codex windows. No reset or credit calls."""
    if not windows or not 0 < reserve < 100 or snapshot.get('status') != 'OBSERVED':
        return 'UNKNOWN', None
    at = instant(snapshot.get('observed_at'))
    if prior_reset and now < prior_reset:
        return 'RETRY_WAIT', prior_reset
    if not current(snapshot.get('observed_at'), now, 5) or prior_reset and at < prior_reset:
        return 'BLOCKED', None
    bucket = snapshot.get('rate_limits') or {}
    slots = {v.get('windowDurationMins'): v for v in (bucket.get('primary'), bucket.get('secondary'))
             if isinstance(v, dict)}
    if not set(windows) <= slots.keys():
        return 'UNKNOWN', None
    resets = []
    for length in windows:
        slot = slots[length]
        used, reset = slot.get('usedPercent'), slot.get('resetsAt')
        if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100 or type(reset) is not int:
            return 'UNKNOWN', None
        try:
            reset_at = datetime.fromtimestamp(reset, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return 'UNKNOWN', None
        if reset_at <= now:
            return 'BLOCKED', None
        if used >= 100 - reserve or bucket.get('rateLimitReachedType'):
            resets.append(reset_at)
    return ('RETRY_WAIT', max(resets)) if resets else ('ELIGIBLE', None)


def admission(sample, now, *, paused=False):
    if paused or sample.get('operator_paused') is True:
        return 'PAUSED', 'operator_pause'
    if not current(sample.get('observed_at'), now, 15):
        return 'BLOCKED', 'stale_admission_sample'
    if sample.get('host') != 'vps-f8e9b20e' or (sample.get('flags_off'), sample.get('flag_total')) != (45, 45):
        return 'BLOCKED', 'flag_or_host_drift'
    if (sample.get('protected_match'), sample.get('protected_total')) != (76, 76):
        return 'BLOCKED', 'protected_configuration_drift'
    if sample.get('golden_local_restore') != 'PASS' or not current(sample.get('backup_at'), now, 36 * 60):
        return 'BLOCKED', 'recovery_evidence_missing'
    if (sample.get('maintenance') or {}).keys() != {'optibrain-backup', 'optibrain-phase2a-upload', 'optibrain-resource-verify'}:
        return 'BLOCKED', 'maintenance_state_unknown'
    if any(state != 'inactive' for state in sample['maintenance'].values()):
        return 'RETRY_WAIT', 'critical_maintenance'
    maintenance_results = sample.get('maintenance_results', {})
    if maintenance_results.keys() != sample['maintenance'].keys() or any(
            result != 'success' for result in maintenance_results.values()):
        return 'BLOCKED', 'backup_or_verification_result_unproven'
    health = sample.get('health_latency') or {}
    if set(health) != {'api', 'pdf', 'omada'} or any(
        v.get('http') != 200 or not 0 < v.get('max_ms', 0) <= 100 for v in health.values()
    ) or sample.get('core', {}).get('caddy.service', {}).get('ActiveState') != 'active':
        return 'BLOCKED', 'core_service_health'
    if sample.get('optional_generation_paused') is not False and sample.get('scope') != 'deterministic_read_only_validation':
        return 'BLOCKED', 'existing_optional_work_pause'
    pressure = sample.get('psi_some_avg10_pct') or {}
    disk = sample.get('filesystem_bytes', {}).get('free', 0)
    ram = sample.get('memory_kib', {}).get('MemAvailable', 0)
    if disk - MAX_STAGING_BYTES < DISK_FLOOR or ram < MEMORY_RESERVE:
        return 'RETRY_WAIT', 'disk_or_memory_reserve'
    if any(not 0 <= pressure.get(k, -1) <= n for k, n in {'cpu': 10, 'memory': 1, 'io': 2}.items()):
        return 'RETRY_WAIT', 'resource_pressure'
    if len(sample.get('load') or []) < 1 or not 0 <= sample['load'][0] <= 2:
        return 'RETRY_WAIT', 'load_pressure'
    return 'ELIGIBLE', None


def cgroup_proof():
    group = Path('/proc/self/cgroup').read_text().split('::', 1)[1].strip()
    root = Path('/sys/fs/cgroup') / group.lstrip('/')
    quota, period = (root / 'cpu.max').read_text().split()
    memory = (root / 'memory.max').read_text().strip()
    tasks = (root / 'pids.max').read_text().strip()
    weight = (root / 'cpu.weight').read_text().strip()
    io = (root / 'io.weight').read_text().splitlines()[0].split()[-1]
    caps = [dict(item.split('=', 1) for item in line.split()[1:])
            for line in (root / 'io.max').read_text().splitlines()]
    io_capped = any(v.get('rbps', '').isdigit() and 0 < int(v['rbps']) <= 30_000_000
                    and v.get('wbps', '').isdigit() and 0 < int(v['wbps']) <= 15_000_000 for v in caps)
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if not (quota.isdigit() and 0 < int(quota) <= int(period) and memory.isdigit()
            and 0 < int(memory) <= 2 * 1024**3 and tasks.isdigit() and 0 < int(tasks) <= 32
            and int(weight) <= 20 and int(io) <= 20 and io_capped and status['NoNewPrivs'].strip() == '1'):
        raise ValueError('Independently enforced process envelope required')
    return {'cpu_quota': int(quota), 'cpu_period': int(period), 'memory_max_bytes': int(memory),
            'tasks_max': int(tasks), 'cpu_weight': int(weight), 'io_weight': int(io),
            'io_max': caps, 'no_new_privileges': True}


@dataclass(frozen=True)
class Task:
    name: str
    priority: int
    parents: tuple[str, ...] = ()
    lane: str = 'deterministic'


WORKFLOW = WorkflowDefinition(
    id='quality-first-autonomy-pilot', name='Development-only proof', version=1,
    trigger={'event_types': [EVENT], 'sources': ['optibrain-development']},
    steps=[{'id': 'verify-and-checkpoint', 'action': 'pilot.deterministic'}],
)


class Pilot:
    """Single-process dispatcher. The existing store owns leases and checkpoints."""

    def __init__(self, scope, tasks, *, goal, source, input_hash):
        self.scope = scope
        self.tasks = sorted(tasks, key=lambda task: (-task.priority, task.name))
        names = {t.name for t in self.tasks}
        if not names or len(names) != len(self.tasks) or len(names) > 8:
            raise ValueError('Bounded unique task catalogue required')
        resolved = set()
        for task in self.tasks:
            if task.lane not in {'deterministic', 'model', 'protected'} or not set(task.parents) <= resolved:
                raise ValueError('Dependencies must precede a task in priority order')
            resolved.add(task.name)
        if not re.fullmatch(r'[0-9a-f]{40}', source) or not re.fullmatch(r'[0-9a-f]{64}', input_hash):
            raise ValueError('Exact source and input identity required')
        self.plan = {'goal': goal, 'source': source, 'input_sha256': input_hash,
                     'tasks': [asdict(t) for t in self.tasks]}
        self.plan_hash = digest(self.plan)

    def event_id(self, task):
        return digest([self.plan_hash, task.name])

    def _open(self, now):
        path = self.scope.path('automation.db')
        for p in (path, self.scope.path('automation.db-wal'), self.scope.path('automation.db-shm')):
            if p.exists():
                info = p.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                    raise ValueError('Private single-link pilot ledger required')
        if not path.exists():
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        store = AutomationStore(path)
        ids = {self.event_id(task) for task in self.tasks}
        rows = store.recent_runs()
        if any(row['event_id'] not in ids or row['workflow_id'] != WORKFLOW.id for row in rows):
            raise ValueError('Pilot scope is already bound to another plan')
        store.upsert_workflow(WORKFLOW)
        existing = {row['event_id'] for row in rows}
        for task in self.tasks:
            event_id = self.event_id(task)
            if event_id not in existing:
                store.ingest_event_and_runs(AutomationEvent(
                    event_id=event_id, event_type=EVENT, source='optibrain-development',
                    occurred_at=now.isoformat(), correlation_id=self.plan_hash,
                    idempotency_key=event_id, payload={'plan_sha256': self.plan_hash,
                        'source': self.plan['source'], 'input_sha256': self.plan['input_sha256'],
                        'goal': self.plan['goal'], 'task': asdict(task)}))
        rows = store.recent_runs()
        if len(rows) != len(ids) or {r['event_id'] for r in rows} != ids:
            raise ValueError('One routed run per task required')
        return store, {row['event_id']: row['run_id'] for row in rows}

    def run(self, sample, handlers, reviewers, *, paused=False, clock=None, task_gate=None):
        clock = clock or (lambda: datetime.now(timezone.utc))
        with self.scope.lock():
            now = clock()
            self.scope.verify(now)
            store, ids = self._open(now)
            recovered = store.recover_expired_claims(now=now)
            report = {'plan_sha256': self.plan_hash, **self.plan, 'recovery': recovered,
                      'model_turns': 0, 'model_tokens': 0, 'incremental_cost_cad': '0.00', 'results': {}}
            for task in self.tasks:
                run_id = ids[self.event_id(task)]
                row = store.get_run(run_id)
                state = row['status']
                reason = None
                if state == 'queued':
                    if task.lane != 'deterministic':
                        state, reason = 'APPROVAL_REQUIRED', 'owner_authority_required'
                    elif any(report['results'][parent]['state'] != 'COMPLETED' for parent in task.parents):
                        state, reason = 'BLOCKED', 'dependency_not_completed'
                    else:
                        state, reason = admission(sample(), clock(), paused=paused)
                        if state == 'ELIGIBLE' and task_gate is not None:
                            state, reason = task_gate(task, report['results'], clock())
                        if state == 'ELIGIBLE':
                            state = self._execute(store, run_id, task, handlers, reviewers, clock)
                            row = store.get_run(run_id)
                report['results'][task.name] = {
                    'state': state.upper(), 'run_id': run_id, 'reason': reason,
                    'checkpoint': row['context'] if state == 'completed' else None,
                }
            return report

    def _execute(self, store, run_id, task, handlers, reviewers, clock):
        attempt = store.claim_run(run_id, 'development-pilot', lease_seconds=LEASE_SECONDS, now=clock())
        if attempt is None:
            raise RuntimeError('Exclusive claim refused')
        marker = store.begin_claimed_action(
            run_id, attempt, step_id='verify-and-checkpoint', action='pilot.deterministic',
            action_identity=self.event_id(task), attempt=1, now=clock())
        if marker is None:
            raise RuntimeError('Action marker refused')
        started = monotonic()
        try:
            result = handlers[task.name]()
            review = reviewers[task.name](result)
            if review.get('passed') is not True or not review.get('check'):
                raise ValueError('Independent verification did not pass')
            checkpoint = {'source': self.plan['source'], 'input_sha256': self.plan['input_sha256'],
                          'result': result, 'result_sha256': digest(result), 'review': review,
                          'wall_seconds': round(monotonic() - started, 6)}
            if len(json.dumps(checkpoint).encode()) > 8192:
                raise ValueError('Checkpoint size exceeded')
        except Exception as error:
            now = clock()
            if not store.complete_claimed_action(run_id, attempt, marker, succeeded=False,
                    error=type(error).__name__, failure_category='permanent', reason_code='pilot_verification_failed', now=now):
                raise RuntimeError('Failed action remains ambiguous') from error
            if not store.finish_claim(run_id, attempt, status='failed', failure_category='permanent',
                    reason_code='pilot_verification_failed', now=now):
                raise RuntimeError('Failed action was not finalized') from error
            return 'failed'
        if not store.complete_claimed_action(run_id, attempt, marker, succeeded=True, result=checkpoint,
                                             final_context=checkpoint, now=clock()):
            raise RuntimeError('Result arrived after its lease')
        return 'completed'
