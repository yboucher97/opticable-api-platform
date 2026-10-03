import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation import lifecycle_control as lc, real_internal as ri
from workflow.automation.remote_effects import FreshClaim
from workflow.automation.today import build_today

NOW=datetime.now(timezone.utc).replace(microsecond=0)
ACT=(NOW-timedelta(hours=1)).isoformat()
RUN='real-family-fixture'

def timeline(source='crm_ui',at=None,actor=ri.OWNER,field='Lead_Status',new='Pre-Qualified',module='Leads'):
    return {'id':'t1','record':{'id':'101','module':{'api_name':module}},'audited_time':at or NOW.isoformat(),
        'source':source,'done_by':{'id':actor},'field_history':[{'api_name':field,'_value':{'old':'Not Contacted','new':new}}]}

def receipt(at=None):
    body={'name':'Alice Example','email':'alice@customer.test','phone':'5145552222','company':'Customer Company','service':'Structured Cabling','message':'A new internal inquiry','consent':True}
    return {'schema':1,'source':'ai_website','origin':'https://ai.opticable.ca','inquiry_id':'new-inquiry-1','request':body,'payload_hash':lc.digest(body),'request_hash':lc.digest(body),'occurred_at':at or NOW.isoformat(),'submitted_email':body['email']}

class RealPlanningTests(unittest.TestCase):
    def test_native_conversion_result_requires_qualified_identity(self):
        lead={'Email':'alice@customer.test','Company':'Customer Company'}
        ri.verify_conversion_identity('Contacts',{'Email':'ALICE@customer.test'},lead)
        ri.verify_conversion_identity('Accounts',{'Account_Name':'Customer Company'},lead)
        for module,record in [('Contacts',{'Email':'someone@customer.test'}),('Accounts',{'Account_Name':'Another Company'})]:
            with self.subTest(module=module),self.assertRaises(ri.UnsafeOutcome):ri.verify_conversion_identity(module,record,lead)
    def test_form_scope_uses_parser_identity_not_user_message_words(self):
        from workflow.automation.phase9_form_receipts import MAIN_FORM,ENGLISH_FORM
        self.assertTrue(ri.approved_form({'form_id':MAIN_FORM,'test_only':False}))
        self.assertFalse(ri.approved_form({'form_id':ENGLISH_FORM,'test_only':False,'notes':'Courriel'}))
        self.assertFalse(ri.approved_form({'form_id':MAIN_FORM,'test_only':True}))
    def test_native_conversion_carries_click_ids_context_and_touch_without_pricing(self):
        context={'Company':'Customer Company','Last_Name':'Example','Service_Types':'CCTV','Description':'Scope for human review','Inquiry_ID':'new-1',
            'First_Campaign':'original','Last_Campaign':'returning','Google_GCLID':'safe-click','Google_GBRAID':'safe-braid','Google_WBRAID':'safe-wbraid','Meta_FBCLID':'safe-meta'}
        deal=ri.conversion_deal(context,NOW)
        for k,v in context.items():
            if k not in {'Company','Last_Name'}:self.assertEqual(deal[k],v)
        self.assertNotIn('Amount',deal);self.assertNotIn('OptiBrain_Test',deal)
    def test_latest_owner_ui_qualification_only(self):
        lead={'id':'101','Lead_Status':'Pre-Qualified','Email':'alice@customer.test'}
        self.assertTrue(ri.human_qualification(lead,[timeline()],ACT))
        for rows in ([timeline('crm_api')],[timeline('workflow')],[timeline(actor='other')],[timeline(at=(NOW-timedelta(hours=2)).isoformat())],
                     [timeline(at=(NOW-timedelta(minutes=1)).isoformat()),timeline('crm_api')],[]):
            with self.subTest(rows=rows):self.assertFalse(ri.human_qualification(lead,rows,ACT))
    def test_other_record_and_module_cannot_qualify(self):
        lead={'id':'102','Lead_Status':'Pre-Qualified'}
        self.assertFalse(ri.human_qualification(lead,[timeline()],ACT))
        self.assertFalse(ri.human_qualification({'id':'101','Lead_Status':'Pre-Qualified'},[timeline(module='Contacts')],ACT))
    def test_test_marking_never_qualifies(self):
        for value in ({'OptiBrain_Test':True},{'Company':'OPTIBRAIN TEST — PHASE 16'},{'Email':'logs@opticable.ca'}):
            self.assertFalse(ri.human_qualification({'id':'101','Lead_Status':'Pre-Qualified',**value},[timeline()],ACT))
    def test_completion_requires_human_ui(self):
        r={'id':'101','Installation_Status':'Completed'}
        self.assertTrue(ri.human_transition(r,[timeline(field='Installation_Status',new='Completed',module='Installations')],ACT,'Installations','Installation_Status','Completed'))
        self.assertFalse(ri.human_transition(r,[timeline('crm_api',field='Installation_Status',new='Completed',module='Installations')],ACT,'Installations','Installation_Status','Completed'))
    def test_implicit_native_name_match_is_human(self):
        lead={'Email':'alice@customer.test','First_Name':'Alice','Last_Name':'Example','Company':'Customer Company'}
        contact={'id':'9','Email':'someone@customer.test','First_Name':'Alice','Last_Name':'Example'}
        with self.assertRaises(ri.HumanAttention):ri.safe_conversion_references(lead,[],[contact],set())
    def test_protected_customer_reference_denied(self):
        lead={'Email':'alice@customer.test','First_Name':'Alice','Last_Name':'Example','Company':'Customer Company'}
        a={'id':'9','Account_Name':'Customer Company'}
        with self.assertRaises(ri.HumanAttention):ri.safe_conversion_references(lead,[a],[],{'9'})
    def test_exact_contact_account_reuse_and_company_mismatch(self):
        l={'Email':'alice@customer.test','First_Name':'Alice','Last_Name':'Example','Company':'Customer Company'}
        a={'id':'9','Account_Name':'Customer Company'};c={'id':'8','Email':l['Email'],'First_Name':'Alice','Last_Name':'Example','Account_Name':{'id':'9'}}
        self.assertEqual(ri.safe_conversion_references(l,[a],[c],set()),(a,c))
        with self.assertRaises(ri.HumanAttention):ri.safe_conversion_references({**l,'Company':'Other company'},[a],[c],set())
    def test_exact_address_format_variation_reuses_existing_site(self):
        addr={'street':'123 Main Street','unit':'Unit 1','city':'Montreal','province':'QC','postal_code':'H1A1A1','country':'Canada'}
        existing={'id':'7','Linked_Account':{'id':'9'},**ri.site_fields({**addr,'street':'123 Main St','unit':'1','city':'Montréal'})}
        self.assertEqual(ri.safe_site_match([existing],'9',addr)['decision'],'REUSE')
    def test_scopes_exclude_all_external_and_financial_operations(self):
        for name in ('mail.test.send','sign.test.send','sign.contract.prepare','books.write','crm.case.create','*'):
            self.assertNotIn(name,lc.REAL_SCOPES)
    def test_today_root_projection_links_crm_and_excludes_tests(self):
        model={'scope':'live','read_only':True,'state':'READY','at':NOW.isoformat(),'attention':[
            {'context':'Accepted work','module':'Deals','identity':'123','why':'Ready','next_action':'Schedule'},
            {'context':'OPTIBRAIN TEST Company','module':'Deals','identity':'124'}]}
        view=build_today({}, {}, {}, {}, {'signals':[]},now=NOW,internal=model)
        self.assertEqual(view['attention_count'],1)
        self.assertIn('org763070937/tab/Deals/123',view['sections']['Projects and install work'][0]['link'])

class FakeRemote:
    def __init__(self):self.claims={};self.results={}
    def claim(self,e):
        fresh=e.action_id not in self.claims;self.claims[e.action_id]=e.payload_hash
        return FreshClaim(e.action_id,e.payload_hash,'business-effects/v1/'+e.action_id+'/claim.json',fresh)
    def complete(self,e,id):self.results[e.action_id]=str(id)

class FakeProvider:
    def __init__(self):self.records={};self.mutations=0;self.lose_ack=False
    def request(self,service,method,path,query=None,headers=None,body=None,**kwargs):
        if method=='GET':
            module=path.split('/')[3]
            if path.split('/')[-1].isdigit():return {'data':{'data':[self.records[path.split('/')[-1]]]},'ok':True}
            return {'data':{'data':[r for r in self.records.values() if r['_module']==module],'info':{'more_records':False}},'ok':True}
        lc.check_transport(self,service,method,path,body,headers or {})
        lc.check_transport(self,service,method,path,body,headers or {},recheck=True)
        self.mutations+=1
        if self.lose_ack:raise TimeoutError('Provider outcome intentionally uncertain')
        row=copy.deepcopy(body['data'][0]);id=row['id'] if method=='PUT' else str(101+self.mutations)
        if method=='PUT':
            if headers['If-Unmodified-Since']!=self.records[id]['Modified_Time']:raise ValueError('Stale provider version')
            row={**self.records[id],**row}
        row.update(id=id,Created_Time=NOW.isoformat(),Modified_Time=NOW.isoformat(),_module=path.split('/')[3]);self.records[id]=row
        return {'data':{'data':[{'code':'SUCCESS','details':{'id':id}}]},'ok':True}

class RealAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.client=FakeProvider();self.remote=FakeRemote()
        self.policy={'enabled':True,'test_scopes':[],'real_scopes':sorted(lc.REAL_SCOPES),'test_run':RUN,'activated_at':ACT,'approved_sources':['ai_website'],'expires_at':(NOW+timedelta(days=30)).isoformat()}
        self.patches=[patch.object(ri,'ROOT',self.root),patch.object(lc,'REAL_ROOT',self.root),patch.object(lc,'REAL_REGISTRY',self.root/'ownership.json'),patch.object(lc,'read_policy',return_value=self.policy),patch.object(ri.os,'geteuid',return_value=0),patch.object(lc,'trusted_json',side_effect=self.read),patch.object(lc,'LifecycleJournal',return_value=lc.LifecycleJournal(self.root/'journal.db')),patch('workflow.automation.remote_effects.RemoteEffects.root_store',return_value=self.remote)]
        for p in self.patches:p.start()
    def read(self,path,*args):
        if path==lc.BASELINE:return {'modules':{'Leads':{'protected_versions':{'999':'v1'}}}}
        return json.loads(path.read_text())
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def engine(self,dry=False):return ri.Engine(self.client,dry_run=dry)
    def source(self,e):e.trigger({'kind':'intake','source':'ai_website','occurred_at':NOW.isoformat(),'receipt':receipt()})
    def test_real_intake_one_task_and_replay_no_effect(self):
        e=self.engine();e.intakes([receipt()]);self.assertEqual(self.client.mutations,2)
        e.intakes([receipt()]);self.assertEqual(self.client.mutations,2)
        self.assertEqual(len(e.state['leads']),1);self.assertEqual(len(self.remote.claims),2)
    def test_dry_run_is_provider_read_only(self):
        e=self.engine(True);e.intakes([receipt()]);self.assertEqual(self.client.mutations,0);self.assertEqual(len(e.plans),1)
        self.assertFalse((self.root/'ownership.json').exists());self.assertFalse((self.root/'authorizations').exists())
    def test_returning_inquiry_without_phone_preserves_normalized_identity(self):
        e=self.engine();e.intakes([receipt()]);id=next(iter(e.state['leads']));before=self.client.records[id]['Normalized_Phone']
        r=receipt();r['inquiry_id']='new-inquiry-2';r['request'].pop('phone');r['payload_hash']=lc.digest(r['request'])
        e.intakes([r]);self.assertEqual(self.client.records[id]['Normalized_Phone'],before)
        self.assertEqual(self.client.mutations,3);self.assertEqual(len(e.state['leads']),1)
    def test_root_source_hash_and_policy_revocation_are_checked(self):
        e=self.engine();e.intakes([receipt()]);key='intake:new-inquiry-1';row=e.state['effects'][key]
        effect=lc.LifecycleEffect(RUN+':'+key,row['envelope'])
        lc.check_real_effect(effect,'crm.lead.intake',RUN)
        auth=json.loads((self.root/'authorizations'/(effect.action_id+'.json')).read_text())
        source=self.root/'sources'/(auth['source_key']+'.json');value=json.loads(source.read_text());value['receipt']['submitted_email']='changed@customer.test';source.write_text(json.dumps(value))
        with self.assertRaises(ValueError):lc.check_real_effect(effect,'crm.lead.intake',RUN)
        self.policy['real_scopes']=[]
        with self.assertRaises(ValueError):lc.check_real_effect(effect,'crm.lead.intake',RUN)
    def test_old_receipt_skipped_without_new_payload_schema(self):
        e=self.engine();e.intakes([{'occurred_at':(NOW-timedelta(hours=2)).isoformat()}]);self.assertEqual(self.client.mutations,0)
    def test_test_and_protected_identity_are_never_written(self):
        e=self.engine();r=receipt();r['request']['email']='logs@opticable.ca';r['submitted_email']='logs@opticable.ca';r['payload_hash']=lc.digest(r['request']);e.intakes([r])
        self.assertEqual(self.client.mutations,0)
        self.client.records['999']={'id':'999','_module':'Leads','Email':'alice@customer.test','Phone':'','Created_Time':ACT}
        e.intakes([receipt()]);self.assertEqual(self.client.mutations,0);self.assertTrue(e.state['attention'])
    def test_existing_offhost_claim_and_state_loss_stop_writes(self):
        e=self.engine();self.source(e);row={'Last_Name':'Example','Email':'alice@customer.test'}
        body={'data':[row],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}
        effect=lc.LifecycleEffect(RUN+':create',{'service':'zohoapis','method':'POST','path':'/crm/v8/Leads','body':body,'headers':{},'content_type':'application/json','query':{}})
        self.remote.claim(effect)
        with self.assertRaises(ri.UnsafeOutcome):e.create('create','Leads',row)
        self.assertEqual(self.client.mutations,0);self.assertTrue((self.root/'HOLD.json').exists())
    def test_lost_ack_cannot_be_retried(self):
        e=self.engine();self.source(e);self.client.lose_ack=True
        with self.assertRaises(ri.UnsafeOutcome):e.create('create','Leads',{'Last_Name':'Example','Email':'alice@customer.test'})
        with self.assertRaises(ri.UnsafeOutcome):e.create('create','Leads',{'Last_Name':'Example','Email':'alice@customer.test'})
        self.assertEqual(self.client.mutations,1)
    def test_journal_alone_cannot_authorize_real_transport(self):
        e=self.engine();self.source(e)
        effect=lc.LifecycleEffect('fake',{'service':'zohoapis','method':'POST','path':'/crm/v8/Leads','body':{'data':[{'Last_Name':'Example'}],'trigger':[]},'headers':{},'content_type':'application/json','query':{}})
        e.journal.intent(effect);e.journal.append(effect,'attempted',{})
        with lc.exact_call(self.client,effect,self.remote.claim(effect),e.journal,mode='REAL_NEW',run=RUN,scope='crm.lead.intake'):
            with self.assertRaises(FileNotFoundError):lc.check_transport(self.client,'zohoapis','POST',effect.payload['path'],effect.payload['body'],{})
    def test_old_customer_reference_is_read_only_and_protected_reference_denied(self):
        e=self.engine();self.source(e)
        e.register('Accounts',{'id':'200','Account_Name':'Customer Company','Created_Time':(NOW-timedelta(days=30)).isoformat()},reference=True)
        e.register('Deals',{'id':'201','Created_Time':NOW.isoformat()})
        lc.validate_request('zohoapis','PUT','/crm/v8/Deals/201',{'data':[{'id':'201','Account_Name':{'id':'200'}}],'trigger':[]},{'If-Unmodified-Since':NOW.isoformat()},'application/json',{},scope='crm.deal.prepare',mode='REAL_NEW',run=RUN)
        with self.assertRaises(ValueError):lc.validate_request('zohoapis','PUT','/crm/v8/Accounts/200',{'data':[{'id':'200','Main_Workdrive_Folder_ID':'abc'}],'trigger':[]},{'If-Unmodified-Since':NOW.isoformat()},'application/json',{},scope='crm.account.create',mode='REAL_NEW',run=RUN)
        with self.assertRaises(ri.UnsafeOutcome):e.register('Accounts',{'id':'999'},reference=True)
    def test_real_qualification_pricing_and_schedule_fields_denied(self):
        e=self.engine();self.source(e)
        for module,change in [('Leads',{'Lead_Status':'Pre-Qualified'}),('Deals',{'Amount':1}),('Installations',{'Scheduled_Date':NOW.isoformat()})]:
            with self.subTest(module=module),self.assertRaises(ValueError):lc.validate_request('zohoapis','POST','/crm/v8/'+module,{'data':[change],'trigger':[]},{},'application/json',{},scope=lc.MODULE_SCOPE[module],mode='REAL_NEW',run=RUN)
    def test_owner_task_completion_is_not_reopened(self):
        e=self.engine();self.source(e);e.register('Leads',{'id':'101','Created_Time':NOW.isoformat()})
        lead={'id':'101'};task=e.task('one','Leads',lead,'Review inquiry','Context');self.client.records[task['id']]['Status']='Completed'
        current=e.task('one','Leads',lead,'Review inquiry','Context')
        self.assertEqual(current['Status'],'Completed');self.assertEqual(self.client.mutations,1)
    def test_closed_deal_acceptance_cannot_create_operational_effects(self):
        e=self.engine();self.source(e)
        with self.assertRaises(ri.HumanAttention):e.accepted({'id':'201','Stage':'Closed Lost'},{'site_id':'301'}, {})
        self.assertEqual(self.client.mutations,0)
    def test_record_remarked_test_cannot_be_updated_as_real(self):
        e=self.engine();self.source(e)
        with self.assertRaises(ri.HumanAttention):e.update('changed','Leads',{'id':'101','OptiBrain_Test':True},{'Last_Name':'Changed'})
        self.assertEqual(self.client.mutations,0)
    def test_late_acceptance_never_rewinds_owner_deal_progression(self):
        e=self.engine();self.source(e)
        lineage={'site_id':'400','account_id':'200','contact_id':'300'}
        with patch.object(e,'list',side_effect=ri.HumanAttention('end of bounded test')),patch.object(e,'update') as update:
            for stage in ('Contracts In Progress','Contracts Signed','Scheduling','Installation','Installation Booked'):
                with self.subTest(stage=stage),self.assertRaises(ri.HumanAttention):
                    e.accepted({'id':'201','Stage':stage,'Service_Types':'Structured Cabling'},lineage,{})
            update.assert_not_called()
    def test_owner_service_suppression_stops_installation_preparation(self):
        e=self.engine();self.source(e)
        service={'id':'500','Linked_Service_Location':{'id':'400'},'Linked_Deal':{'id':'201'},'Service_Type':'Cabling Installation'}
        lineage={'site_id':'400','account_id':'200','contact_id':'300'}
        for stage in ('Cancelled','Suspended'):
            with self.subTest(stage=stage),patch.object(e,'list',return_value=[{**service,'Service_Stage':stage}]),self.assertRaises(ri.HumanAttention):
                e.accepted({'id':'201','Stage':'Contracts In Progress','Service_Types':'Structured Cabling'},lineage,{})
        self.assertEqual(self.client.mutations,0)
