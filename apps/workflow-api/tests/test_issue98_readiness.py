"""Issue #98 regressions: real contract shapes, no provider or business effects."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import contextlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from workflow.automation.readiness import native_watch_signal, build_readiness, queue_depth_signal
from workflow.automation.store import AutomationStore

ROOT = Path(__file__).resolve().parents[3]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod
projection = load('issue98_projection', 'ops/phase14/current_readiness.py')
queue = load('issue98_queue', 'ops/phase15/queue_metrics.py')
NOW = datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.resource = dict(at=NOW.isoformat(), available=58 * projection.GIB,
            backup_age_hours=1, backup_generation='fixture', alerts=[],
            categories={'local_recovery': 100 * projection.GIB},
            database_checks=dict(at=NOW.isoformat(), databases=[dict(name=n, quick_check='ok') for n in
                ['automation.db', 'phase9-form-receipts.db', 'phase9-intake.db',
                 'phase10-service-events.db', 'phase12-autonomy.db']]))
        self.jobs = [dict(job=n, state='COMPLETED_SUCCESS', timer_active=True) for n in projection.EXPECTED_JOBS]
        self.safety = dict(flag_checks=[True] * 45, controls_closed=True)
        self.deployment = dict(actual_sha='e' * 40, registered_sha='e' * 40,
                               authoritative_host=True, local_recovery_verified=True)
        generation = '20261112T195422Z'
        self.resource['backup_generation'] = generation
        key = 'backups/2026/11/12/' + generation + '.tar.gz.age'
        self.proof = dict(generation=generation, at=NOW.timestamp(),
            archive_path='/var/backups/optibrain/optibrain-backup-' + generation + '.tar.gz',
            plaintext_sha256='a' * 64, ciphertext_sha256='b' * 64,
            remote_object_key=key, remote_bytes=4096,
            prepared_metadata=dict(generation=generation, source_sha256='a' * 64,
                encrypted_sha256='b' * 64, object_key=key, recipient_sha256='c' * 64),
            restore=dict(result='PASS', generation=generation, source_extraction='PASS',
                source_sha256='a' * 64, source_commit='d' * 40, databases_restored=10))
        self.deployment['recovery_proof'] = self.proof
        self.credential = dict(at=NOW.timestamp(), results={
            'GOOGLE': dict(status='VERIFIED_OPERATIONAL_CACHE'), 'ZOHO': dict(status='VERIFIED')})

    def result(self):
        self.snapshot = projection.build_snapshot(self.resource, self.jobs, self.safety,
            self.deployment, self.credential, now=NOW)
        return {r['name']: r for r in self.snapshot['signals']}

    def test_current_registry_does_not_expect_masked_executor(self):
        self.assertNotIn('opticable-phase12-test-runner', projection.EXPECTED_JOBS)
        self.assertIn('optibrain-credential-refresh', projection.EXPECTED_JOBS)
        self.assertIn('optibrain-platform-intelligence', projection.EXPECTED_JOBS)
        self.assertTrue(all(r['state'] == 'OK' for r in self.result().values()))

    def test_does_not_reapply_legacy_staging_size_alarm(self):
        self.assertEqual(self.result()['Growth']['state'], 'OK')

    def test_active_current_sampler_is_not_mistaken_for_stale_prior_completion(self):
        self.jobs[0]['state'] = 'RUNNING'
        self.assertEqual(self.result()['Timers']['state'], 'OK')

    def test_failed_timer_remains_action_required(self):
        self.jobs[0]['timer_active'] = False
        self.assertEqual(self.result()['Timers']['state'], 'ACTION REQUIRED')

    def test_missing_and_duplicate_inventory_cannot_be_green(self):
        self.jobs.pop()
        self.assertEqual(self.result()['Timers']['state'], 'UNKNOWN')
        self.jobs.append(deepcopy(self.jobs[0]))
        self.assertEqual(self.result()['Timers']['state'], 'UNKNOWN')

    def test_never_run_and_stale_jobs_are_not_success(self):
        self.jobs[0]['state'] = 'NEVER_RUN'
        self.assertEqual(self.result()['Timers']['state'], 'UNKNOWN')
        self.jobs[0]['state'] = 'STALE_COMPLETION'
        self.assertEqual(self.result()['Timers']['state'], 'DEGRADED')

    def test_stale_future_and_naive_observations_do_not_get_freshened(self):
        for at in [(NOW - timedelta(hours=2)).isoformat(), (NOW + timedelta(seconds=1)).isoformat(), '2026-11-12T21:00:00']:
            self.resource['at'] = at
            rows = self.result()
            self.assertEqual(rows['Disk']['state'], 'UNKNOWN')
            self.assertEqual(self.snapshot['resource_observed_at'], at)

    def test_missing_backup_proof_cannot_be_readback_success(self):
        self.resource['backup_age_hours'] = None
        self.assertEqual(self.result()['Off-host backup']['state'], 'UNKNOWN')
        self.assertEqual(self.result()['Backup']['state'], 'ACTION REQUIRED')

    def test_restore_and_offline_decryption_are_separate(self):
        rows = self.result()
        self.assertFalse(rows['Off-host backup']['offline_decryption_verified'])
        self.deployment['local_recovery_verified'] = False
        self.assertEqual(self.result()['Backup']['state'], 'ACTION REQUIRED')

    def test_fresh_local_backup_without_offhost_proof_is_not_readback_success(self):
        self.deployment.pop('recovery_proof')
        self.assertEqual(self.result()['Backup']['state'], 'OK')
        self.assertEqual(self.result()['Off-host backup']['state'], 'UNKNOWN')

    def test_offhost_proof_must_bind_exact_generation_hashes_and_restore(self):
        original = deepcopy(self.proof)
        for section, key, value in [
                (None, 'generation', '20261111T195422Z'),
                (None, 'remote_object_key', 'wrong-object.age'),
                (None, 'remote_bytes', 0), (None, 'remote_bytes', True),
                (None, 'ciphertext_sha256', 'malformed'),
                ('prepared_metadata', 'encrypted_sha256', 'e' * 64),
                ('prepared_metadata', 'source_sha256', 'e' * 64),
                ('prepared_metadata', 'object_key', 'wrong-object.age'),
                ('prepared_metadata', 'generation', '20261111T195422Z'),
                ('restore', 'result', 'FAIL'), ('restore', 'source_extraction', 'FAIL'),
                ('restore', 'generation', '20261111T195422Z'),
                ('restore', 'source_sha256', 'e' * 64),
                ('restore', 'databases_restored', 0)]:
            with self.subTest(section=section, field=key, value=value):
                proof = deepcopy(original)
                (proof if section is None else proof[section])[key] = value
                self.deployment['recovery_proof'] = proof
                self.assertEqual(self.result()['Off-host backup']['state'], 'UNKNOWN')

    def test_offhost_proof_age_is_not_refreshed_by_new_resource_sample(self):
        for at in [NOW.timestamp() + 1, float('nan'), float('inf'), 'invalid', True]:
            with self.subTest(at=at):
                self.proof['at'] = at
                self.assertEqual(self.result()['Off-host backup']['state'], 'UNKNOWN')
        self.proof['at'] = (NOW - timedelta(hours=37)).timestamp()
        self.assertEqual(self.result()['Off-host backup']['state'], 'ACTION REQUIRED')
        self.proof['at'] = (NOW - timedelta(hours=2)).timestamp()
        row = self.result()['Off-host backup']
        self.assertEqual(row['state'], 'OK')
        self.assertEqual(row['proof_age_seconds'], 7200)
        self.assertEqual(row['original_observed_at'], self.proof['at'])
        self.assertFalse(row['offline_decryption_verified'])

    def test_malformed_offhost_proof_is_unknown_without_crashing_projection(self):
        for proof in [None, [], {'prepared_metadata': []}, {'restore': None}]:
            with self.subTest(proof=proof):
                self.deployment['recovery_proof'] = proof
                self.assertEqual(self.result()['Off-host backup']['state'], 'UNKNOWN')

    def test_collect_uses_existing_trusted_proof_without_new_provider_calls(self):
        proof_path = '/var/lib/optibrain/autonomous-operations/retention-generation-proofs/' + self.resource['backup_generation'] + '.json'
        values = {'/var/lib/optibrain/resource-management/latest.json': self.resource,
                  '/etc/optibrain/phase7-canary-registration.json': {'candidate_sha': 'e' * 40},
                  proof_path: {}}
        path = Mock();path.read_text.return_value = '1234 4321';path.is_file.return_value = True
        def read(p, *, trusted=False):
            if p == proof_path:
                self.assertTrue(trusted)
            return values.get(p, {})
        with patch.object(projection, 'read_json', side_effect=read) as reader, \
                patch.object(projection, 'Path', return_value=path), \
                patch.object(projection.subprocess, 'check_output', return_value='e' * 40), \
                patch.object(projection.subprocess, 'run', return_value=Mock(stdout='active')):
            for proof, expected in [({}, 'UNKNOWN'), (self.proof, 'OK'), ([], 'UNKNOWN'),
                                     ({'restore': None}, 'UNKNOWN')]:
                with self.subTest(proof=proof):
                    values[proof_path] = proof
                    snapshot = projection.collect(lambda *a, **k: {'state': 'COMPLETED_SUCCESS'}, [], now=NOW)
                    row = next(r for r in snapshot['signals'] if r['name'] == 'Off-host backup')
                    self.assertEqual(row['state'], expected)
                    self.assertEqual(snapshot['provider_calls'], 0)
            reader.assert_any_call(proof_path, trusted=True)
            self.resource['backup_generation'] = '../unexpected'
            reader.reset_mock()
            snapshot = projection.collect(lambda *a, **k: {'state': 'COMPLETED_SUCCESS'}, [], now=NOW)
            self.assertFalse(any('/retention-generation-proofs/' in str(c) for c in reader.call_args_list))
            self.assertEqual(next(r for r in snapshot['signals'] if r['name'] == 'Off-host backup')['state'], 'UNKNOWN')

    def test_stale_integrity_and_missing_required_db_cannot_be_green(self):
        self.resource['database_checks']['at'] = (NOW - timedelta(days=2)).isoformat()
        self.assertEqual(self.result()['DB health']['state'], 'UNKNOWN')
        self.resource['database_checks']['at'] = NOW.isoformat()
        self.resource['database_checks']['databases'].pop()
        self.assertEqual(self.result()['DB health']['state'], 'UNKNOWN')

    def test_known_failed_integrity_is_action_required(self):
        self.resource['database_checks']['databases'][0]['quick_check'] = 'FAILED'
        self.assertEqual(self.result()['DB health']['state'], 'ACTION REQUIRED')

    def test_actual_disabled_flags_are_required(self):
        self.safety['flag_checks'][4] = False
        self.assertEqual(self.result()['Safety flags']['state'], 'ACTION REQUIRED')
        self.safety['flag_checks'] = []
        self.assertEqual(self.result()['Safety flags']['state'], 'UNKNOWN')

    def test_current_registration_mismatch_not_old_receipt_controls_deployment(self):
        self.deployment['registered_sha'] = 'a' * 40
        self.assertEqual(self.result()['Deployment']['state'], 'ACTION REQUIRED')

    def test_credential_freshness_is_from_existing_refresher(self):
        self.credential['at'] -= 3601
        self.assertEqual(self.result()['Credential refresh']['state'], 'UNKNOWN')
        self.credential['at'] = NOW.timestamp()
        self.credential['results']['GOOGLE']['status'] = 'BLOCKED'
        self.assertEqual(self.result()['Credential refresh']['state'], 'ACTION REQUIRED')

    def test_projection_is_pure_and_makes_no_provider_claims(self):
        before = deepcopy(self.resource)
        self.result()
        self.assertEqual(before, self.resource)
        self.assertEqual(self.snapshot['provider_calls'], 0)
        self.assertEqual(self.snapshot['mutations'], 0)


class NativeAndQueueTests(unittest.TestCase):
    def test_unresolved_expired_watch_is_never_relabelled_successful(self):
        row = native_watch_signal(dict(native_subscription_status='human_action_required',
            native_subscription_expires_at=(NOW - timedelta(days=30)).isoformat(),
            native_subscription_last_verified_at=(NOW - timedelta(days=31)).isoformat()), NOW)
        self.assertEqual(row['state'], 'ACTION REQUIRED')
        self.assertIn('Unresolved', row['reason']);self.assertIn('expired', row['reason'])
        self.assertFalse(row['automatic_recreation_authorized'])

    def test_verified_label_does_not_override_expired_or_stale_evidence(self):
        for expiry, verified in [(NOW - timedelta(seconds=1), NOW), (NOW + timedelta(days=1), NOW - timedelta(days=2)),
                                  (NOW + timedelta(days=1), NOW + timedelta(seconds=1))]:
            row = native_watch_signal(dict(native_subscription_status='verified',
                native_subscription_expires_at=expiry.isoformat(),
                native_subscription_last_verified_at=verified.isoformat()), NOW)
            self.assertEqual(row['state'], 'ACTION REQUIRED')

    def test_malformed_expiry_is_unknown_and_never_leaks_value(self):
        row = native_watch_signal(dict(native_subscription_status='verified',
            native_subscription_expires_at='fixture-sensitive-malformed'), NOW)
        self.assertEqual(row['state'], 'UNKNOWN');self.assertNotIn('fixture-sensitive', json.dumps(row))

    def test_claimed_run_prevents_historical_only_classification(self):
        with tempfile.TemporaryDirectory() as t:
            store = AutomationStore(Path(t) / 'automation.db')
            with sqlite3.connect(store.db_path) as db:
                for identity, status in [('retained', 'failed'), ('active', 'claimed')]:
                    db.execute('INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) VALUES(?,?,?,?,?,?)',
                        (identity, 'fixture', 'fixture', 'fixture', status, (NOW - timedelta(days=2)).isoformat()))
            rows = build_readiness(store, {}, api_version='fixture', auth_configured=True,
                                  runtime_path=Path(t) / 'missing.json', now=NOW)['signals']
            queue_row = next(r for r in rows if r['name'] == 'Queue')
            self.assertEqual(queue_row['classification'], 'CURRENT OR UNCLASSIFIED')
            self.assertEqual(queue_row['current_delivery_state'], 'UNKNOWN')
            self.assertEqual(queue_row['retained_failure_count'], 1)
            with sqlite3.connect(store.db_path) as db:
                self.assertEqual(db.execute("SELECT status FROM automation_runs WHERE run_id='retained'").fetchone()[0], 'failed')

    def test_nonempty_active_backlog_with_unknown_age_is_degraded(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'queues.json'
            p.write_text(json.dumps(dict(schema=1, status='measured', captured_at=NOW.isoformat(), queues={
                name: dict(backlog_count=1 if i == 0 else 0, oldest_message_timestamp_ms=0)
                for i, name in enumerate(queue.NAMES)})))
            self.assertEqual(queue_depth_signal(NOW, p)['state'], 'DEGRADED')


class QueueTransportTests(unittest.TestCase):
    PATH = '/accounts/' + 'a' * 32 + '/queues'
    def response(self, body=None):
        result = Mock();result.__enter__ = Mock(return_value=result);result.__exit__ = Mock(return_value=False)
        result.status = 200;result.read.return_value = body or b'{"success":true,"result":[]}'
        return result

    def test_actual_transport_retries_503_with_bound_and_no_redirect(self):
        opener, sleep = Mock(), Mock()
        opener.open.side_effect = [urllib.error.HTTPError(self.PATH, 503, 'fixture', {}, None), self.response()]
        queue.request_json(self.PATH, 'fixture-token', opener=opener, sleep=sleep)
        self.assertEqual(opener.open.call_count, 2);sleep.assert_called_once_with(1)
        for call in opener.open.call_args_list:
            self.assertEqual(call.args[0].method, 'GET')
            self.assertEqual(call.kwargs['timeout'], 5)

    def test_auth_failures_not_retried_or_exposed(self):
        for code in (401, 403, 302):
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = urllib.error.HTTPError(self.PATH, code, 'fixture-secret', {}, None)
            with self.assertRaises(ValueError) as error:
                queue.request_json(self.PATH, 'fixture-token', opener=opener, sleep=sleep)
            self.assertNotIn('secret', str(error.exception));self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_long_or_date_retry_after_defers_to_existing_timer(self):
        for after in ('60', 'Thu, 12 Nov 2026 22:00:00 GMT', 'NaN'):
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = urllib.error.HTTPError(self.PATH, 429, 'fixture', {'Retry-After': after}, None)
            with self.assertRaises(ValueError):queue.request_json(self.PATH, 'fixture', opener=opener, sleep=sleep)
            self.assertEqual(opener.open.call_count, 1);sleep.assert_not_called()

    def test_short_retry_after_then_success(self):
        opener, sleep = Mock(), Mock()
        opener.open.side_effect = [urllib.error.HTTPError(self.PATH, 429, 'fixture', {'Retry-After': '2'}, None), self.response()]
        queue.request_json(self.PATH, 'fixture', opener=opener, sleep=sleep)
        self.assertEqual(opener.open.call_count, 2);sleep.assert_called_once_with(2)

    def test_retry_stops_after_two_transport_failures(self):
        opener, sleep = Mock(), Mock();opener.open.side_effect = urllib.error.URLError('fixture-sensitive')
        with self.assertRaises(ValueError) as error:queue.request_json(self.PATH, 'fixture', opener=opener, sleep=sleep)
        self.assertEqual(opener.open.call_count, 2);self.assertNotIn('sensitive', str(error.exception))

    def test_oversize_and_provider_error_are_not_healthy(self):
        for body in (b'a' * (1024**2 + 1), b'{"success":false,"errors":[]}'):
            opener = Mock();opener.open.return_value = self.response(body)
            with self.assertRaises(ValueError):queue.request_json(self.PATH, 'fixture', opener=opener)
            self.assertEqual(opener.open.call_count, 1)

    def test_queue_body_paths_are_refused_before_auth(self):
        opener = Mock()
        with self.assertRaises(ValueError):queue.request_json(self.PATH + '/messages', 'fixture', opener=opener)
        opener.open.assert_not_called()
        self.assertIsNone(queue.NoRedirect().redirect_request(None, None, 302, 'fixture', {}, 'https://other.invalid'))

    def test_duplicate_queue_inventory_is_refused(self):
        rows = [dict(queue_name=n, queue_id=str(i + 1) * 32) for i, n in enumerate(queue.NAMES)]
        with self.assertRaises(ValueError):queue.sample('a' * 32, 'fixture', lambda _: {'result': rows + rows[:1]})

    def test_real_main_wires_retry_transport_and_persists_only_metrics(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t);env = root / 'env'
            env.write_text('CLOUDFLARE_API_TOKEN=fixture-sensitive-token\nCLOUDFLARE_ACCOUNT_ID=' + 'a' * 32 + '\n')
            rows = [dict(queue_name=n, queue_id=str(i + 1) * 32) for i, n in enumerate(queue.NAMES)]
            metrics = dict(backlog_count=0, backlog_bytes=0, oldest_message_timestamp_ms=0)
            opener, sleep = Mock(), Mock()
            opener.open.side_effect = [urllib.error.HTTPError(self.PATH, 503, 'fixture', {}, None),
                self.response(json.dumps(dict(success=True, result=rows)).encode()),
                self.response(json.dumps(dict(success=True, result=metrics)).encode()),
                self.response(json.dumps(dict(success=True, result=metrics)).encode())]
            transport = queue.request_json
            def path(value):
                return env if str(value) == '/etc/opticable-workflow-api.env' else root
            def get(p, token):
                return transport(p, token, opener=opener, sleep=sleep)
            with patch.object(queue, 'Path', side_effect=path), patch.object(queue.os, 'geteuid', return_value=0), \
                    patch.object(queue.os, 'umask'), patch.object(queue, 'request_json', side_effect=get), \
                    contextlib.redirect_stdout(io.StringIO()):
                queue.main()
            result = (root / 'queue-depth.json').read_text()
            self.assertEqual(json.loads(result)['status'], 'measured')
            self.assertNotIn('sensitive', result)
            self.assertEqual(opener.open.call_count, 4)


if __name__ == '__main__':
    unittest.main()
