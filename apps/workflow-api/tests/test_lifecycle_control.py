import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from workflow.automation import lifecycle_control as lc
from workflow.automation.remote_effects import FreshClaim
from workflow.automation.mutation_control import require_business_transport
from workflow.automation.crm_write_boundary import require_authority, verify_transport_authority

RUN='phase16-20261002'

class LifecycleControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=lc.LifecycleJournal(Path(self.temp.name)/'actions.db')
        self.client=object()
        self.registry={'records':{'100':{'ownership':'TEST_ONLY','run':RUN,'module':'Leads'},
            '200':{'ownership':'TEST_ONLY','run':RUN,'module':'Accounts'},
            '300':{'ownership':'TEST_ONLY','run':RUN,'module':'WorkDrive'}}}
        self.baseline={'modules':{'Leads':{'protected_versions':{'999':'v1'}}}}
        self.policy={'test_scopes':list(lc.TEST_SCOPES),'real_scopes':[],'test_run':RUN}
        self.root=patch.object(lc.os,'geteuid',return_value=0);self.root.start()
        self.read=patch.object(lc,'trusted_json',side_effect=lambda p,*a:self.registry if p==lc.REGISTRY else self.baseline);self.read.start()
        self.control=patch.object(lc,'read_policy',return_value=self.policy);self.control.start()
    def tearDown(self):
        self.control.stop();self.read.stop();self.root.stop();self.temp.cleanup()
    def effect(self,body=None,path='/crm/v8/Tasks',method='POST',headers=None,service='zohoapis',content_type='application/json'):
        body=body or {'data':[{'Subject':lc.TEST_PREFIX+' internal task','What_Id':{'id':'100'},'$se_module':'Leads','Status':'Not Started','Due_Date':'2026-10-03','OptiBrain_Test':True}],'trigger':[]}
        return lc.LifecycleEffect('test:exact-call',dict(service=service,method=method,path=path,body=body,headers=headers or {},content_type=content_type,query={}))
    def grant(self,effect,scope='crm.internal.task',mode='TEST_ONLY',fresh=True):
        self.journal.intent(effect);self.journal.append(effect,'attempted',{})
        claim=FreshClaim(effect.action_id,effect.payload_hash,'business-effects/v1/test/claim.json',fresh)
        return lc.exact_call(self.client,effect,claim,self.journal,mode=mode,run=RUN,scope=scope)
    def invoke(self,effect,recheck=False):
        p=effect.payload
        return require_business_transport(self.client,p['service'],p['method'],p['path'],p['body'],p['headers'],recheck=recheck,content_type=p['content_type'],query=p['query'])
    def test_exact_grant_and_single_use(self):
        e=self.effect()
        with self.grant(e):
            require_authority(self.client,'zohoapis','POST',e.payload['path'],e.payload['body'],{})
            self.invoke(e)
            verify_transport_authority(self.client,'zohoapis','POST',e.payload['path'],e.payload['body'],{})
            self.invoke(e,True)
            with self.assertRaises(ValueError): self.invoke(e)
        with self.assertRaises(ValueError): self.invoke(e)
    def test_changed_payload_denied(self):
        e=self.effect()
        with self.grant(e):
            changed=self.effect();changed.payload['body']['data'][0]['Subject']='modified'
            with self.assertRaises(ValueError): self.invoke(changed)
    def test_protected_record_denied_even_if_falsely_registered(self):
        self.registry['records']['999']={'ownership':'TEST_ONLY','run':RUN,'module':'Leads'}
        e=self.effect();e.payload['body']['data'][0]['What_Id']['id']='999'
        with self.grant(e):
            with self.assertRaisesRegex(ValueError,'Protected'): self.invoke(e)
    def test_module_confusion_denied(self):
        e=self.effect();e.payload['body']['data'][0]['What_Id']['id']='200'
        with self.grant(e):
            with self.assertRaises(ValueError): self.invoke(e)
    def test_existing_offhost_claim_denied(self):
        with self.assertRaises(ValueError):
            with self.grant(self.effect(),fresh=False): pass
    def test_lost_local_state_cannot_resend(self):
        e=self.effect();self.journal.intent(e)
        with self.assertRaises(ValueError):
            with lc.exact_call(self.client,e,FreshClaim(e.action_id,e.payload_hash,'old',False),self.journal,mode='TEST_ONLY',run=RUN,scope='crm.internal.task'): pass
    def test_policy_revocation_between_validation_and_transport(self):
        e=self.effect()
        with self.grant(e):
            self.invoke(e);self.policy['test_scopes']=[]
            with self.assertRaises(ValueError): self.invoke(e,True)
    def test_non_root_denied(self):
        with patch.object(lc.os,'geteuid',return_value=1000):
            with self.assertRaises(ValueError):
                with self.grant(self.effect()): pass
    def test_real_scope_has_no_test_send_authority(self):
        body={'fromAddress':lc.RECIPIENT,'toAddress':lc.RECIPIENT,'subject':'[OPTIBRAIN TEST] fixture','content':'test','mailFormat':'plaintext'}
        with self.assertRaises(ValueError):lc.validate_request('mail','POST','/api/accounts/1083319000000008002/messages',body,{},'application/json',{},scope='mail.test.send',mode='REAL_NEW',run=RUN)
    def test_native_workflow_containment_cannot_enable_or_delete(self):
        body={'workflow_rules':[{'id':'123','status':{'active':False,'delete_schedule_action':False}}]}
        with patch.object(lc,'trusted_json',return_value={'run':RUN,'rule_ids':['123']}):
            def validate(value):
                lc.validate_request('zohoapis','PUT','/crm/v8/settings/automation/workflow_rules/123',value,{},'application/json',{},scope='crm.config.workflow_containment',mode='TEST_ONLY',run=RUN)
            validate(body)
            for status in ({'active':True,'delete_schedule_action':False},{'active':False,'delete_schedule_action':True}):
                with self.subTest(status=status),self.assertRaises(ValueError):validate({'workflow_rules':[{'id':'123','status':status}]})
    def test_external_test_recipient_and_cc_denied(self):
        body={'fromAddress':lc.RECIPIENT,'toAddress':lc.RECIPIENT,'subject':'[OPTIBRAIN TEST] fixture','content':'test','mailFormat':'plaintext'}
        for change in ({'toAddress':'customer@example.net'},{'ccAddress':'customer@example.net'},{'subject':'Customer reminder'}):
            with self.subTest(change=change),self.assertRaises(ValueError):lc.validate_request('mail','POST','/api/accounts/1083319000000008002/messages',{**body,**change},{},'application/json',{},scope='mail.test.send',mode='TEST_ONLY',run=RUN)
    def test_financial_delete_and_unreviewed_paths_denied(self):
        for path in ('/books/v3/invoices','/crm/v8/Quotes','/crm/v8/CustomModule5002','/workdrive/api/v1/files/300','/crm/v8/functions/execute'):
            with self.subTest(path=path),self.assertRaises(ValueError):lc.validate_request('zohoapis','DELETE',path,{}, {},'application/json',{},scope='crm.deal.prepare',mode='TEST_ONLY',run=RUN)
    def test_sign_preparation_cannot_quicksend(self):
        body={'data':json.dumps({'templates':{'request_name':'[OPTIBRAIN TEST] contract','actions':[{'recipient_email':lc.RECIPIENT}]}}),'is_quicksend':'true'}
        with self.assertRaises(ValueError):lc.validate_request('sign','POST','/templates/325018000000115001/createdocument',body,{},'application/x-www-form-urlencoded',{},scope='sign.contract.prepare',mode='TEST_ONLY',run=RUN)
    def test_sign_extra_recipient_and_reminders_denied(self):
        base={'templates':{'request_name':'[OPTIBRAIN TEST] contract','email_reminders':False,'actions':[{'recipient_email':lc.RECIPIENT,'action_type':'SIGN','role':'Signataire','verify_recipient':False}]}}
        for change in ('cc','second signer','reminders'):
            value=json.loads(json.dumps(base))
            if change=='cc':value['templates']['actions'][0]['cc_email']='customer@example.net'
            elif change=='second signer':value['templates']['actions'].append({'recipient_email':'customer@example.net'})
            else:value['templates']['email_reminders']=True
            with self.subTest(change=change),self.assertRaises(ValueError):
                lc.validate_request('sign','POST','/templates/325018000000115001/createdocument',{'data':json.dumps(value),'is_quicksend':'true'},{},'application/x-www-form-urlencoded',{},scope='sign.test.send',mode='TEST_ONLY',run=RUN)
    def test_workdrive_cannot_overwrite_upload_or_use_unowned_folder(self):
        body={'parent_id':'300','filename':'OPTIBRAIN_TEST_PHASE16_A.txt','content':lc.TEST_PREFIX+' synthetic'}
        lc.validate_request('zohoapis','POST','/workdrive/api/v1/upload',body,{'Accept':'application/vnd.api+json'},'multipart/form-data',{},scope='workdrive.file.create',mode='TEST_ONLY',run=RUN)
        for patch_body in ({'override-name-exist':'true'},{'parent_id':'999'},{'filename':'invoice.pdf'},{'content':'unowned business document'}):
            with self.subTest(change=patch_body),self.assertRaises(ValueError):
                lc.validate_request('zohoapis','POST','/workdrive/api/v1/upload',{**body,**patch_body},{'Accept':'application/vnd.api+json'},'multipart/form-data',{},scope='workdrive.file.create',mode='TEST_ONLY',run=RUN)
    def test_intents_and_evidence_immutable(self):
        e=self.effect();self.journal.intent(e);self.journal.append(e,'attempted',{})
        with self.journal.connect() as db:
            for statement in ('DELETE FROM lifecycle_intents','UPDATE lifecycle_intents SET payload_hash="other"','DELETE FROM lifecycle_evidence','UPDATE lifecycle_evidence SET kind="other"'):
                with self.subTest(statement=statement),self.assertRaises(sqlite3.IntegrityError):db.execute(statement)
    def test_idempotency_conflict_denied(self):
        e=self.effect();self.journal.intent(e)
        e.payload['body']['data'][0]['Subject']='different'
        with self.assertRaises(ValueError):self.journal.intent(e)
    def test_crm_workflows_and_notifications_denied(self):
        for change in ('trigger','notify'):
            e=replace(self.effect(),request_key='test:boundary-'+change)
            if change=='trigger':e.payload['body']['trigger']=['workflow']
            else:e.payload['body']['data'][0]['Send_Notification_Email']=True
            with self.subTest(change=change),self.grant(e),self.assertRaises(ValueError):self.invoke(e)
