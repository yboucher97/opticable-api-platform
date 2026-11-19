"""Fault injection only: no real credentials, production transport or mutations."""
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import contextlib
import importlib.util
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent / 'owner_acceptance'
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
d = module('owner_controller_under_test', HERE / 'controller.py')
m = module('owner_model_under_test', HERE / 'binding_test_model.py')


def package():
    policy = {'id': m.POLICY, 'uid': m.POLICY, 'reusable': False, 'precedence': 1,
        'name': 'Synthetic owner policy', 'decision': 'allow', 'exclude': [],
        'include': [{'email': {'email': 'info@opticable.ca'}}],
        'require': [{'login_method': {'id': m.IDP}}], 'session_duration': '1h'}
    app = {'id': m.APP, 'uid': m.APP, 'type': 'self_hosted', 'name': 'Synthetic test only',
        'domain': 'app.opticable.ca', 'destinations': [{'type': 'public', 'uri': 'app.opticable.ca'}],
        'allowed_idps': [m.IDP], 'aud': 'synthetic-not-a-real-audience',
        'enable_binding_cookie': True, 'session_duration': '1h', 'policies': [deepcopy(policy)]}
    stages = {}
    for name, binding, duration, owner in [('original', True, '1h', '1h'),
        ('short_policy_binding_on', True, '1h', '15m'), ('test_binding_off', False, '15m', '15m')]:
        a, p = m.expected(app, policy, binding, duration, owner); stages[name] = {'app': a, 'policy': p}
    stages['rollback_binding_on_policy_still_short'] = deepcopy(stages['short_policy_binding_on'])
    base = '/accounts/81d07d311d1b51e5e04b451d1f254850/access/apps/' + m.APP
    return {'allowed_paths': {'app': base, 'policy': base + '/policies/' + m.POLICY,
        'revoke': base + '/revoke_tokens'}, 'allowed_get_paths': [base, base + '/policies'],
        'policy_id': m.POLICY, 'exact_bodies': m.bodies(app, policy), 'semantic_stage_readbacks': stages}


class FakeClock:
    def __init__(self): self.value, self.hook = 1000., None
    def monotonic(self): return self.value
    def sleep(self, seconds):
        self.value += seconds
        if self.hook: self.hook()


class FakeCloud:
    def __init__(self, p, clock, stage='original'):
        self.p, self.clock = p, clock
        self.app, self.policy = deepcopy(p['semantic_stage_readbacks'][stage]['app']), deepcopy(p['semantic_stage_readbacks'][stage]['policy'])
        self.calls, self.faults = [], defaultdict(deque)
    def apply(self, method, path, body):
        if method == 'PUT':
            if path == self.p['allowed_paths']['app']:
                self.app['enable_binding_cookie'] = body['enable_binding_cookie']; self.app['session_duration'] = body['session_duration']
            else: self.policy['session_duration'] = body['session_duration']
        self.app['policies'] = [deepcopy(self.policy)]
        if method == 'GET': return deepcopy(self.app) if path == self.p['allowed_paths']['app'] else [deepcopy(self.policy)]
    def request(self, method, path, body, timeout):
        self.calls.append((method, path, deepcopy(body), self.clock.monotonic()))
        faults = self.faults[(method, path)]
        if faults:
            action = faults.popleft()
            if callable(action): return action(method, path, body, timeout)
            self.clock.sleep(min(8, timeout)); raise action
        self.clock.sleep(.01)
        return (202 if method == 'POST' else 200), self.apply(method, path, body)


class FakeWorker:
    def __init__(self, result=None):
        self.results, self.stopped = queue.Queue(), False
        if result: self.results.put(result)
    def start(self): pass
    def stop(self): self.stopped = True


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root, self.clock, self.p = Path(self.temp.name), FakeClock(), package()
        self.j = d.Journal(self.root, self.clock, owner_uid=os.getuid())
        self.cloud = FakeCloud(self.p, self.clock)
        self.provider = d.Provider(self.p, self.cloud, self.j, self.clock, writes=True)
        self.ctl = d.Controller(self.p, m, self.provider, self.j, self.clock)
        self.output = io.StringIO(); self.quiet = contextlib.redirect_stdout(self.output); self.quiet.__enter__(); self.addCleanup(self.quiet.__exit__, None, None, None)
    def off(self):
        self.cloud = FakeCloud(self.p, self.clock, 'test_binding_off'); self.provider.transport = self.cloud
        self.ctl.started = self.clock.monotonic() - 100
        self.j.data.update(used=True, started_monotonic=self.ctl.started, boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()); self.j.flush()
    def writes(self): return [c for c in self.cloud.calls if c[0] != 'GET']
    def test_one_transient_timeout_retries_once_and_records_real_verification(self):
        self.cloud.faults[('GET', self.p['allowed_paths']['app'])].append(d.Failure('CURL_EXIT_28', transient=True))
        with self.provider.limit(self.clock.monotonic() + 40): result = self.provider.get(self.p['allowed_paths']['app'])
        self.assertTrue(result['enable_binding_cookie']); self.assertEqual(len(self.cloud.calls), 2)
        self.assertGreaterEqual(self.cloud.calls[1][3] - self.cloud.calls[0][3], 9)
        log = (self.root / 'execution.jsonl').read_text(); self.assertIn('REQUEST_FAILED', log); self.assertIn('GET_RETRY_BACKOFF', log); self.assertIn('REQUEST_SUCCESS', log)
    def test_repeated_timeouts_do_not_become_success(self):
        self.cloud.faults[('GET', self.p['allowed_paths']['app'])].extend([d.Failure('CURL_EXIT_28', transient=True)] * 2)
        with self.provider.limit(self.clock.monotonic() + 40), self.assertRaises(d.Failure): self.provider.get(self.p['allowed_paths']['app'])
        self.assertEqual(len(self.cloud.calls), 2); self.assertNotIn('REQUEST_SUCCESS', (self.root / 'execution.jsonl').read_text())
    def test_failed_required_monitoring_restores_binding_first(self):
        with self.assertRaisesRegex(d.Failure, 'REQUIRED_READ_UNVERIFIED'):
            self.ctl.execute(lambda: None, lambda: FakeWorker(('failed', 'CURL_EXIT_28')))
        self.ctl.equal(*self.provider.state(), 'original')
        writes = self.writes(); self.assertEqual([x[0] for x in writes], ['PUT', 'POST', 'PUT', 'PUT', 'PUT', 'POST'])
        self.assertTrue(writes[3][2]['enable_binding_cookie']); self.assertEqual(writes[4][2]['session_duration'], '1h')
        self.assertTrue(self.j.data['restored'])
    def test_unknown_configuration_is_never_overwritten(self):
        self.off(); self.cloud.app['domain'] = 'unexpected.example.test'
        with self.assertRaisesRegex(d.Failure, 'UNKNOWN_CONFIGURATION'): self.ctl.restore()
        self.assertEqual(self.writes(), [])
    def test_rate_limit_honors_retry_after(self):
        self.cloud.faults[('GET', self.p['allowed_paths']['app'])].append(d.Failure('HTTP_429', transient=True, status=429, retry_after=5))
        with self.provider.limit(self.clock.monotonic() + 40): self.provider.get(self.p['allowed_paths']['app'])
        self.assertGreaterEqual(self.cloud.calls[1][3] - self.cloud.calls[0][3], 13)
    def test_rate_limit_larger_than_budget_aborts_without_hammering(self):
        self.cloud.faults[('GET', self.p['allowed_paths']['app'])].append(d.Failure('HTTP_429', transient=True, status=429, retry_after=120))
        with self.provider.limit(self.clock.monotonic() + 40), self.assertRaisesRegex(d.Failure, 'RETRY_AFTER'): self.provider.get(self.p['allowed_paths']['app'])
        self.assertEqual(len(self.cloud.calls), 1)
    def test_auth_errors_and_invalid_json_are_not_retried(self):
        for code in ['HTTP_401', 'HTTP_403', 'INVALID_PROVIDER_JSON', 'PROVIDER_SUCCESS_NOT_ACKNOWLEDGED']:
            before = len(self.cloud.calls); self.cloud.faults[('GET', self.p['allowed_paths']['app'])].append(d.Failure(code))
            with self.assertRaisesRegex(d.Failure, code): self.provider.get(self.p['allowed_paths']['app'])
            self.assertEqual(len(self.cloud.calls), before + 1)
    def test_transient_503_and_connection_interruption_are_bounded(self):
        for code in ['HTTP_503', 'CURL_EXIT_7']:
            before = len(self.cloud.calls); self.cloud.faults[('GET', self.p['allowed_paths']['app'])].append(d.Failure(code, transient=True))
            with self.provider.limit(self.clock.monotonic() + 40): self.provider.get(self.p['allowed_paths']['app'])
            self.assertEqual(len(self.cloud.calls), before + 2)
    def test_no_automatic_mutation_retry(self):
        path = self.p['allowed_paths']['revoke']; self.cloud.faults[('POST', path)].append(d.Failure('CURL_EXIT_28', transient=True))
        with self.assertRaises(d.Failure): self.ctl.mutate('initial-revoke', None, self.clock.monotonic() + 20)
        with self.assertRaisesRegex(d.Failure, 'DUPLICATE'): self.ctl.mutate('initial-revoke', None, self.clock.monotonic() + 20)
        self.assertEqual(sum(x[0] == 'POST' for x in self.cloud.calls), 1)
    def test_unacknowledged_initial_revocation_never_opens_test(self):
        self.cloud.faults[('POST', self.p['allowed_paths']['revoke'])].append(d.Failure('CURL_EXIT_28', transient=True))
        with self.assertRaisesRegex(d.Failure, 'CURL_EXIT_28'): self.ctl.execute(lambda: None, FakeWorker)
        self.ctl.equal(*self.provider.state(), 'original')
        self.assertIsNone(self.ctl.started)
        self.assertEqual(sum(x[0] == 'POST' for x in self.cloud.calls), 1)
        self.assertNotIn('OWNER_TEST_OPEN', self.output.getvalue())
    def test_cancelled_read_never_retries_or_reports_success(self):
        cancel = threading.Event(); cancel.set()
        with self.provider.limit(self.clock.monotonic() + 40, cancel), self.assertRaisesRegex(d.Failure, 'READ_CANCELLED'):
            self.provider.get(self.p['allowed_paths']['app'])
        self.assertEqual(self.cloud.calls, [])
    def test_persisted_mutation_identity_cannot_be_reused(self):
        self.j.intent('synthetic', 'PUT', 'app_restore')
        with self.assertRaisesRegex(d.Failure, 'IDENTITY_MISMATCH'):
            self.j.intent('synthetic', 'PUT', 'policy_restore', recovery_retry=True)
    def test_new_approval_and_fresh_ready_are_both_required(self):
        now = datetime.now(timezone.utc)
        receipt = {'state': 'APPROVED', 'package_sha256': 'new-D-only', 'owner': 'info@opticable.ca',
            'ready': True, 'maximum_incremental_cost_cad': 0, 'owner_approval_text_sha256': 'synthetic',
            'executor_sha256': d.sha256(b'synthetic-runner').hexdigest(), 'READY_recorded_at': now.isoformat()}
        with patch.object(d, 'protected', return_value=b'synthetic-runner'):
            d.authorize(receipt, 'new-D-only', self.root / 'runner', now=now)
            for updates in ({'package_sha256': 'consumed-B'}, {'package_sha256': 'consumed-C'}, {'ready': False},
                {'READY_recorded_at': (now - timedelta(seconds=601)).isoformat()},
                {'READY_recorded_at': now.replace(tzinfo=None).isoformat()}):
                with self.assertRaises(d.Failure): d.authorize({**receipt, **updates}, 'new-D-only', self.root / 'runner', now=now)
    def test_interrupted_ledger_reload_preserves_single_use(self):
        stale = d.Journal(self.root, self.clock, owner_uid=os.getuid())
        self.j.data['used'] = True; self.j.flush()
        self.assertFalse(stale.data.get('used', False))
        reloaded = d.Journal(self.root, self.clock, owner_uid=os.getuid())
        ctl = d.Controller(self.p, m, self.provider, reloaded, self.clock)
        with self.assertRaisesRegex(d.Failure, 'CONSUMED'): ctl.execute(lambda: None, FakeWorker)
        self.assertEqual(self.cloud.calls, [])
    def test_final_revocation_unknown_is_not_replayed_by_recovery(self):
        self.off(); self.cloud.faults[('POST', self.p['allowed_paths']['revoke'])].append(d.Failure('CURL_EXIT_28', transient=True))
        with self.assertRaises(d.Failure): self.ctl.restore()
        with self.assertRaisesRegex(d.Failure, 'REVOCATION_ACK_UNKNOWN'): self.ctl.restore()
        self.assertEqual(sum(x[0] == 'POST' for x in self.cloud.calls), 1)
        self.ctl.equal(*self.provider.state(), 'original')
    def test_lost_applied_put_ack_is_reconciled_without_duplicate_put(self):
        self.off()
        def applied(method, path, body, timeout):
            self.cloud.apply(method, path, body); raise d.Failure('CURL_EXIT_28', transient=True)
        self.cloud.faults[('PUT', self.p['allowed_paths']['app'])].append(applied)
        self.ctl.restore(); self.assertTrue(self.j.data['mutations']['restore-app']['reconciled'])
        self.assertEqual(sum(x[0] == 'PUT' and x[1] == self.p['allowed_paths']['app'] for x in self.cloud.calls), 1)
    def test_interrupted_unapplied_restore_can_recover_once_after_verified_get(self):
        self.off(); self.cloud.faults[('PUT', self.p['allowed_paths']['app'])].append(d.Failure('CURL_EXIT_28', transient=True))
        with self.assertRaises(d.Failure): self.ctl.restore()
        recovered = d.Journal(self.root, self.clock, owner_uid=os.getuid())
        ctl = d.Controller(self.p, m, self.provider, recovered, self.clock); self.provider.journal = recovered
        ctl.restore(); self.assertTrue(recovered.data['restored']); self.assertEqual(recovered.data['mutations']['restore-app']['attempts'], 2)
    def test_completed_recovery_does_not_duplicate_writes_or_revokes(self):
        self.off(); self.ctl.restore(); before = len(self.writes()); self.ctl.restore(); self.assertEqual(len(self.writes()), before)
    def test_owner_early_completion_restores_without_waiting(self):
        (self.root / 'owner-stop.json').write_text('{}'); self.ctl.execute(lambda: None, FakeWorker)
        self.assertTrue(self.j.data['restored']); self.assertLess(self.clock.monotonic() - self.ctl.started, 2)
    def test_no_overlapping_or_duplicate_test_after_consumption(self):
        self.j.data['used'] = True
        with self.assertRaisesRegex(d.Failure, 'CONSUMED'): self.ctl.execute(lambda: None, FakeWorker)
        self.assertEqual(self.cloud.calls, [])
    def test_whole_window_reaches_restoration_before_minute23(self):
        self.off(); worker = FakeWorker()
        last = [self.clock.monotonic()]
        def refresh():
            if self.clock.monotonic() - last[0] >= 30:
                last[0] = self.clock.monotonic(); worker.results.put(('verified', last[0]))
        self.clock.hook = refresh
        outcome = self.ctl.supervise(worker); self.assertEqual(outcome, 'RESTORATION_DEADLINE')
        self.assertLessEqual(self.clock.monotonic(), self.ctl.started + 1380)
        self.ctl.restore(); self.assertLess(self.clock.monotonic(), self.ctl.started + 1500); self.assertTrue(worker.stopped)
    def test_stale_required_verification_aborts_promptly(self):
        self.off()
        with self.assertRaisesRegex(d.Failure, 'VERIFICATION_STALE'): self.ctl.supervise(FakeWorker())
        self.assertLess(self.clock.monotonic() - self.ctl.started, 192)
        self.ctl.restore()
    def test_blocked_optional_worker_does_not_block_deadline_or_restore(self):
        self.off(); self.clock.value = self.ctl.started + 1378.8
        entered, release = threading.Event(), threading.Event()
        def optional(): entered.set(); release.wait(2)
        worker = d.ReadWorker(lambda cancel: None, optional, self.j, self.clock)
        original_start = worker.start
        def start(): original_start(); self.assertTrue(entered.wait(.5))
        worker.start = start
        real_start = time.monotonic()
        self.ctl.supervise(worker); self.ctl.restore(); release.set()
        self.assertLess(time.monotonic() - real_start, 1); self.assertTrue(self.j.data['restored'])
    def test_blocked_required_read_cannot_block_restoration_deadline(self):
        self.off(); self.clock.value = self.ctl.started + 1378.8
        entered, release = threading.Event(), threading.Event()
        def required(cancel): entered.set(); release.wait(2)
        worker = d.ReadWorker(required, lambda: None, self.j, self.clock)
        original_start = worker.start
        def start(): original_start(); self.assertTrue(entered.wait(.5))
        worker.start = start
        real_start = time.monotonic(); self.ctl.supervise(worker); self.ctl.restore(); release.set()
        self.assertLess(time.monotonic() - real_start, 1); self.assertTrue(self.j.data['restored'])
    def test_optional_hang_does_not_starve_required_verification(self):
        count, entered, release = [], threading.Event(), threading.Event()
        def optional(): entered.set(); release.wait(2)
        worker = d.ReadWorker(lambda cancel: count.append(True), optional, self.j, interval=.01)
        try:
            worker.start(); self.assertTrue(entered.wait(.5))
            until = time.monotonic() + .5
            while len(count) < 3 and time.monotonic() < until: time.sleep(.005)
            self.assertGreaterEqual(len(count), 3)
        finally: worker.stop(); release.set()
    def test_missed_deadline_recovery_does_not_falsely_claim_on_time(self):
        self.off(); self.clock.value = self.ctl.started + 1600; self.ctl.restore()
        self.assertIn('"within_hard_deadline":false', (self.root / 'execution.jsonl').read_text())
    def test_changed_boot_recovery_reports_unverifiable_historical_time(self):
        self.off(); self.j.data['boot_id'] = 'different-synthetic-boot'; self.ctl.restore()
        self.assertIn('"within_hard_deadline":null', (self.root / 'execution.jsonl').read_text())
    def test_restore_read_outage_never_claims_restored(self):
        self.off(); self.cloud.faults[('GET', self.p['allowed_paths']['app'])].extend([d.Failure('CURL_EXIT_7', transient=True)] * 2)
        with self.assertRaises(d.Failure): self.ctl.restore()
        self.assertFalse(self.j.data.get('restored', False)); self.assertIn('EMERGENCY_RESTORATION_UNVERIFIED', (self.root / 'execution.jsonl').read_text()); self.assertEqual(self.writes(), [])
    def test_read_only_and_unallowlisted_operations_are_rejected(self):
        self.provider.writes = False
        for method, path, key in [('POST', self.p['allowed_paths']['revoke'], None), ('GET', '/unrelated', None), ('PUT', self.p['allowed_paths']['app'], 'policy_short')]:
            with self.assertRaises(d.Failure): self.provider.call(method, path, key)
        self.assertEqual(self.cloud.calls, [])
    def test_exclusive_lock_prevents_second_process(self):
        lock = self.root / 'control.lock'
        code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('x',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m);\ntry:\n with m.exclusive(sys.argv[2],owner_uid=int(sys.argv[3])): pass\nexcept BlockingIOError: sys.exit(2)\nexcept m.Failure: sys.exit(2)"
        with d.exclusive(lock, owner_uid=os.getuid()):
            r = subprocess.run([sys.executable, '-B', '-c', code, str(HERE / 'controller.py'), str(lock), str(os.getuid())], capture_output=True, timeout=5)
            self.assertEqual(r.returncode, 2)
        with d.exclusive(lock, owner_uid=os.getuid()): pass


class TransportTests(unittest.TestCase):
    def test_credentials_only_on_stdin_and_no_transport_retries_or_redirects(self):
        seen = {}
        def run(args, **kw):
            seen.update(args=args, **kw)
            return SimpleNamespace(returncode=0, stdout='{"success":true,"result":{}}\nOPTIBRAIN_META:200||0.1', stderr='')
        d.CurlTransport('synthetic-test-token', run).request('GET', '/synthetic-only', None, 2)
        self.assertNotIn('synthetic-test-token', ' '.join(seen['args'])); self.assertIn('synthetic-test-token', seen['input'])
        self.assertIn('--max-time', seen['args']); self.assertEqual(seen['args'][seen['args'].index('--retry') + 1], '0')
        self.assertNotIn('--insecure', seen['args']); self.assertNotIn('--location', seen['args'])
    def test_partial_or_invalid_responses_are_not_security_success(self):
        for output in ['garbage', '{"success":false}\nOPTIBRAIN_META:200||0.1', '{"success":true,"result":{}}\nOPTIBRAIN_META:202||0.1']:
            transport = d.CurlTransport('synthetic-token', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=output, stderr=''))
            with self.assertRaises(d.Failure): transport.request('GET', '/synthetic-only', None, 2)
    def test_real_slow_http_fixture_has_a_total_transfer_bound(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self): time.sleep(.5); self.close_connection = True
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def fixture_run(args, **kw):
            # Local synthetic fixture only; production transport always enforces HTTPS/API hostname.
            args = list(args); args[args.index('--url') + 1] = 'http://127.0.0.1:' + str(server.server_port)
            args[args.index('--proto') + 1] = '=http'
            return subprocess.run(args, **kw)
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(d.Failure, 'CURL_EXIT_28'): d.CurlTransport('synthetic-token', fixture_run).request('GET', '/fixture', None, .15)
            self.assertLess(time.monotonic() - started, 1)
        finally: server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main(verbosity=2)
