"""Production transport gating, off-host replay protection and recovery evidence."""
import io,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import httpx
from workflow.automation.business_autonomy import Action,BusinessJournal,Policy,decide,dispatch,dispatch_approved
from workflow.automation.remote_effects import RemoteEffects,FreshClaim
from workflow.automation.mutation_control import action_scope,bind_task_claim,require_business_transport,technical_admin_call,require_technical_admin
from workflow.config import ZohoGatewaySettings
from workflow.zoho_gateway import ZohoGatewayClient,ZohoWriteUnconfirmedError

class ObjectError(Exception):
    def __init__(self,code):self.response={'Error':{'Code':code}}
class Objects:
    def __init__(self):self.rows={};self.uploads=0
    def put_object(self,**kw):
        assert kw['IfNoneMatch']=='*'
        if kw['Key'] in self.rows:raise ObjectError('PreconditionFailed')
        self.rows[kw['Key']]=kw['Body'];self.uploads+=1
    def get_object(self,**kw):
        if kw['Key'] not in self.rows:raise ObjectError('NoSuchKey')
        return {'Body':io.BytesIO(self.rows[kw['Key']])}

def action(key='phase13:task:fixture'):
    return Action('crm.task.create','Leads','501',key,{'Subject':'OPTIBRAIN TEST — PHASE 12 — Follow-up review Fixture','Status':'Not Started','Due_Date':'2026-10-02','purpose':'Internal follow-up review; no customer send'})

class Safety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.journal=BusinessJournal(Path(self.tmp.name)/'actions.db');self.action=action()
        self.policy=Policy(automatic_mutations=True,auto_test_task=True)
        self.body={'data':[{'Subject':'synthetic fixture'}],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}
        self.store=RemoteEffects(Objects());self.oauth=Mock()
        self.oauth.status.return_value=SimpleNamespace(configured=True,connected=True)
        self.oauth.access_token.return_value='fixture'
        self.client=ZohoGatewayClient(ZohoGatewaySettings(base_url='https://example.invalid',api_key='fixture',timeout_seconds=1,standby_enabled=True),self.oauth)
    def scope(self):return action_scope(self.action,self.journal,'TEST_ONLY')
    def attempted(self):
        self.journal.prepare(self.action,decide(self.action,'TEST_ONLY',self.policy))
        self.journal.transition(self.action.action_id,from_states=('proposed',),to='attempted',attempt=True)
        from datetime import datetime,timezone
        from workflow.automation.action_evidence import ActionEvidence,envelope
        now=datetime.now(timezone.utc);audit=ActionEvidence(self.journal.path)
        audit.plan(envelope(self.action.action_id,self.action.action_type,{'type':'Leads','identity':'501'},now,
            mutation=True,before_state={'id':'501','ownership':'TEST_ONLY'},proposed_state=self.action.payload,
            exact_versions={'payload_hash':self.action.payload_hash},authority_class='EXISTING_TEST_ONLY_POLICY',
            rollback_capability='COMPENSATING_ACTION_ONLY',consequence='Derived TEST Task',compensating_action='Owner reconciliation'),now)
        audit.start(self.action.action_id,now,authority_check=lambda:None)
    def test_legacy_attempt_without_universal_envelope_cannot_reach_transport(self):
        self.journal.prepare(self.action,decide(self.action,'TEST_ONLY',self.policy))
        self.journal.transition(self.action.action_id,from_states=('proposed',),to='attempted',attempt=True)
        claim=self.store.claim(self.action)
        with self.scope(),patch('workflow.automation.mutation_control.os.geteuid',return_value=0),patch('workflow.automation.mutation_control.read_control',return_value={'test_writes_enabled':True,'allowed_actions':['crm.task.create']}):
            bind_task_claim(self.action,self.client,self.body,claim)
            with self.assertRaises(ValueError):require_business_transport(self.client,'zohoapis','POST','/crm/v8/Tasks',self.body)
    def test_all_legacy_business_methods_deny_before_auth_even_with_flags_and_confirm(self):
        with patch.dict(os.environ,{'OPTIBRAIN_BUSINESS_AUTO_WRITES':'1','OPTIBRAIN_OUTBOUND_SENDS':'phase7-single-canary-v1'}),patch('workflow.automation.mutation_control.read_control',return_value={'test_writes_enabled':True}),patch('workflow.zoho_gateway.httpx.request') as transport:
            for service,path in [('mail','/api/accounts/1/messages'),('sign','/requests'),('forms','/api/v1/forms'),('projects','/api/v3/portal/1/projects/'),('zohoapis','/crm/v8/Tasks')]:
                for method in ['POST','PUT','PATCH','DELETE']:
                    with self.subTest(service=service,method=method),self.assertRaises(ValueError):
                        self.client.request(service,method,path,body={},reason='approved',confirm=True)
            self.oauth.status.assert_not_called();self.oauth.access_token.assert_not_called();transport.assert_not_called()
    def test_executable_get_and_overrides_deny_before_oauth(self):
        for path in ['/crm/v8/functions/x/actions/execute','/crm/v8/../functions/x','/crm%2fv8/Leads','/crm/v8/Leads?x=y']:
            with self.subTest(path=path),self.assertRaises(ValueError):self.client.request('zohoapis','GET',path)
        self.oauth.status.assert_not_called()
    def test_exact_central_transport_timeout_never_retries_and_is_reconstructable(self):
        self.attempted();claim=self.store.claim(self.action)
        with self.scope(),patch('workflow.automation.mutation_control.os.geteuid',return_value=0),patch('workflow.automation.mutation_control.read_control',return_value={'test_writes_enabled':True,'allowed_actions':['crm.task.create']}),patch('workflow.automation.crm_write_boundary.require_authority'),patch('workflow.automation.crm_write_boundary.verify_transport_authority'),patch.object(self.client,'_local_request',side_effect=httpx.ReadTimeout('uncertain')) as transport,patch.object(self.client,'_standby_request') as standby:
            bind_task_claim(self.action,self.client,self.body,claim)
            with self.assertRaises(ZohoWriteUnconfirmedError):self.client.request('zohoapis','POST','/crm/v8/Tasks',body=self.body,reason='TEST_ONLY',confirm=True)
            with self.assertRaises(ValueError):self.client.request('zohoapis','POST','/crm/v8/Tasks',body=self.body,reason='TEST_ONLY',confirm=True)
            transport.assert_called_once();standby.assert_not_called()
        proof=self.journal.reconstruction(self.action.action_id)
        self.assertEqual(proof['history_integrity'],'PASS')
        self.assertIn('transport_intent',[x['kind'] for x in proof['events']])
    def test_kill_during_oauth_stops_actual_transport(self):
        self.attempted();claim=self.store.claim(self.action);control={'test_writes_enabled':True,'allowed_actions':['crm.task.create']}
        self.oauth.access_token.side_effect=lambda: control.update(test_writes_enabled=False) or 'fixture'
        with self.scope(),patch('workflow.automation.mutation_control.os.geteuid',return_value=0),patch('workflow.automation.mutation_control.read_control',side_effect=lambda:control),patch('workflow.automation.crm_write_boundary.require_authority'),patch('workflow.automation.crm_write_boundary.verify_transport_authority'),patch.object(self.client,'_local_request') as transport,patch.object(self.client,'_standby_request') as standby:
            bind_task_claim(self.action,self.client,self.body,claim)
            with self.assertRaises(ValueError):self.client.request('zohoapis','POST','/crm/v8/Tasks',body=self.body,reason='TEST_ONLY',confirm=True)
            transport.assert_not_called();standby.assert_not_called()
    def test_payload_target_client_and_claim_cannot_be_substituted(self):
        self.attempted();claim=self.store.claim(self.action)
        with self.scope(),patch('workflow.automation.mutation_control.os.geteuid',return_value=0),patch('workflow.automation.mutation_control.read_control',return_value={'test_writes_enabled':True,'allowed_actions':['crm.task.create']}):
            bind_task_claim(self.action,self.client,self.body,claim)
            for client,path,body in [(object(),'/crm/v8/Tasks',self.body),(self.client,'/crm/v8/Leads',self.body),(self.client,'/crm/v8/Tasks',{})]:
                with self.assertRaises(ValueError):require_business_transport(client,'zohoapis','POST',path,body)
    def test_restore_or_deleted_local_journal_cannot_reacquire_offhost_claim(self):
        self.assertTrue(self.store.claim(self.action).fresh)
        self.store.complete(self.action,'700')
        recovered=BusinessJournal(Path(self.tmp.name)/'fresh.db')
        recovered.prepare(self.action,decide(self.action,'TEST_ONLY',self.policy))
        self.assertFalse(self.store.claim(self.action).fresh)
        self.assertEqual(self.store.get(self.action,'result')['provider_id'],'700')
        changed=Action('crm.task.create','Leads','502',self.action.request_key,self.action.payload)
        with self.assertRaises(ValueError):self.store.claim(changed)
    def test_uncertain_offhost_upload_never_grants_transport(self):
        self.store.client.put_object=Mock(side_effect=TimeoutError('committed maybe'))
        with self.assertRaises(ValueError):self.store.claim(self.action)
    def test_old_proposal_cannot_bypass_current_kill_and_approval_is_not_consumed(self):
        self.journal.prepare(self.action,decide(self.action,'TEST_ONLY',self.policy))
        execute=Mock()
        row=dispatch(self.action,ownership='TEST_ONLY',policy=Policy(),journal=self.journal,fresh=Mock(),execute=execute,reconcile=Mock())
        self.assertEqual(row['state'],'deferred');execute.assert_not_called()
        approved=Action('email.send','Leads','501','phase13:send:fixture',{'recipient':'fixture@example.invalid'})
        self.journal.prepare(approved,decide(approved,'TEST_ONLY',self.policy))
        with self.assertRaises(ValueError):dispatch_approved(approved,approval_id='0'*32,actor='human:fixture',journal=self.journal,fresh=Mock(),execute=execute,reconcile=Mock())
        self.assertEqual(self.journal.get(approved.action_id)['attempts'],0)
    def test_append_only_evidence_redacts_and_detects_tampering(self):
        self.attempted();self.journal.record_evidence(self.action.action_id,'fixture_response',{'access_token':'forbidden','status':200})
        proof=self.journal.reconstruction(self.action.action_id)
        self.assertNotIn('forbidden',json.dumps(proof));self.assertIn('[REDACTED]',json.dumps(proof))
        with sqlite3.connect(self.journal.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM action_evidence')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE action_envelopes SET envelope_json='{}'")
    def test_runtime_cannot_issue_root_technical_administration(self):
        with patch('workflow.automation.mutation_control.os.geteuid',return_value=1002):
            with self.assertRaises(ValueError):
                with technical_admin_call(self.client,'cloudflare','PUT','/resource',{}):pass
        with patch('workflow.automation.mutation_control.os.geteuid',return_value=0):
            from datetime import datetime,timezone
            from workflow.automation.action_evidence import ActionEvidence,envelope
            now=datetime.now(timezone.utc);audit=ActionEvidence(self.journal.path);aid='technical-audit-fixture-001'
            plan=envelope(aid,'TECHNICAL_CONFIG',{'type':'CONFIG','identity':'/resource'},now,provider='cloudflare',
                mutation=True,before_state={'exists':False},proposed_state={},rollback_capability='COMPENSATING_ACTION_ONLY',
                consequence='Technical object may exist',compensating_action='Owner reviewed cleanup',authority_class='EXPLICIT_TEST_FIXTURE')
            audit.plan(plan,now);audit.start(aid,now,authority_check=lambda:None)
            with self.assertRaises(ValueError):
                with technical_admin_call(self.client,'cloudflare','PUT','/resource',{}):pass
            with technical_admin_call(self.client,'cloudflare','PUT','/resource',{},audit=audit,action_id=aid):
                require_technical_admin(self.client,'cloudflare','PUT','/resource',{})
                with self.assertRaises(ValueError):require_technical_admin(self.client,'cloudflare','PUT','/resource',{})
    def test_production_api_authentication_is_fail_closed_and_url_keys_are_rejected(self):
        from fastapi.testclient import TestClient
        from workflow import api
        with patch.dict(os.environ,{},clear=True):
            client=TestClient(api.app)
            self.assertEqual(client.get('/v1/automation/workflows').status_code,503)
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(client.post('/webhooks/zoho/site-workflow',json={}).status_code,403)
            self.assertEqual(client.get('/jobs/fixture').status_code,403)
        with patch.dict(os.environ,{api.settings.api.api_key_env:'fixture-only-key'}):
            self.assertEqual(client.get('/v1/automation/workflows').status_code,401)
            self.assertEqual(client.get(api.ZOHO_OAUTH_STATUS_PATH,params={'api_key':'fixture-only-key'}).status_code,400)
    def test_books_write_denial_is_independent_of_control_flags(self):
        with patch('workflow.zoho_gateway.httpx.request') as transport:
            for path in ['/books/v3/invoices','/crm/v8/CustomModule5001']:
                for method in ['POST','PUT','PATCH','DELETE']:
                    with self.assertRaises(Exception):self.client.request('zohoapis',method,path,body={},reason='test',confirm=True)
            self.oauth.status.assert_not_called();transport.assert_not_called()
    def test_execution_context_is_durable_before_mutating_callback(self):
        def execute():
            proof=self.journal.reconstruction(self.action.action_id)
            detail=json.loads(proof['action']['detail_json'])
            self.assertEqual(detail['run_id'],'phase13:run:fixture')
            self.assertEqual(detail['source_trigger'],'phase13:trigger:fixture')
            self.assertIn('execution_context',[x['kind'] for x in proof['events']])
            return '700'
        row=dispatch(self.action,ownership='TEST_ONLY',policy=self.policy,journal=self.journal,
            fresh=lambda:{'id':'501','ownership':'TEST_ONLY'},execute=execute,reconcile=lambda:'700',
            run_id='phase13:run:fixture',source_trigger='phase13:trigger:fixture')
        self.assertEqual(row['state'],'succeeded')
    def test_locked_duplicate_claim_is_reconciliation_only(self):
        self.store.claim(self.action)
        self.store.client.put_object=Mock(side_effect=ObjectError('ObjectLockedByBucketPolicy'))
        self.assertFalse(self.store.claim(self.action).fresh)
