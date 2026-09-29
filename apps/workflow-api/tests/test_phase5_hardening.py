"""Final review cases: native evidence, renewal ambiguity, release ordering."""
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import tempfile
from pathlib import Path
import types
import unittest
from unittest.mock import patch

import httpx

import test_phase5_notification as native_tests
import test_phase5_campaign as ops_tests
from test_phase5_campaign import campaign, provider
from workflow.automation.desired_journal import DesiredJournal, resource_key
from workflow.automation.desired_state import DesiredStateController
from workflow.automation.events import EventLedger
from workflow.automation.native_notifications import (NativeNotificationWorker, CHANNEL, ORG,
    mark_synthetic, native_health, origin_evidence, effective_endpoint)
from workflow.automation.webhooks import WebhookEndpoint, accept_delivery, WebhookError
from workflow.automation.health_monitor import AutomationHealthMonitor
from workflow.automation.sync_runtime import SyncJob, sync_one_due
from workflow.automation.delta_sync import DeltaSync


class NotificationHardeningTests(unittest.TestCase):
    def setUp(self):
        native_tests.NativeSubscriptionTests.setUp(self)
        self.path = Path(self.tmp.name) / 'notification.json'
        self.path.write_text(self.document.model_dump_json())
        self.worker = NativeNotificationWorker(self.controller, self.path)
        self.adapter = self.registry.resolve(self.resource)
        self.controller.apply(self.document, self.controller.plan(self.document))
        self.fake.calls.clear()
        self.initial_expiry = datetime.fromisoformat(os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY'])

    def due(self, *, expired=False):
        self.now = self.initial_expiry + timedelta(hours=1) if expired else self.initial_expiry - timedelta(hours=12)
        self.adapter.clock = lambda: self.now

    def test_renewal_not_due_has_no_mutation(self):
        self.worker.poll()
        self.assertEqual(self.fake.writes, [])
        self.assertEqual(native_health(self.store)['native_subscription_status'], 'verified')

    def test_due_one_reviewed_mutation_with_durable_intent_and_readback(self):
        self.due()
        original = self.fake.request
        def request(service, method, path, **kwargs):
            if method != 'GET':
                intent = self.controller.journal.last(resource_key(self.resource), ('started',))
                self.assertEqual(intent['metadata']['action'], 'update')
                self.assertEqual(intent['metadata']['native_expected']['expiry'], kwargs['body']['watch'][0]['channel_expiry'])
            return original(service, method, path, **kwargs)
        self.fake.request = request
        self.worker.poll()
        self.assertEqual(len(self.fake.writes), 1)
        method, arguments = self.fake.writes[0]
        self.assertEqual(method, 'PATCH')
        body = arguments['body']['watch'][0]
        self.assertEqual(body['channel_id'], CHANNEL)
        self.assertEqual(body['events'], ['Leads.create', 'Leads.edit'])
        self.assertEqual(body['notify_url'], os.environ['OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT'])
        self.assertEqual(body['token'], os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL'])
        expiry = datetime.fromisoformat(body['channel_expiry'])
        self.assertEqual(expiry, self.now + timedelta(days=6))
        self.assertEqual(self.controller.plan(self.document).summary, {'noop': 1})
        self.assertEqual(native_health(self.store, now=self.now)['native_subscription_status'], 'verified')

    def test_successful_renewal_repeat_and_restart_are_noops(self):
        self.due(); self.worker.poll(); self.worker.poll()
        restarted = DesiredStateController(self.registry, self.store)
        NativeNotificationWorker(restarted, self.path).poll()
        self.assertEqual(len(self.fake.writes), 1)
        self.assertEqual(restarted.plan(self.document).summary, {'noop': 1})

    def test_timeout_matching_readback_reconciles_without_second_write(self):
        self.due(); self.fake.lose = True
        self.worker.poll(); self.worker.poll()
        health = native_health(self.store, now=self.now)
        self.assertEqual(health['native_subscription_last_renewal_result']['status'], 'verified')
        self.assertTrue(health['native_subscription_last_renewal_result']['results'][0]['result']['reconciled_by_readback'])
        self.assertEqual(len(self.fake.writes), 1)

    def test_timeout_mismatch_remains_manual_across_restart_no_write(self):
        self.due(); self.fake.lose = True; self.fake.skip_verify = True
        self.worker.poll()
        restarted = DesiredStateController(self.registry, self.store)
        NativeNotificationWorker(restarted, self.path).poll()
        self.assertEqual(native_health(self.store)['native_subscription_status'], 'human_action_required')
        self.assertEqual(len(self.fake.writes), 1)

    def test_timeout_unknown_readback_remains_manual_no_write(self):
        self.due()
        original = self.fake.request
        attempts = []
        def request(service, method, path, **kwargs):
            if method == 'PATCH':
                attempts.append(method)
                self.fake.skip_verify = True
                self.fake.error = httpx.ReadTimeout('fixture secret never printed')
                raise httpx.ReadTimeout('fixture response lost')
            return original(service, method, path, **kwargs)
        self.fake.request = request
        self.worker.poll(); self.worker.poll()
        self.assertTrue(self.controller.journal.unresolved(resource_key(self.resource)))
        self.assertEqual(native_health(self.store)['native_subscription_status'], 'human_action_required')
        # Count attempts at the transport boundary, even when response is lost.
        self.assertEqual(attempts, ['PATCH'])

    def test_unrelated_channel_and_events_refused_before_provider_access(self):
        for field, value in [('channel_id', '999'), ('events', ['Deals.edit'])]:
            altered = self.document.model_copy(deep=True)
            if field == 'channel_id': altered.resources[0].identity[field] = value
            else: altered.resources[0].desired[field] = value
            self.path.write_text(altered.model_dump_json())
            calls = len(self.fake.calls)
            with self.subTest(field=field), self.assertRaises(ValueError): self.worker.poll()
            self.assertEqual(len(self.fake.calls), calls)
        self.assertFalse(self.fake.writes)

    def test_alternate_identity_cannot_bypass_durable_channel_journal(self):
        self.document.resources[0].identity['module'] = 'Leads'
        self.path.write_text(self.document.model_dump_json())
        with self.assertRaises(ValueError): self.worker.poll()
        self.assertFalse(self.fake.calls)

    def test_expired_missing_channel_never_recreated_automatically(self):
        self.due(expired=True); self.fake.rows = []
        self.worker.poll(); self.worker.poll()
        self.assertFalse(self.fake.writes)
        self.assertEqual(native_health(self.store, now=self.now)['native_subscription_status'], 'degraded')

    def test_crash_after_intent_and_provider_acceptance_reconciles_readback_without_write(self):
        self.due()
        renewal = self.document.model_copy(deep=True)
        renewal.resources[0].desired['renewal_expiry'] = (self.now + timedelta(days=6)).isoformat()
        change = self.controller.plan(renewal).changes[0]
        evidence = {'action': 'update', **self.adapter.intent_evidence(renewal.resources[0], change)}
        self.controller.journal.record('started', resource_key(self.resource), evidence, 'fixture-crash')
        self.fake.rows[0]['channel_expiry'] = change.desired['expiry']
        restarted = DesiredStateController(self.registry, self.store)
        NativeNotificationWorker(restarted, self.path).poll()
        self.assertFalse(self.fake.writes)
        self.assertFalse(restarted.journal.unresolved(resource_key(self.resource)))
        self.assertEqual(restarted.plan(self.document).summary, {'noop': 1})

    def test_health_does_not_mask_changed_authentication_with_old_verified_status(self):
        self.worker.poll()
        with patch.dict(os.environ, {'OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT': 'https://changed.example.test/callback'}):
            self.assertEqual(native_health(self.store)['native_subscription_status'], 'configuration_drift')

    def test_changed_credential_or_destination_rejects_reviewed_renewal_plan(self):
        self.due()
        renewal = self.document.model_copy(deep=True)
        renewal.resources[0].desired['renewal_expiry'] = (self.now + timedelta(days=6)).isoformat()
        plan = self.controller.plan(renewal)
        self.assertEqual(plan.summary, {'update': 1})
        for key, value in [('OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL', 'changed-credential-is-32bytes-long'),
                           ('OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT', 'https://different.example.test/callback')]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaisesRegex(ValueError, 'Stale'):
                self.controller.apply(renewal, plan)
        self.assertFalse(self.fake.writes)

    def test_expired_channel_degrades_health_but_delta_keeps_reading(self):
        self.due(expired=True)
        health = native_health(self.store, now=self.now)
        self.assertEqual(health['native_subscription_status'], 'expired')
        class DeltaRead:
            calls = []
            def request(inner, service, method, path, **kwargs):
                inner.calls.append(method)
                return {'ok': True, 'status': 204}
        fake = DeltaRead()
        DeltaSync(self.store).initialize('zoho_crm', ORG, 'Leads', cursor=datetime.now(timezone.utc).isoformat())
        jobs = [SyncJob(provider='zoho_crm', source_account=ORG, stream='Leads', enabled=True)]
        sync_one_due(self.store, jobs, lambda: '', fake)
        self.assertEqual(fake.calls, ['GET'])
        self.assertEqual(DeltaSync(self.store).snapshot('zoho_crm', ORG, 'Leads', 'incremental')['status'], 'idle')
        with patch('workflow.automation.native_notifications.native_health', return_value=health):
            snapshot = AutomationHealthMonitor(self.store, sync_health=lambda: {'healthy': True}).inspect({'enabled': False})
        self.assertIn('native_subscription_degraded', [a['code'] for a in snapshot['alerts']])
        self.assertNotIn('delta_worker_unhealthy', [a['code'] for a in snapshot['alerts']])

    def test_verified_renewal_extends_only_exact_callback_expiry(self):
        self.due(); self.worker.poll()
        endpoint = self.endpoint()
        self.assertGreater(datetime.fromisoformat(effective_endpoint(self.store, endpoint).expires_at), self.initial_expiry)
        other = endpoint.model_copy(update={'channel_id': '999'})
        self.assertEqual(effective_endpoint(self.store, other).expires_at, self.initial_expiry.isoformat())
        body = self.payload()
        with patch('workflow.automation.webhooks.datetime') as clock:
            clock.now.return_value = self.initial_expiry + timedelta(hours=1)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            clock.fromtimestamp.side_effect = datetime.fromtimestamp
            body['server_time'] = int((self.initial_expiry + timedelta(hours=1)).timestamp() * 1000)
            self.assertTrue(accept_delivery(EventLedger(self.store), endpoint, {'content-type': 'application/json'}, json.dumps(body).encode())['accepted'])

    def test_plans_audit_results_and_health_contain_no_secrets(self):
        self.due(); self.worker.poll()
        material = json.dumps([self.controller.plan(self.document).model_dump(), self.store.recent_audit(200), native_health(self.store)])
        self.assertNotIn(os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL'], material)
        self.assertNotIn(os.environ['OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT'], material)

    def endpoint(self):
        return WebhookEndpoint(provider='zoho_crm', source_account=ORG, secret_env='OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL',
            channel_id=CHANNEL, expires_at=self.initial_expiry.isoformat(), allowed_event_types=['zoho.crm.Leads.insert', 'zoho.crm.Leads.update'], enabled=True)

    def payload(self):
        return {'token': os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL'], 'channel_id': CHANNEL,
                'server_time': int(datetime.now(timezone.utc).timestamp() * 1000), 'module': 'Leads', 'operation': 'update', 'ids': ['123']}

    def test_no_provider_event_is_pending_not_failed_and_never_waits(self):
        self.assertEqual(origin_evidence(self.store)['provider_origin_delivery'], 'pending')
        settings = types.SimpleNamespace(zoho_gateway=None, zoho_oauth=None, automation=types.SimpleNamespace(db_path=self.store.db_path))
        with patch.object(provider, 'load_settings', return_value=settings), patch.object(provider, 'ZohoOAuthManager'), patch.object(provider, 'ZohoGatewayClient', return_value=self.fake), patch.object(provider.time, 'sleep') as sleep:
            result = provider.run('native-origin-proof')
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['provider_origin_delivery'], 'pending')
        sleep.assert_not_called()

    def test_genuine_authenticated_callback_already_observed_is_durable_verified(self):
        accepted = accept_delivery(EventLedger(self.store), self.endpoint(), {'content-type': 'application/json'}, json.dumps(self.payload()).encode())
        result = origin_evidence(self.store)
        self.assertEqual(result['provider_origin_delivery'], 'verified')
        self.assertEqual(result['evidence']['event_id'], accepted['event_id'])
        self.assertTrue(result['provider_emitted_event_proven'])
        self.assertEqual(native_health(self.store)['provider_origin_delivery'], 'verified')

    def test_synthetic_public_delivery_and_duplicate_never_become_provider_origin(self):
        body = self.payload()
        mark_synthetic(self.store, body)
        headers = {'content-type': 'application/json'}
        first = accept_delivery(EventLedger(self.store), self.endpoint(), headers, json.dumps(body).encode())
        self.assertTrue(first['accepted'])
        self.assertTrue(accept_delivery(EventLedger(self.store), self.endpoint(), headers, json.dumps(body).encode())['duplicate'])
        self.assertEqual(origin_evidence(self.store)['provider_origin_delivery'], 'pending')
        evidence = self.store.recent_audit(200)
        self.assertTrue(any(e['action'] == 'synthetic_delivery_received' for e in evidence))
        body['server_time'] += 1
        accept_delivery(EventLedger(self.store), self.endpoint(), headers, json.dumps(body).encode())
        self.assertEqual(origin_evidence(self.store)['provider_origin_delivery'], 'verified')

    def test_forged_token_never_creates_origin_evidence(self):
        body = self.payload(); body['token'] = 'forged'
        with self.assertRaises(WebhookError):
            accept_delivery(EventLedger(self.store), self.endpoint(), {'content-type': 'application/json'}, json.dumps(body).encode())
        self.assertEqual(origin_evidence(self.store)['provider_origin_delivery'], 'pending')


class MainPromotionTests(unittest.TestCase):
    def setUp(self):
        ops_tests.Phase5CampaignTests.setUp(self)
        self.remote = campaign.BASELINE
        self.calls = []
        self.fail_push = False
        self.remote_after_failed_push = campaign.BASELINE
        self.failed_readback = False
        def git(repository, *args, **kwargs):
            self.calls.append(args)
            if args[0] == '-c': args = args[2:]
            if args[0] == 'ls-remote':
                if self.failed_readback: raise RuntimeError('fixture_remote_unreachable')
                identity = self.job.candidate if 'refs/tags/' in args[-1] else self.remote
                return identity + '\t' + args[-1]
            if args[0] == 'fetch': return ''
            if args[0] == 'rev-parse': return campaign.BASELINE if args[1] == 'FETCH_HEAD' else self.job.candidate
            if args[0] == 'branch': return campaign.BRANCH
            if args[0] == 'status': return ''
            if args[0] == 'merge-base': return campaign.BASELINE
            if args[0] == 'push' and args[-1].endswith(':refs/heads/main'):
                if self.fail_push:
                    self.remote = self.remote_after_failed_push
                    raise RuntimeError('fixture_network_failure')
                self.remote = self.job.candidate
            return ''
        self.job.git = git
        self.gates = ['production_service_ready', 'production_smoke_completed', 'notification_subscription_verified',
            'public_lead_delivery_verified', 'crm_delta_fallback_verified', 'provider_governance_verified',
            'postdeployment_backup_completed', 'offhost_verification_completed', 'final_recovery_gates_verified']

    def allow(self):
        self.job.result.update({key: True for key in self.gates})

    def test_main_unchanged_before_every_recovery_gate(self):
        for missing in self.gates:
            self.allow(); self.job.result[missing] = False
            with self.subTest(missing=missing), self.assertRaisesRegex(RuntimeError, 'before_recovery_gates'):
                self.job.promote_main()
            self.assertEqual(self.remote, campaign.BASELINE)
        self.assertFalse(self.calls)

    def test_all_gates_allow_only_exact_fast_forward_before_tag_publication(self):
        self.allow(); self.job.promote_main()
        self.assertEqual(self.remote, self.job.candidate)
        self.assertTrue(self.job.result['remote_main_promotion_attempted'])
        self.assertTrue(self.job.result['remote_main_promoted'])
        with patch.object(self.job, 'recovery_tag') as tag:
            self.job.publish_final_recovery_tag('fixture-pretag')
        tag.assert_called_once()
        pushes = [c for c in self.calls if 'push' in c]
        self.assertEqual(pushes[0][-3:], ('push', 'origin', self.job.candidate + ':refs/heads/main'))
        self.assertIn('core.hooksPath=' + str(campaign.REPO / 'ops/phase5/git-hooks'), pushes[0])
        self.assertTrue(all(not any('force' in v for v in c) for c in pushes))
        self.assertEqual(self.job.result['final_baseline_sha'], self.job.candidate)

    def test_prepromotion_main_mismatch_fails_closed_before_push(self):
        self.allow(); self.remote = 'b' * 40
        with self.assertRaisesRegex(RuntimeError, 'prepromotion_main_mismatch'): self.job.promote_main()
        self.assertFalse(self.job.result['remote_main_promotion_attempted'])
        self.assertFalse(any(c[0] == 'push' for c in self.calls))
        self.assertEqual(self.job.result['remote_main_sha'], 'b' * 40)

    def test_failed_main_push_reports_exact_observed_remote_without_force_or_retry(self):
        for observed in [campaign.BASELINE, self.job.candidate, 'c' * 40]:
            self.allow(); self.fail_push = True; self.remote = campaign.BASELINE; self.remote_after_failed_push = observed; self.calls.clear()
            with self.subTest(observed=observed), self.assertRaisesRegex(RuntimeError, 'network_failure'):
                self.job.promote_main()
            self.assertEqual(self.job.result['remote_main_sha'], observed)
            self.assertEqual(self.job.result['final_baseline_sha'], observed)
            self.assertEqual(len([c for c in self.calls if 'push' in c]), 1)
            self.assertFalse(any('force' in v for c in self.calls for v in c))

    def test_main_push_unknown_readback_reports_unknown_never_baseline(self):
        self.allow()
        original = self.job.git
        def git(repository, *args, **kwargs):
            if 'push' in args:
                self.failed_readback = True
                raise RuntimeError('fixture_unconfirmed_push')
            return original(repository, *args, **kwargs)
        self.job.git = git
        with self.assertRaises(RuntimeError): self.job.promote_main()
        self.assertEqual(self.job.result['remote_main_sha'], 'unknown')
        self.assertEqual(self.job.result['remote_main_promoted'], 'unknown')
        self.assertEqual(self.job.result['final_baseline_sha'], 'unknown')

    def test_failure_after_deploy_before_main_preserves_baseline_and_v2(self):
        self.job.result.update(production_checkout_advanced=True, production_database_version=2)
        with patch.object(self.job, 'observe_failure_state'), patch.object(self.job, 'checkout_permissions'):
            result = self.job.blocked(RuntimeError('fixture_offhost_failure'), 'encrypted-offhost-verification')
        self.assertEqual(self.remote, campaign.BASELINE)
        self.assertEqual(result['production_database_version'], 2)
        self.assertFalse(result['remote_main_promotion_attempted'])

    def test_tag_cannot_be_published_before_verified_main(self):
        self.job.result.update(remote_main_promoted=False, remote_main_sha=campaign.BASELINE)
        with patch.object(self.job, 'recovery_tag') as tag, self.assertRaisesRegex(RuntimeError, 'before_main_promotion'):
            self.job.publish_final_recovery_tag('fixture-pretag')
        tag.assert_not_called()

    def test_tag_failure_preserves_promoted_main(self):
        self.allow(); self.job.promote_main()
        with patch.object(self.job, 'recovery_tag', side_effect=RuntimeError('fixture_tag_failure')), self.assertRaises(RuntimeError):
            self.job.publish_final_recovery_tag('fixture-pretag')
        self.assertEqual(self.remote, self.job.candidate)
        self.assertFalse(self.job.result.get('recovery_tag_published', False))
        self.assertTrue(self.job.result['recovery_tag_publication_attempted'])

    def test_final_pass_requires_candidate_checkout_main_and_tag_identical(self):
        self.allow(); self.job.promote_main(); self.job.result['postdeployment_tag'] = 'fixture-posttag'
        self.job.result.update(production_git_sha=self.job.candidate, production_database_version=2, production_service_active=True)
        with patch.object(self.job, 'observe_failure_state'):
            self.job.verify_final_identity()
            for key in ['production_git_sha', 'remote_main_sha']:
                previous = self.job.result[key]; self.job.result[key] = campaign.BASELINE
                with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'final_state_unverified'):
                    self.job.verify_final_identity()
                self.job.result[key] = previous
            with patch.object(self.job, 'git', return_value=campaign.BASELINE + '\tfixture-tag'), self.assertRaisesRegex(RuntimeError, 'final_state_unverified'):
                self.job.verify_final_identity()


class CampaignStageFailureTests(unittest.TestCase):
    """Execute the complete real driver against isolated operation fakes."""
    def setUp(self):
        ops_tests.Phase5CampaignTests.setUp(self)
        self.head, self.remote, self.service = campaign.BASELINE, campaign.BASELINE, 'active'
        self.operations = []
        self.failed_stage = None
        self.tag_published = False
        self.archive = self.root / 'fixture.tar.gz'; self.archive.write_bytes(b'fixture backup')
        self.offhost = self.root / 'offhost.json'
        self.offhost.write_text(json.dumps({'generation': 'fixture-generation', 'source_sha256': campaign.sha(self.archive),
                                           'verification_status': 'download_hash_verified'}))
        self.diagnostic = self.root / 'protected-diagnostic'
        self.diagnostic.write_bytes(b'fixture protected diagnostic')
        self.runbook = self.root / 'protected-runbook'
        self.runbook.write_bytes(b'fixture protected runbook')
        self.env = self.root / 'fixture.env'
        self.env.write_text('SITE_WORKFLOW_API_KEY=fixture-private-key\n'); self.env.chmod(0o600)
        original_stage = self.job.stage_start
        def stage(name):
            original_stage(name)
            self.operations.append(('stage', name))
            if name == self.failed_stage: raise RuntimeError('fixture_stage_failure')
        self.job.stage_start = stage
        def git(repository, *args, **kwargs):
            self.operations.append(('git', args))
            if args[0] == '-c': args = args[2:]
            if args[:2] == ('branch', '--show-current'): return campaign.BRANCH
            if args[0] == 'status': return campaign.base.EXPECTED_STATUS if repository == campaign.PROD else ''
            if args[0] == 'rev-parse': return self.head if repository == campaign.PROD else (campaign.BASELINE if args[1] == 'FETCH_HEAD' else self.job.candidate)
            if args[0] == 'merge-base': return campaign.BASELINE
            if args[0] == 'merge':
                self.assertEqual(self.service, 'inactive', 'Source must never advance while service is active')
                self.head = self.job.candidate; return ''
            if args[0] == 'ls-remote':
                if args[-1] == 'refs/heads/main': return self.remote + '\tmain'
                if 'post-phase4' in args[-1]: return campaign.BASELINE + '\tphase4'
                return (self.job.candidate + '\tposttag') if self.tag_published else ''
            if args[0] == 'push':
                if args[-1].endswith(':refs/heads/main'): self.remote = self.job.candidate
                else: self.tag_published = True
            return ''
        self.job.git = git
        self.job.git_bytes = lambda *args: b''
        def run(argv, **kwargs):
            self.operations.append(('run', tuple(argv)))
            if 'run_tests.py' in ' '.join(argv): return json.dumps({'passed': True, 'tests': 419, 'subtests': 374, 'skipped': 0})
            if argv[:2] == ['/usr/bin/systemctl', 'stop']: self.service = 'inactive'
            if argv[:2] == ['/usr/bin/systemctl', 'start'] and argv[-1] == campaign.SERVICE: self.service = 'active'
            return ''
        self.job.run = run
        self.job.service_state = lambda: self.service
        self.job.inspect_database = lambda: {'version': 2, 'run_status_counts': {'completed': 1}, 'watchdog_sample_id': 1}
        self.job.healthy = lambda *args, **kwargs: self.operations.append(('health', args[0]))
        self.job.ready = lambda *args: None
        self.job.wait_watchdog = lambda *args: None
        self.job.protected_unchanged = lambda: None
        def permissions(*args, **kwargs):
            self.operations.append(('source-modes', kwargs))
            if self.failed_stage == 'candidate-source-modes': raise RuntimeError('fixture_source_modes')
            return {'result': 'PASS'}
        self.job.checkout_permissions = permissions
        self.job.service_source_readability = lambda: {'result': 'PASS'}
        def configuration():
            self.job.stage_start('private-phase5-configuration')
            self.job.mark(runtime_configuration_written=True)
        self.job.configuration = configuration
        self.job.smoke = lambda: self.job.mark(production_smoke_completed=True)
        self.job.recovery_tag = lambda *args: self.operations.append(('tag', args))
        def archive(commit, label):
            self.job.stage_start(label + '-backup')
            return self.archive, 'fixture-generation', {}
        self.job.archive = archive
        def restored(archive, generation, manifest, label):
            self.job.stage_start(label + '-restored-v2-drill')
        self.job.restored_drill = restored
        def provider(mode):
            return {'result': 'PASS', 'delivery_class': 'synthetic', 'duplicate': True,
                    'crm_record_writes': 0, 'provider_emitted_event_proven': False,
                    'provider_origin_delivery': 'pending'}
        self.job.provider = provider
        def observed(result):
            result.update(production_git_sha=self.head, remote_main_sha=self.remote, production_database_version=2,
                          production_service_active=self.service == 'active', production_checkout_advanced=self.head == self.job.candidate,
                          remote_main_promoted=self.remote == self.job.candidate)
        self.job.observe_failure_state = observed

    def execute(self):
        with patch.object(campaign.base, 'ENV', self.env), patch.object(campaign.base, 'OFFHOST_STATE', self.offhost), patch.object(campaign.base, 'protected_file'), patch.object(campaign.base, 'PROTECTED', self.diagnostic), patch.object(campaign, 'RUNBOOK', self.runbook):
            return campaign.base.execute_with_evidence(self.job)

    def test_pending_origin_complete_deterministic_deployment_and_release_order(self):
        result = self.execute()
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(result['native_lead_delivery']['provider_origin_delivery'], 'pending')
        self.assertEqual(self.remote, self.job.candidate)
        stages = [entry[1] for entry in self.operations if entry[0] == 'stage']
        self.assertLess(stages.index('postdeployment-restored-v2-drill'), stages.index('fast-forward-remote-main'))
        self.assertLess(stages.index('encrypted-offhost-verification'), stages.index('fast-forward-remote-main'))
        self.assertLess(stages.index('fast-forward-remote-main'), stages.index('publish-final-phase5-recovery-tag'))
        self.assertEqual(result['final_baseline_sha'], self.job.candidate)

    def test_failures_before_promotion_preserve_observed_main_and_never_roll_back_v2(self):
        failures = ['stop-and-materialize-candidate', 'candidate-source-modes', 'private-phase5-configuration',
                    'candidate-startup-and-health', 'additive-native-subscription', 'authenticated-public-lead-delivery-drill',
                    'crm-delta-fallback-verification', 'durable-provider-origin-observation', 'live-provider-noop-and-health',
                    'postdeployment-backup', 'postdeployment-restored-v2-drill', 'encrypted-offhost-verification',
                    'final-health-protections-before-main-promotion']
        for failed in failures:
            self.setUp(); self.failed_stage = failed
            with self.subTest(stage=failed):
                result = self.execute()
                self.assertEqual(result['result'], 'BLOCKED')
                self.assertEqual(result['remote_main_sha'], campaign.BASELINE)
                self.assertFalse(result['remote_main_promotion_attempted'])
                self.assertEqual(result['production_database_version'], 2)
                self.assertEqual(result['production_git_sha'], self.head)
                self.assertEqual(result['production_service_active'], self.service == 'active')
                self.assertFalse(any(op[0] == 'git' and op[1][0] in {'reset', 'revert'} for op in self.operations))

    def test_failure_at_tag_publication_reports_main_already_promoted(self):
        self.failed_stage = 'publish-final-phase5-recovery-tag'
        result = self.execute()
        self.assertEqual(result['result'], 'BLOCKED')
        self.assertEqual(result['remote_main_sha'], self.job.candidate)
        self.assertTrue(result['remote_main_promoted'])
        self.assertEqual(result['final_baseline_sha'], self.job.candidate)




class AtomicMainPushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.bare, self.clone = Path(self.tmp.name) / 'origin.git', Path(self.tmp.name) / 'candidate'
        self.command(['git', 'init', '--bare', '--quiet', str(self.bare)])
        seed = Path(self.tmp.name) / 'seed'
        self.command(['git', 'init', '--quiet', str(seed)])
        self.command(['git', '-C', str(seed), 'config', 'user.name', 'Fixture'])
        self.command(['git', '-C', str(seed), 'config', 'user.email', 'fixture@example.invalid'])
        self.command(['git', '-C', str(seed), 'checkout', '-b', 'main'])
        source = seed / 'fixture.txt'
        source.write_text('baseline\n')
        self.command(['git', '-C', str(seed), 'add', '.'])
        self.command(['git', '-C', str(seed), 'commit', '-qm', 'baseline'])
        self.baseline = self.command(['git', '-C', str(seed), 'rev-parse', 'HEAD']).stdout.strip()
        self.command(['git', '-C', str(seed), 'checkout', '-b', campaign.BRANCH])
        for content in ('intermediate', 'candidate'):
            source.write_text(content + '\n')
            self.command(['git', '-C', str(seed), 'commit', '-am', content, '-q'])
        self.command(['git', '-C', str(seed), 'remote', 'add', 'origin', str(self.bare)])
        self.command(['git', '-C', str(seed), 'push', '-q', 'origin', 'main', campaign.BRANCH])
        self.command(['git', 'clone', '--quiet', '--branch', campaign.BRANCH, str(self.bare), str(self.clone)])
        self.hooks = Path(self.tmp.name) / 'hooks'
        self.hooks.mkdir()
        template = (campaign.REPO / 'ops/phase5/git-hooks/pre-push').read_text()
        self.assertIn(campaign.BASELINE, template)
        hook = self.hooks / 'pre-push'
        hook.write_text(template.replace(campaign.BASELINE, self.baseline))
        hook.chmod(0o755)
        self.candidate = self.command(['git', '-C', str(self.clone), 'rev-parse', 'HEAD']).stdout.strip()

    def command(self, argv, *, check=True):
        return subprocess.run(argv, capture_output=True, text=True, check=check, timeout=30)

    def push(self):
        return self.command(['git', '-C', str(self.clone), '-c', 'core.hooksPath=' + str(self.hooks),
                             'push', 'origin', self.candidate + ':refs/heads/main'], check=False)

    def test_exact_advertised_baseline_allows_normal_fast_forward(self):
        result = self.push()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(['git', '-C', str(self.bare), 'rev-parse', 'refs/heads/main']).stdout.strip(), self.candidate)

    def test_changed_advertised_ancestor_is_refused_even_when_fast_forward_possible(self):
        ancestor = self.command(['git', '-C', str(self.clone), 'rev-parse', self.candidate + '^']).stdout.strip()
        self.command(['git', '-C', str(self.bare), 'update-ref', 'refs/heads/main', ancestor])
        result = self.push()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.command(['git', '-C', str(self.bare), 'rev-parse', 'refs/heads/main']).stdout.strip(), ancestor)


if __name__ == '__main__': unittest.main()
