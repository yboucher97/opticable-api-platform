from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import tempfile
import unittest

from workflow.automation.autonomy_pilot import (
    DISK_FLOOR, LEASE_SECONDS, Pilot, Task, admission, allowance, retry_after,
)
from workflow.automation.operational_recovery import DevelopmentScope, RULE


NOW = datetime(2026, 11, 21, 14, tzinfo=timezone.utc)
G = 1024**3


def sample(now=NOW):
    return {
        'host': 'vps-f8e9b20e', 'observed_at': now.isoformat(), 'backup_at': now.isoformat(),
        'flags_off': 45, 'flag_total': 45, 'protected_match': 76, 'protected_total': 76,
        'golden_local_restore': 'PASS', 'maintenance': {
            key: 'inactive' for key in ('optibrain-backup', 'optibrain-phase2a-upload', 'optibrain-resource-verify')},
        'maintenance_results': {
            key: 'success' for key in ('optibrain-backup', 'optibrain-phase2a-upload', 'optibrain-resource-verify')},
        'health_latency': {k: {'http': 200, 'max_ms': 20} for k in ('api', 'pdf', 'omada')},
        'core': {'caddy.service': {'ActiveState': 'active'}},
        'optional_generation_paused': True, 'scope': 'deterministic_read_only_validation',
        'psi_some_avg10_pct': {'cpu': 0, 'memory': 0, 'io': 0},
        'filesystem_bytes': {'free': 52 * G}, 'memory_kib': {'MemAvailable': 20 * 1024**2}, 'load': [0.2],
    }


def quota(at, used, reset):
    return {'status': 'OBSERVED', 'observed_at': at.isoformat(), 'rate_limits': {
        'primary': {'usedPercent': used, 'windowDurationMins': 10080, 'resetsAt': int(reset.timestamp())}}}


class PolicyTests(unittest.TestCase):
    def test_resource_and_health_defer_before_work(self):
        cases = (
            ({'filesystem_bytes': {'free': DISK_FLOOR}}, 'RETRY_WAIT'),
            ({'memory_kib': {'MemAvailable': G // 1024}}, 'RETRY_WAIT'),
            ({'psi_some_avg10_pct': {'cpu': 0, 'memory': 1.5, 'io': 0}}, 'RETRY_WAIT'),
            ({'load': [4]}, 'RETRY_WAIT'),
            ({'psi_some_avg10_pct': {'cpu': 15, 'memory': 0, 'io': 0}}, 'RETRY_WAIT'),
            ({'psi_some_avg10_pct': {'cpu': 0, 'memory': 0, 'io': 3}}, 'RETRY_WAIT'),
            ({'flags_off': 44}, 'BLOCKED'),
            ({'protected_match': 75}, 'BLOCKED'),
            ({'golden_local_restore': 'UNVERIFIED'}, 'BLOCKED'),
            ({'backup_at': (NOW - timedelta(days=2)).isoformat()}, 'BLOCKED'),
            ({'health_latency': {'api': {'http': 200, 'max_ms': 400}}}, 'BLOCKED'),
            ({'operator_paused': True}, 'PAUSED'),
            ({'scope': 'generation'}, 'BLOCKED'),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                self.assertEqual(admission(sample() | overrides, NOW)[0], expected)
        slow = sample()
        slow['maintenance']['optibrain-backup'] = 'activating'
        self.assertEqual(admission(slow, NOW), ('RETRY_WAIT', 'critical_maintenance'))
        self.assertEqual(admission(sample(), NOW + timedelta(minutes=16))[0], 'BLOCKED')
        interrupted = sample()
        interrupted['maintenance_results']['optibrain-backup'] = 'signal'
        self.assertEqual(admission(interrupted, NOW), ('BLOCKED', 'backup_or_verification_result_unproven'))
        interrupted['maintenance_results'] = {}
        self.assertEqual(admission(interrupted, NOW)[0], 'BLOCKED')

    def test_server_retry_after_delta_date_backoff_and_bound(self):
        self.assertEqual(retry_after('1800', 1, NOW, jitter=3), NOW + timedelta(seconds=1803))
        future = NOW + timedelta(hours=2)
        self.assertEqual(retry_after(format_datetime(future, usegmt=True), 2, NOW), future)
        self.assertEqual(retry_after('bogus', 3, NOW, jitter=2), NOW + timedelta(seconds=242))
        with self.assertRaises(ValueError):
            retry_after(None, 4, NOW)

    def test_refill_needs_fresh_independent_observation_and_retains_reserve(self):
        reset = NOW + timedelta(minutes=2)
        prior = quota(NOW, 70, reset)
        self.assertEqual(allowance(prior, NOW, windows=(10080,)), ('RETRY_WAIT', reset))
        self.assertEqual(allowance(prior, NOW, windows=(300, 10080)), ('UNKNOWN', None))
        after = reset + timedelta(seconds=1)
        self.assertEqual(allowance(prior, after, windows=(10080,), prior_reset=reset), ('BLOCKED', None))
        fresh = quota(after, 5, after + timedelta(days=7))
        self.assertEqual(allowance(fresh, after, windows=(10080,), prior_reset=reset), ('ELIGIBLE', None))
        self.assertEqual(allowance({}, after, windows=(10080,)), ('UNKNOWN', None))


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scope = DevelopmentScope(Path(self.temp.name).resolve())
        self.scope.write('.optibrain-development.json', json.dumps({
            'environment': 'isolated-development', 'production_allowed': False,
            'rule': RULE, 'root': str(self.scope.root),
            'issued_at': NOW.isoformat(), 'expires_at': (NOW + timedelta(hours=1)).isoformat(),
        }).encode())
        self.tasks = (Task('requires-approval', 80, lane='protected'), Task('reconcile', 70),
                      Task('review-quote', 60, ('reconcile',)), Task('recovery', 50))
        self.pilot = Pilot(self.scope, self.tasks, goal='fixture', source='a'*40, input_hash='b'*64)

    def callbacks(self):
        calls = []
        actions = {t.name: lambda n=t.name: (calls.append(n) or {'name': n}) for t in self.tasks}
        reviews = {t.name: lambda out, n=t.name: {'passed': out['name'] == n, 'check': 'independent assertion'}
                   for t in self.tasks}
        return calls, actions, reviews

    def test_three_consecutive_checkpoints_and_restart_without_duplicate_work(self):
        calls, actions, reviews = self.callbacks()
        first = self.pilot.run(sample, actions, reviews, clock=lambda: NOW)
        second = self.pilot.run(sample, actions, reviews, clock=lambda: NOW)
        self.assertEqual(calls, ['reconcile', 'review-quote', 'recovery'])
        self.assertEqual(first['results'], second['results'])
        self.assertEqual(first['results']['requires-approval']['state'], 'APPROVAL_REQUIRED')
        self.assertEqual([v['state'] for v in list(first['results'].values())[1:]], ['COMPLETED'] * 3)

    def test_rejected_review_blocks_dependent_and_continues_independent(self):
        calls, actions, reviews = self.callbacks()
        reviews['reconcile'] = lambda out: {'passed': False}
        out = self.pilot.run(sample, actions, reviews, clock=lambda: NOW)['results']
        self.assertEqual(calls, ['reconcile', 'recovery'])
        self.assertEqual([v['state'] for v in out.values()], ['APPROVAL_REQUIRED','FAILED','BLOCKED','COMPLETED'])

    def test_maintenance_and_pause_hold_before_any_handler(self):
        calls, actions, reviews = self.callbacks()
        paused = self.pilot.run(sample, actions, reviews, paused=True, clock=lambda: NOW)
        self.assertEqual(paused['results']['reconcile']['state'], 'PAUSED')
        active = sample()
        active['maintenance']['optibrain-resource-verify'] = 'active'
        deferred = self.pilot.run(lambda: active, actions, reviews, clock=lambda: NOW)
        self.assertEqual(deferred['results']['reconcile']['state'], 'RETRY_WAIT')
        self.assertEqual(calls, [])

    def test_source_drift_and_linked_ledger_refused(self):
        self.pilot.run(sample, {}, {}, paused=True, clock=lambda: NOW)
        wrong = Pilot(self.scope, self.tasks, goal='fixture', source='c'*40, input_hash='b'*64)
        with self.assertRaisesRegex(ValueError, 'another plan'):
            wrong.run(sample, {}, {}, paused=True, clock=lambda: NOW)
        os.link(self.scope.path('automation.db'), self.scope.path('hardlink.db'))
        with self.assertRaisesRegex(ValueError, 'single-link'):
            self.pilot.run(sample, {}, {}, paused=True, clock=lambda: NOW)

    def test_crash_after_claim_and_after_marker_recovers_only_unstarted_task(self):
        pid = os.fork()
        if pid == 0:
            try:
                with self.scope.lock():
                    store, ids = self.pilot._open(NOW)
                    before, after = self.tasks[1], self.tasks[3]
                    for task in (before, after):
                        run_id = ids[self.pilot.event_id(task)]
                        attempt = store.claim_run(run_id, 'fixture-crash', lease_seconds=LEASE_SECONDS, now=NOW)
                        if task == after:
                            store.begin_claimed_action(run_id, attempt, step_id='verify-and-checkpoint',
                                action='pilot.deterministic', action_identity=self.pilot.event_id(task), attempt=1, now=NOW)
                os._exit(9)
            except BaseException:
                os._exit(2)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 9)
        after = NOW + timedelta(seconds=LEASE_SECONDS + 1)
        calls, tasks, reviews = self.callbacks()
        out = self.pilot.run(lambda: sample(after), tasks, reviews, clock=lambda: after)
        self.assertEqual(out['recovery'], {'requeued': 1, 'human_action_required': 1})
        self.assertEqual(out['results']['recovery']['state'], 'HUMAN_ACTION_REQUIRED')
        self.assertEqual(calls, ['reconcile', 'review-quote'])
