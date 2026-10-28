import concurrent.futures
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from workflow.automation.engine import AutomationEngine
from workflow.automation.events import EventConflict, EventLedger
from workflow.automation.intake_hold import (
    EXECUTION_OFF, HOLD_REASON, HoldUnavailable, IntakeHoldPolicy, hold_event, hold_health)
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore
from workflow.automation.webhooks import WebhookEndpoint, WebhookError, accept_delivery


class PolicyTests(unittest.TestCase):
    def test_default_is_disabled_and_unknown_mode_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(IntakeHoldPolicy.from_environment(execution_enabled=True).enabled)
        for mode in ('true', 'hold', 'HOLD-V1', ''):
            with patch.dict(os.environ, {'OPTIBRAIN_INTAKE_MODE': mode}, clear=True), self.assertRaises(ValueError):
                IntakeHoldPolicy.from_environment(execution_enabled=False)

    def test_every_execution_flag_is_explicitly_off(self):
        env = {**EXECUTION_OFF, 'OPTIBRAIN_INTAKE_MODE': 'hold-v1'}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(IntakeHoldPolicy.from_environment(execution_enabled=False).enabled)
            with self.assertRaises(ValueError):
                IntakeHoldPolicy.from_environment(execution_enabled=True)
        for key in EXECUTION_OFF:
            for value in (None, 'true', 'typo'):
                bad = dict(env)
                if value is None:
                    del bad[key]
                else:
                    bad[key] = value
                with self.subTest(key=key, value=value), patch.dict(os.environ, bad, clear=True), self.assertRaises(ValueError):
                    IntakeHoldPolicy.from_environment(execution_enabled=False)

    def test_capacity_configuration_is_bounded(self):
        for name in ('OPTIBRAIN_INTAKE_MAX_RECEIPTS', 'OPTIBRAIN_INTAKE_MAX_DATABASE_BYTES',
                     'OPTIBRAIN_INTAKE_MINIMUM_FREE_BYTES'):
            for value in ('0', '-1', 'NaN', '9999999999999999'):
                with self.subTest(name=name, value=value), patch.dict(os.environ,
                        {**EXECUTION_OFF, 'OPTIBRAIN_INTAKE_MODE': 'hold-v1', name: value}, clear=True), self.assertRaises(ValueError):
                    IntakeHoldPolicy.from_environment(execution_enabled=False)


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = AutomationStore(self.root/'automation.db')
        self.ledger = EventLedger(self.store)
        self.policy = IntakeHoldPolicy(True, 100, 512*1024**2, 0)

    def event(self, **kw):
        return AutomationEvent.model_validate({'event_id': 'original', 'event_type': 'fixture.business',
            'source': 'fixture', 'payload': {'decision': 'preserve'}, **kw})

    def rows(self, table):
        with self.store._connect() as conn:
            return [tuple(r) for r in conn.execute('SELECT * FROM '+table)]

    def test_receipt_is_atomic_durable_and_restart_does_not_route_it(self):
        self.store.upsert_workflow(WorkflowDefinition.model_validate({'id': 'fixture', 'name': 'fixture',
            'trigger': {'event_types': ['fixture.business']}, 'steps': [{'id': 'send', 'action': 'fixture.forbidden'}]}))
        receipt = hold_event(self.ledger, self.event(), self.policy, legacy_identity=True)
        self.assertEqual(receipt['event_id'], 'original')
        self.assertTrue(receipt['durable'] and receipt['held'])
        self.assertEqual(receipt['run_ids'], [])
        after = EventLedger(AutomationStore(self.store.db_path))
        row = after.inspect('original')
        self.assertEqual(row['status'], 'quarantined')
        self.assertEqual(row['last_error'], HOLD_REASON)
        self.assertEqual(after.process_pending(100), 0)
        self.assertEqual(after.process('original'), [])
        engine = AutomationEngine(self.store, self.root)
        handler = Mock(side_effect=AssertionError('business effect'))
        engine.register_action('fixture.forbidden', handler)
        engine.recover_pending(limit=100)
        handler.assert_not_called()
        self.assertEqual(self.rows('automation_runs'), [])
        self.assertTrue(any(r[4] == HOLD_REASON for r in self.rows('automation_event_history')))

    def test_same_original_id_or_idempotency_key_gets_one_receipt(self):
        one = hold_event(self.ledger, self.event(idempotency_key='stable'), self.policy, legacy_identity=True)
        two = hold_event(self.ledger, self.event(event_id='delivery-retry', idempotency_key='stable'), self.policy, legacy_identity=True)
        self.assertTrue(one['accepted'])
        self.assertTrue(two['duplicate'])
        self.assertEqual(two['event_id'], 'original')
        self.assertEqual(two['received_event_id'], 'delivery-retry')
        self.assertEqual(len(self.rows('automation_events')), 1)
        self.assertEqual(hold_health(self.ledger, self.policy)['held_receipts'], 1)

    def test_identity_conflict_rolls_back_without_replacing_evidence(self):
        hold_event(self.ledger, self.event(idempotency_key='stable'), self.policy, legacy_identity=True)
        before = self.rows('automation_events')
        with self.assertRaises(EventConflict):
            hold_event(self.ledger, self.event(event_id='retry', idempotency_key='stable', payload={'decision': 'different'}), self.policy, legacy_identity=True)
        self.assertEqual(self.rows('automation_events'), before)
        self.assertEqual(hold_health(self.ledger, self.policy)['held_receipts'], 1)

    def test_concurrent_delivery_has_one_winner(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: hold_event(self.ledger, self.event(), self.policy, legacy_identity=True), range(24)))
        self.assertEqual(sum(r['accepted'] for r in replies), 1)
        self.assertEqual(sum(r['duplicate'] for r in replies), 23)
        self.assertEqual(len(self.rows('automation_events')), 1)

    def test_count_capacity_is_serialized_and_duplicates_still_dedupe(self):
        policy = replace(self.policy, max_receipts=3)
        def capture(n):
            try:
                return hold_event(self.ledger, self.event(event_id=str(n)), policy, legacy_identity=True)['accepted']
            except HoldUnavailable:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(capture, range(10))), 3)
        self.assertEqual(len(self.rows('automation_events')), 3)
        existing = self.rows('automation_events')[0][0]
        self.assertTrue(hold_event(self.ledger, self.event(event_id=existing), policy, legacy_identity=True)['duplicate'])
        self.assertFalse(hold_health(self.ledger, policy)['capture_available'])

    def test_disk_database_and_commit_failure_never_acknowledge(self):
        for policy in (replace(self.policy, minimum_free_bytes=10**30), replace(self.policy, max_database_bytes=1)):
            with self.assertRaises(HoldUnavailable):
                hold_event(self.ledger, self.event(), policy, legacy_identity=True)
            self.assertEqual(self.rows('automation_events'), [])
        store = self.store
        class FailedCommit:
            def __enter__(self):
                self.conn = AutomationStore._connect(store)
                return self.conn
            def __exit__(self, *args):
                self.conn.rollback()
                self.conn.close()
                raise sqlite3.OperationalError('fixture commit failed')
            def close(self):
                self.conn.close()
        with patch.object(self.store, '_connect', side_effect=FailedCommit), self.assertRaises(HoldUnavailable):
            hold_event(self.ledger, self.event(), self.policy, legacy_identity=True)
        self.assertEqual(self.rows('automation_events'), [])

    def test_existing_uncertain_state_and_effect_history_are_untouched(self):
        self.ledger.capture(self.event())
        before = self.rows('automation_event_history')
        receipt = hold_event(self.ledger, self.event(), self.policy, legacy_identity=True)
        self.assertTrue(receipt['duplicate'])
        self.assertFalse(receipt['held'])
        self.assertEqual(self.rows('automation_event_history'), before)
        self.assertEqual(self.ledger.inspect('original')['status'], 'accepted')

    def test_separate_process_receipt_survives_immediate_process_exit(self):
        app = str(Path(__file__).resolve().parents[1])
        code = f'''import sys,os;sys.path.insert(0,{app!r})
from pathlib import Path
from workflow.automation.store import AutomationStore
from workflow.automation.events import EventLedger
from workflow.automation.intake_hold import hold_event,IntakeHoldPolicy
from workflow.automation.models import AutomationEvent
hold_event(EventLedger(AutomationStore(Path({str(self.store.db_path)!r}))),AutomationEvent(event_id='process',event_type='fixture.business',source='fixture'),IntakeHoldPolicy(True,100,536870912,0),legacy_identity=True)
os._exit(0)
'''
        subprocess.run([sys.executable, '-I', '-c', code], check=True)
        self.assertEqual(self.ledger.inspect('process')['status'], 'quarantined')
        self.assertEqual(self.ledger.process_pending(), 0)

    def test_authenticated_webhook_is_held_without_dirtying_sync_or_storing_secret(self):
        secret = 'fixture-secret-'*4
        endpoint = WebhookEndpoint(provider='zoho_crm', source_account='fixture-org', secret_env='FIXTURE_NATIVE_TOKEN',
            channel_id='5062683202609281', allowed_event_types=['zoho.crm.Leads.insert'], enabled=True,
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        body = {'token': secret, 'channel_id': endpoint.channel_id, 'server_time': int(datetime.now(timezone.utc).timestamp()*1000),
                'module': 'Leads', 'operation': 'insert', 'ids': ['123']}
        with patch.dict(os.environ, {'FIXTURE_NATIVE_TOKEN': secret}):
            one = accept_delivery(self.ledger, endpoint, {'content-type': 'application/json'}, json.dumps(body).encode(), hold_policy=self.policy)
            two = accept_delivery(self.ledger, endpoint, {'content-type': 'application/json'}, json.dumps(body).encode(), hold_policy=self.policy)
            self.assertTrue(one['held'] and two['duplicate'])
            self.assertNotIn(secret, json.dumps(self.ledger.inspect(one['event_id'])))
            with self.assertRaises(WebhookError):
                accept_delivery(self.ledger, endpoint, {'content-type': 'application/json'}, json.dumps(dict(body,token='wrong')).encode(), hold_policy=self.policy)
        self.assertEqual(len(self.rows('automation_events')), 1)
        self.assertEqual(self.rows('automation_sync_checkpoints'), [])


class ApiHoldTests(HoldTests):
    # Inherit all storage fault/concurrency checks, then exercise actual routes.
    def setUp(self):
        super().setUp()
        from workflow import api
        self.api = api
        for patcher in [patch.object(api, 'automation_store', self.store),
                patch.object(api, 'intake_hold_policy', self.policy),
                patch.object(api, 'settings', replace(api.settings, automation=replace(api.settings.automation, enabled=False))),
                patch.dict(os.environ, {api.settings.api.api_key_env:'fixture-api-key'})]:
            patcher.start(); self.addCleanup(patcher.stop)
        self.auth = {'X-API-Key':'fixture-api-key'}
        self.client = TestClient(api.app)

    def test_api_authentication_and_canonical_receipt(self):
        payload = self.event().model_dump()
        self.assertEqual(self.client.post('/v1/automation/events',json=payload).status_code,401)
        result = self.client.post('/v1/automation/events',headers=self.auth,json=payload)
        self.assertEqual(result.status_code,202)
        self.assertTrue(result.json()['durable'] and result.json()['held'])
        self.assertEqual(result.json()['event_id'],'original')
        self.assertTrue(self.client.post('/v1/automation/events',headers=self.auth,json=payload).json()['duplicate'])
        self.assertEqual(self.client.post('/v1/automation/events',headers=self.auth,json=dict(payload,payload={'changed':True})).status_code,409)
        with patch.dict(os.environ, {self.api.settings.api.api_key_env:''}):
            self.assertEqual(self.client.post('/v1/automation/events',headers=self.auth,json=payload).status_code,503)

    def test_no_identity_no_receipt_and_kernel_off_default_stays_closed(self):
        self.assertEqual(self.client.post('/v1/automation/events',headers=self.auth,
            json={'event_type':'fixture.business','source':'fixture'}).status_code,422)
        with patch.object(self.api,'intake_hold_policy',IntakeHoldPolicy()):
            self.assertEqual(self.client.post('/v1/automation/events',headers=self.auth,json=self.event().model_dump()).status_code,503)
        self.assertEqual(self.rows('automation_events'),[])

    def test_lifespan_starts_no_execution_or_recovery_workers(self):
        native = Mock()
        with patch.object(self.api,'native_notification_worker',native), \
                patch.object(self.api.automation_engine,'sync_definitions') as definitions, \
                patch.object(self.api.automation_engine,'recover_pending') as recover, \
                patch.object(self.api.delta_sync_worker,'start') as delta, TestClient(self.api.app) as client:
            self.assertEqual(client.post('/v1/automation/events',headers=self.auth,json=self.event().model_dump()).status_code,202)
            definitions.assert_not_called(); recover.assert_not_called(); delta.assert_not_called(); native.start.assert_not_called()

    def test_replay_provider_mutations_and_legacy_execution_are_blocked(self):
        for route in ['/v1/automation/events/original/replay','/v1/automation/events/replay-batch',
                '/v1/automation/sync/promote-backfill','/v1/automation/workflows/reload',
                '/v1/automation/desired-state/apply','/v1/integrations/zoho/request',
                '/v1/automation/runs/old/redrive','/v1/site-and-password/webhooks/zoho','/v1/omada/jobs']:
            with self.subTest(route=route):
                self.assertEqual(self.client.post(route,headers=self.auth,json={}).status_code,403)

    def test_capacity_db_failures_and_lifecycle_body_bound(self):
        with patch.object(self.api,'intake_hold_policy',replace(self.policy,max_database_bytes=1)):
            r=self.client.post('/v1/automation/events',headers=self.auth,json=self.event().model_dump())
            self.assertEqual(r.status_code,503)
            self.assertEqual(r.headers['retry-after'],'30')
        with patch.object(self.store,'_connect',side_effect=sqlite3.OperationalError('FIXTURE-SECRET')):
            r=self.client.post('/v1/automation/events',headers=self.auth,json=self.event().model_dump())
            self.assertEqual(r.status_code,503);self.assertNotIn('FIXTURE-SECRET',r.text)
        for route in ['/v1/automation/events','/v1/lifecycle/leads','/v1/lifecycle/emails','/v1/lifecycle/meetings']:
            self.assertEqual(self.client.post(route,headers=self.auth,content=b' '*1_048_577).status_code,413)
        self.assertEqual(self.rows('automation_events'),[])

    def test_lifecycle_intake_is_capture_only(self):
        requests=[('/v1/lifecycle/leads',{'source':'fixture','email':'fixture@example.invalid','inquiry_id':'original'}),
                  ('/v1/lifecycle/emails',{'source':'fixture','subject':'fixture','sender_email':'fixture@example.invalid',
                    'mailbox_account_id':'fixture','mailbox_address':'fixture@example.invalid','message_id':'original','body':'fixture'}),
                  ('/v1/lifecycle/meetings',{'title':'fixture','start_datetime':'2026-10-28T12:00:00Z','end_datetime':'2026-10-28T13:00:00Z'})]
        with patch.object(self.api.automation_engine,'ingest',side_effect=AssertionError('No execution')):
            for route,payload in requests:
                with self.subTest(route=route):
                    result=self.client.post(route,headers=self.auth,json=payload)
                    self.assertEqual(result.status_code,202,result.text)
                    self.assertTrue(result.json()['held'])
        self.assertEqual(self.rows('automation_runs'),[])

    def test_signature_validation_and_durable_webhook_response(self):
        endpoint=WebhookEndpoint(provider='github',source_account='fixture',secret_env='FIXTURE_SIGNATURE',
            allowed_event_types=['github.push'],enabled=True)
        raw=b'{"repository":{"id":123}}';secret='fixture-signing-secret-'*2
        headers={'content-type':'application/json','x-github-delivery':str(uuid4()),'x-github-event':'push',
                 'x-hub-signature-256':'sha256='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()}
        with patch('workflow.automation.event_api.load_endpoints',return_value={'fixture':endpoint}), patch.dict(os.environ,{'FIXTURE_SIGNATURE':secret}):
            self.assertEqual(self.client.post('/v1/automation/webhooks/fixture',content=raw,headers={**headers,'x-hub-signature-256':'wrong'}).status_code,401)
            result=self.client.post('/v1/automation/webhooks/fixture',content=raw,headers=headers)
            self.assertEqual(result.status_code,202);self.assertTrue(result.json()['durable'] and result.json()['held'])
            duplicate=self.client.post('/v1/automation/webhooks/fixture',content=raw,headers=headers).json()
            self.assertTrue(duplicate['duplicate']);self.assertEqual(duplicate['event_id'],result.json()['event_id'])
        self.assertEqual(self.rows('automation_runs'),[])
