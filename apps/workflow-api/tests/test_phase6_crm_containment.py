"""Release-wide CRM control; fake transport and advisory AI only."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from workflow.automation.crm_write_boundary import POLICY,reviewed_reconciler_call,require_authority,LEGACY_ACTIONS
from workflow.automation.engine import AutomationEngine
from workflow.automation.models import WorkflowStep
from workflow.automation.store import AutomationStore
from workflow.automation.providers.lifecycle import register_lifecycle_actions
from workflow.automation.providers.lifecycle_extended import register_lifecycle_extended_actions
from workflow.automation.providers.lifecycle_phase2 import register_lifecycle_phase2_actions
from workflow.automation.providers.zoho import register_zoho_actions
from workflow.config import ZohoGatewaySettings
from workflow.zoho_gateway import ZohoGatewayClient

class CRMContainmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=AutomationStore(Path(self.tmp.name)/'state.db');self.engine=AutomationEngine(self.store,Path(self.tmp.name)/'defs')
        self.provider=Mock();self.ai=Mock()
        register_lifecycle_actions(self.engine,self.provider,self.store)
        register_lifecycle_extended_actions(self.engine,self.provider,self.ai,self.store)
        register_lifecycle_phase2_actions(self.engine,self.provider,self.ai,self.store)
        register_zoho_actions(self.engine,self.provider,self.store)
        self.body={'data':[{'id':'123','Normalized_Phone':'5145550100'}],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}
        self.headers={'If-Unmodified-Since':'2026-09-28T18:00:00+00:00'}
    def test_all_legacy_actions_refuse_before_provider_with_missing_malformed_or_claimed_approval(self):
        for action in LEGACY_ACTIONS:
            for inputs in ({},{'lead':None},{'lead':{},'qualification':{'promotion_allowed':True},'approved_to_send':True,'approval_id':'human','policy':POLICY}):
                with self.subTest(action=action,inputs=inputs),self.assertRaises(ValueError):
                    self.engine._actions[action]({},WorkflowStep(id='step',action=action,inputs=inputs))
        self.provider.request.assert_not_called()
    def test_flags_cannot_enable_legacy_promotion(self):
        for flag in ('','phase5-lead-v1',POLICY):
            with self.subTest(flag=flag),patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':flag}),self.assertRaises(ValueError):
                self.engine._actions['lifecycle.crm_promote_lead']({},WorkflowStep(id='s',action='lifecycle.crm_promote_lead',inputs={'lead':{},'qualification':{'promotion_allowed':True}}))
        self.provider.request.assert_not_called()
    def test_advisory_ai_still_classifies_without_provider(self):
        self.ai.generate.return_value={'text':'{"qualified":true,"confidence":0.99}','provider':'fake'}
        result=self.engine._actions['lifecycle.qualify_lead']({},WorkflowStep(id='s',action='lifecycle.qualify_lead',inputs={'lead':{'email':'fixture@example.test'}}))
        self.assertTrue(result['qualified']);self.provider.request.assert_not_called()
    def test_generic_automation_action_cannot_bypass_with_confirm(self):
        for module in ('Accounts','Contacts','Deals','Leads','Tasks','settings/fields','Leads/123/actions/convert'):
            with self.subTest(module=module),self.assertRaises(ValueError):
                self.engine._actions['zoho.request']({},WorkflowStep(id='s',action='zoho.request',inputs={'service':'zohoapis','method':'POST','path':'/crm/v8/'+module,'reason':'human approved','confirm':True}))
        self.provider.request.assert_not_called()
    def test_gateway_direct_and_standby_fail_before_oauth_or_transport(self):
        oauth=Mock();gateway=ZohoGatewayClient(ZohoGatewaySettings(base_url="",api_key="",timeout_seconds=60,standby_enabled=True),oauth)
        for path in ('/crm/v8/Accounts','/crm/v8/Contacts','/crm/v8/Deals','/crm/v8/Tasks','/crm/v8/Leads','/crm/v8/settings/fields','/crm/v8/Leads/123/actions/convert'):
            for method in ('POST','PUT','PATCH','DELETE'):
                with self.subTest(path=path,method=method),self.assertRaises(ValueError):gateway.request('zohoapis',method,path,body={},reason='approved',confirm=True)
        oauth.status.assert_not_called();oauth.access_token.assert_not_called()
    def test_path_escape_and_method_override_cannot_widen_crm_authority(self):
        gateway=ZohoGatewayClient(ZohoGatewaySettings(base_url="",api_key="",timeout_seconds=60,standby_enabled=False),Mock())
        for path in ('/crm%2fv8/Accounts','/creator/../crm/v8/Deals','/crm/v8/Accounts?x=y','/crm/v8/Accounts#fragment','/CRM/v8/Accounts'):
            with self.subTest(path=path),self.assertRaises(ValueError):gateway.request('zohoapis','POST',path,body={},reason='approved',confirm=True)
    def test_exact_reconciler_grant_is_single_use_and_reset_after_scope(self):
        client=object()
        with patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':POLICY}):
            with reviewed_reconciler_call(client,'PUT','/crm/v8/Leads/123',self.body,self.headers,POLICY):
                require_authority(client,'zohoapis','PUT','/crm/v8/Leads/123',self.body,self.headers)
                with self.assertRaises(ValueError):require_authority(client,'zohoapis','PUT','/crm/v8/Leads/123',self.body,self.headers)
            with self.assertRaises(ValueError):require_authority(client,'zohoapis','PUT','/crm/v8/Leads/123',self.body,self.headers)
    def test_grant_rejects_owner_accounts_extra_fields_and_wrong_policy(self):
        client=object()
        with patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':POLICY}):
            for name,value in (('Owner','123'),('Email','changed@example.test'),('Lead_Status','Converted')):
                body={**self.body,'data':[{**self.body['data'][0],name:value}]}
                with self.subTest(field=name),self.assertRaises(ValueError):
                    with reviewed_reconciler_call(client,'PUT','/crm/v8/Leads/123',body,self.headers,POLICY):pass
            with self.assertRaises(ValueError):
                with reviewed_reconciler_call(client,'POST','/crm/v8/Accounts',self.body,self.headers,POLICY):pass
    def test_policy_change_before_transport_refuses(self):
        client=object()
        with patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':POLICY}):
            with reviewed_reconciler_call(client,'PUT','/crm/v8/Leads/123',self.body,self.headers,POLICY):
                os.environ['OPTIBRAIN_CRM_LEAD_WRITES']='observe'
                with self.assertRaises(ValueError):require_authority(client,'zohoapis','PUT','/crm/v8/Leads/123',self.body,self.headers)
    def test_grant_body_version_and_client_cannot_be_swapped(self):
        client=object()
        with patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':POLICY}):
            with reviewed_reconciler_call(client,'PUT','/crm/v8/Leads/123',self.body,self.headers,POLICY):
                for other,body,headers in ((object(),self.body,self.headers),(client,{},self.headers),(client,self.body,{'If-Unmodified-Since':'2026-09-29T00:00:00Z'})):
                    with self.subTest(other=id(other)),self.assertRaises(ValueError):require_authority(other,'zohoapis','PUT','/crm/v8/Leads/123',body,headers)
    def test_approved_crm_transport_loss_never_falls_back_or_reuses_grant(self):
        import httpx
        from workflow.zoho_gateway import ZohoWriteUnconfirmedError
        oauth=Mock();oauth.status.return_value.configured=True;oauth.status.return_value.connected=True
        gateway=ZohoGatewayClient(ZohoGatewaySettings(base_url='https://connect.example.test',api_key='fake',timeout_seconds=60,standby_enabled=True),oauth)
        with patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':POLICY}),patch.object(gateway,'_local_request',side_effect=httpx.ReadTimeout('fixture loss')) as local,patch.object(gateway,'_standby_request') as standby:
            with reviewed_reconciler_call(gateway,'PUT','/crm/v8/Leads/123',self.body,self.headers,POLICY):
                with self.assertRaises(ZohoWriteUnconfirmedError):gateway.request('zohoapis','PUT','/crm/v8/Leads/123',body=self.body,headers=self.headers,reason='reviewed',confirm=True)
                with self.assertRaises(ValueError):gateway.request('zohoapis','PUT','/crm/v8/Leads/123',body=self.body,headers=self.headers,reason='reviewed',confirm=True)
            local.assert_called_once();standby.assert_not_called()
    def test_policy_change_during_oauth_prevents_transport(self):
        oauth=Mock();oauth.status.return_value.configured=True;oauth.status.return_value.connected=True
        def token():
            os.environ['OPTIBRAIN_CRM_LEAD_WRITES']='observe'
            return 'fake-token'
        oauth.access_token.side_effect=token
        gateway=ZohoGatewayClient(ZohoGatewaySettings(base_url='',api_key='',timeout_seconds=60,standby_enabled=True),oauth)
        with patch.dict(os.environ,{'OPTIBRAIN_CRM_LEAD_WRITES':POLICY}),patch.object(gateway,'_local_request') as local,patch.object(gateway,'_standby_request') as standby:
            with reviewed_reconciler_call(gateway,'PUT','/crm/v8/Leads/123',self.body,self.headers,POLICY),self.assertRaises(ValueError):
                gateway.request('zohoapis','PUT','/crm/v8/Leads/123',body=self.body,headers=self.headers,reason='reviewed',confirm=True)
            local.assert_not_called();standby.assert_not_called()
    def test_generic_encoded_or_traversal_paths_refuse_before_adapter(self):
        for path in ('/crm%2fv8/Accounts','/creator/../crm/v8/Deals','/crm/v8/Contacts?override=x'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                self.engine._actions['zoho.request']({},WorkflowStep(id='s',action='zoho.request',inputs={'service':'zohoapis','method':'POST','path':path,'reason':'approved','confirm':True}))
        self.provider.request.assert_not_called()
    def test_api_intake_and_old_promotion_event_cannot_reach_provider(self):
        import yaml
        from fastapi.testclient import TestClient
        from workflow import api
        from workflow.automation.models import WorkflowDefinition
        source=Path(__file__).resolve().parents[1]/'config/automation/workflows/customer-lifecycle-lead-intake.yaml'
        self.store.upsert_workflow(WorkflowDefinition.model_validate(yaml.safe_load(source.read_text())))
        # A deliberately old/custom active snapshot must also fail at the action boundary.
        old=WorkflowDefinition.model_validate({'id':'old.promotion','name':'Old snapshot','trigger':{'event_types':['fixture.old.promotion']},'steps':[{'id':'promote','action':'lifecycle.crm_promote_lead','with':{'lead':{'email':'fixture@example.test'},'qualification':{'promotion_allowed':True,'confidence':1}}}]})
        self.store.upsert_workflow(old)
        with patch.object(api,'automation_engine',self.engine),patch.dict(os.environ,{api.settings.api.api_key_env:'fixture-key'}):
            os.environ.pop('OPTIBRAIN_CRM_LEAD_WRITES',None)
            client=TestClient(api.app)
            headers={'X-API-Key':'fixture-key'}
            response=client.post('/v1/lifecycle/leads',headers=headers,json={'source':'fixture','email':'fixture@example.test'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['accepted']);self.assertEqual(response.json()['run_ids'],[])
            response=client.post('/v1/automation/events',headers=headers,json={'event_type':'fixture.old.promotion','source':'fixture','payload':{}})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.store.get_run(response.json()['run_ids'][0])['status'],'failed')
        self.provider.request.assert_not_called();self.ai.generate.assert_not_called()
    def test_method_override_headers_are_blocked_before_oauth(self):
        oauth=Mock();gateway=ZohoGatewayClient(ZohoGatewaySettings(base_url='',api_key='',timeout_seconds=60,standby_enabled=True),oauth)
        for header in ('X-HTTP-Method-Override','X-Method-Override'):
            with self.subTest(header=header),self.assertRaises(ValueError):gateway.request('zohoapis','GET','/crm/v8/Accounts',headers={header:'POST'})
        oauth.status.assert_not_called()
