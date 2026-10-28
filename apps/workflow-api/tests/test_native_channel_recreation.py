from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from workflow.automation.action_evidence import ActionEvidence, envelope, approval_binding
from workflow.automation.desired_journal import DesiredJournal, resource_key
from workflow.automation.desired_state import DesiredStateDocument
from workflow.automation.event_schema import digest
from workflow.automation import mutation_control
from workflow.automation.store import AutomationStore
from workflow.config import ZohoGatewaySettings
from workflow.zoho_gateway import ZohoGatewayClient
from test_phase5_notification import NativeFake

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('native_recreate', ROOT/'ops/phase5/recreate_expired_notification.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class NativeRecreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store = AutomationStore(Path(self.temp.name)/'automation.db')
        self.provider = NativeFake()
        oauth = Mock();oauth.status.return_value = types.SimpleNamespace(configured=True, connected=True)
        oauth.access_token.return_value = 'fixture-oauth-value'
        self.client = ZohoGatewayClient(ZohoGatewaySettings('https://example.invalid',None,30,False),oauth)
        def local(service,method,path,**kw):
            return self.provider.request(service,method,path,body=kw['body'])
        transport = patch.object(self.client,'_local_request',side_effect=local);transport.start();self.addCleanup(transport.stop)
        self.expiry=(datetime.now(timezone.utc)+timedelta(days=6)).replace(microsecond=0).isoformat()
        env=patch.dict(os.environ,{'OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT':'https://optibrain.opticable.ca/v1/automation/webhooks/phase5-crm-leads',
            'OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL':'fixture-native-channel-secret-32bytes',
            'OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY':self.expiry})
        env.start();self.addCleanup(env.stop)
        self.document=DesiredStateDocument.model_validate_json((ROOT/'apps/workflow-api/config/automation/desired-state/zoho-crm-notification.template.json').read_text())
        self.key=resource_key(self.document.resources[0])
        meta={'provider':'zoho_crm','kind':'notification','action':'update','native_expected':{'channel_id':recovery.CHANNEL,
              'expiry':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
              'configuration_hash':digest([os.environ['OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT'],os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL']])}}
        DesiredJournal(self.store).record('manual',self.key,meta,'historical-renewal')
        self.original=DesiredJournal(self.store).last(self.key,('manual',))

    @contextmanager
    def root_transport(self):
        # Only this module's privilege check is a fixture; real file ownership,
        # the actual gateway validation and the cross-process journal lock remain.
        fixture_os=Mock(wraps=os);fixture_os.geteuid.return_value=0
        with patch.object(mutation_control,'os',fixture_os):yield

    def proposal(self):
        return recovery.proposal(self.client,recovery.ReadOnlyStore(self.store.db_path),self.document,self.expiry)

    def approval(self):
        return {'approved':True,'phase':'CRM_NOTIFICATION_RECREATE_ONLY',
                'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()}

    def test_read_only_proposal_preserves_old_manual_and_requires_expired_absence(self):
        proposed=self.proposal()
        self.assertEqual(proposed['status'],'READY_FOR_APPROVAL')
        self.assertEqual(proposed['prior_intent_sha256'],digest(self.original))
        self.assertTrue(DesiredJournal(self.store).unresolved(self.key))
        self.assertEqual(DesiredJournal(self.store).last(self.key,('manual',)),self.original)
        self.assertFalse(self.provider.writes)
        bad=copy.deepcopy(self.original['metadata']);bad['native_expected']['expiry']=self.expiry
        DesiredJournal(self.store).record('manual',self.key,bad,'fixture-new-unresolved')
        with self.assertRaises(ValueError):self.proposal()

    def test_root_approved_recreation_uses_actual_gateway_once_without_relabeling_history(self):
        proposed=self.proposal()
        with self.root_transport():
            result=recovery.apply_approved(self.client,self.store,self.document,proposed,self.approval(),'a'*64)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(len(self.provider.writes),1)
        self.assertEqual(self.provider.writes[0][0],'POST')
        self.assertEqual(DesiredJournal(self.store).last(self.key,('manual',)),self.original)
        self.assertFalse(DesiredJournal(self.store).unresolved(self.key))
        saved=json.dumps(self.store.recent_audit())
        self.assertNotIn(os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL'],saved)
        with self.root_transport(),self.assertRaises(ValueError):
            recovery.apply_approved(self.client,self.store,self.document,proposed,self.approval(),'a'*64)
        self.assertEqual(len(self.provider.writes),1)

    def test_lost_ack_does_not_retry_and_new_unresolved_state_is_not_bypassed(self):
        proposed=self.proposal();self.provider.lose=True
        with self.root_transport():
            result=recovery.apply_approved(self.client,self.store,self.document,proposed,self.approval(),'b'*64)
        self.assertEqual(result['status'],'BLOCKED_MANUAL_NO_RETRY')
        self.assertEqual(len(self.provider.writes),1)
        self.assertTrue(DesiredJournal(self.store).unresolved(self.key))
        view=recovery.ReviewedExpiredJournal(self.store,self.key,proposed['prior_intent_sha256'])
        self.assertTrue(view.unresolved(self.key))
        self.assertTrue(view.unresolved('unrelated') is False)
        with self.root_transport(),self.assertRaises(ValueError):
            recovery.apply_approved(self.client,self.store,self.document,proposed,self.approval(),'c'*64)
        self.assertEqual(len(self.provider.writes),1)

    def test_runtime_cannot_acquire_config_authority_or_create_customer_records(self):
        with self.assertRaises(ValueError):
            self.client.request('zohoapis','POST',recovery.PATH,body={'watch':[]},confirm=True,reason='fixture')
        self.assertFalse(self.provider.writes)
        # No admin context can authorize Leads or Tasks, even with a valid native plan.
        now=datetime.now(timezone.utc);audit=ActionEvidence(self.store.db_path)
        body={'watch':[{'channel_id':recovery.CHANNEL,'events':['Leads.create','Leads.edit'],
            'notify_url':os.environ['OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT'],
            'token':os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL'],'channel_expiry':self.expiry,
            'notify_on_related_action':False,'return_affected_field_values':False}]}
        aid='fixture-native-admin'
        audit.plan(envelope(aid,'CONFIGURATION_CREATE',{'type':'CONFIGURATION','identity':recovery.PATH},now,
            provider='zoho_crm_notification',mutation=True,approval_required=True,approval_record=self.approval(),
            before_state={'exists':False},proposed_state=body,rollback_capability='COMPENSATING_ACTION_ONLY',
            consequence='New provider notifications enter durable hold',authority_class='OWNER_EXACT_NATIVE_CONFIGURATION',
            exact_versions={'owner_phase':'CRM_NOTIFICATION_RECREATE_ONLY','owner_approval_sha256':'e'*64},
            compensating_action='Keep intake and explicitly review subscription expiry'),now)
        audit.approve(aid,'fixture-owner',now,binding=approval_binding(audit.get(aid)),expires_at=self.approval()['expires_at'])
        audit.start(aid,now,authority_check=lambda:None)
        with self.assertRaises(ValueError),mutation_control.technical_admin_call(self.client,'zoho_crm_notification','POST',recovery.PATH,body,audit=audit,action_id=aid):pass
        with self.root_transport(),mutation_control.technical_admin_call(self.client,'zoho_crm_notification','POST',recovery.PATH,body,audit=audit,action_id=aid):
            for path in ['/crm/v8/Leads','/crm/v8/Tasks','/crm/v8/actions/watch/extra']:
                with self.assertRaises(ValueError):
                    self.client.request('zohoapis','POST',path,body={},confirm=True,reason='fixture-forbidden')
        self.assertFalse(self.provider.writes)

    def test_changed_prior_intent_or_scope_cannot_use_old_approval(self):
        proposed=self.proposal()
        altered=copy.deepcopy(self.original['metadata']);altered['result']={'status':'new-unresolved'}
        DesiredJournal(self.store).record('manual',self.key,altered,'later-intent')
        with self.root_transport(),self.assertRaises(ValueError):
            recovery.apply_approved(self.client,self.store,self.document,proposed,self.approval(),'d'*64)
        self.assertFalse(self.provider.writes)
