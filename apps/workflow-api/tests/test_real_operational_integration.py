import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation import lifecycle_control as lc, real_internal as ri
import test_real_internal as fixtures

NOW=datetime.now(timezone.utc).replace(microsecond=0)
ACT=(NOW-timedelta(hours=1)).isoformat()
RUN='operational-fixture'


def status_event(installation,status,*,source='crm_ui',actor=ri.OWNER,at=None,event_id='t1'):
    return {'id':event_id,'record':{'id':installation,'module':{'api_name':'Installations'}},
        'audited_time':at or NOW.isoformat(),'source':source,'done_by':{'id':actor},
        'field_history':[{'api_name':'Installation_Status','_value':{'old':'In Progress','new':status}}]}


class Provider(fixtures.FakeProvider):
    def __init__(self):
        super().__init__();self.timeline={};self.writes=[]
    def request(self,service,method,path,**kwargs):
        if method=='GET' and path.endswith('/__timeline'):
            return {'data':{'__timeline':self.timeline.get(path.split('/')[-2],[]),'info':{'more_records':False}}}
        if method=='GET' and '/workdrive/api/v1/files/' in path:
            identity=path.rsplit('/',1)[-1]
            return {'data':{'data':{'id':identity,'attributes':{'name':'Account','parent_id':'anchor'}}}}
        if method!='GET':self.writes.append((service,method,path,copy.deepcopy(kwargs.get('body'))))
        return super().request(service,method,path,**kwargs)


class RealOperationalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.client=Provider();self.remote=fixtures.FakeRemote()
        self.policy={'enabled':True,'test_scopes':[],'real_scopes':sorted(lc.REAL_SCOPES-{'crm.case.prepare'}),
            'test_run':RUN,'activated_at':ACT,'approved_sources':['ai_website'],'expires_at':(NOW+timedelta(days=30)).isoformat()}
        self.patches=[patch.object(ri,'ROOT',self.root),patch.object(lc,'REAL_ROOT',self.root),
            patch.object(lc,'REAL_REGISTRY',self.root/'ownership.json'),patch.object(lc,'read_policy',return_value=self.policy),
            patch.object(ri.os,'geteuid',return_value=0),patch.object(lc,'trusted_json',side_effect=self.read),
            patch.object(lc,'LifecycleJournal',return_value=lc.LifecycleJournal(self.root/'journal.db')),
            patch('workflow.automation.remote_effects.RemoteEffects.root_store',return_value=self.remote)]
        for p in self.patches:p.start()
        (self.root/'activation.json').write_text(json.dumps({'workdrive_parent':'anchor'}))
        self.engine=ri.Engine(self.client)
        self.engine.trigger({'kind':'finance_estimate','source':'ai_website','occurred_at':NOW.isoformat()})
        self.rows={
            '200':{'id':'200','_module':'Accounts','Account_Name':'Customer Company','Main_Workdrive_Folder_ID':'account-folder'},
            '300':{'id':'300','_module':'Contacts','Last_Name':'Person','Email':'person@customer.ca','Account_Name':{'id':'200'}},
            '400':{'id':'400','_module':'Service_Locations','Name':'123 Main Street','Linked_Account':{'id':'200'}},
            '500':{'id':'500','_module':'Services','Name':'Structured Cabling — earlier work','Service_Type':'Cabling Installation',
                'Linked_Service_Location':{'id':'400'},'Linked_Deal':{'id':'199'},'Service_Stage':'Ready for Scheduling'},
            '600':{'id':'600','_module':'Installations','Name':'Installation','Linked_Service':{'id':'500'},
                'Installation_Status':'Requested','Instructions_Notes':'Use front entrance'},
            '201':{'id':'201','_module':'Deals','Deal_Name':'Additional cabling work','Stage':'Contracts Signed',
                'Service_Types':'Structured Cabling','Account_Name':{'id':'200'},'Contact_Name':{'id':'300'},'Service_Location':{'id':'400'}},
        }
        for row in self.rows.values():
            row.update(Created_Time=NOW.isoformat(),Modified_Time=NOW.isoformat())
            self.client.records[row['id']]=row
            self.engine.register(row['_module'],row)
        self.lineage={'source':'ai_website','account_id':'200','contact_id':'300','site_id':'400',
            'service_ids':['500'],'installation_id':'600','accepted':True}
        self.engine.state['deals']['201']=self.lineage
    def read(self,path,*args):
        if path==lc.BASELINE:return {'modules':{'Accounts':{'protected_versions':{'999':'v1'}}}}
        return json.loads(path.read_text())
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def complete(self):
        self.rows['600'].update(Installation_Status='Completed',Completion_Notes='Tested and documented all drops',Completion_Proof_Link='https://workdrive.zoho.com/proof')
        self.client.timeline['600']=[status_event('600','Completed')]
        self.engine.completions()
    def invoice(self,status='paid',balance=0):
        native={'Invoice_ID':'800','Account_Name':{'id':'200'},'Potential_Name':{'id':'201'}}
        books={'invoice_id':'800','invoice_number':'INV-1','status':status,'total':100,'balance':balance,
            'due_date':(NOW-timedelta(days=2)).date().isoformat()}
        self.engine.trigger({'kind':'finance_invoice','source':'ai_website','occurred_at':NOW.isoformat(),'native':native,'books':books})
        return self.engine.invoice_progress(native,books,self.rows['201'],self.lineage,[self.rows['400']],[self.rows['500']])

    def test_completion_records_native_evidence_and_uses_activation_scope_once(self):
        self.complete()
        self.assertEqual(self.rows['500']['Service_Stage'],'Ready for Scheduling') # old snapshot isn't provider authority
        provider=self.client.records['500']
        self.assertEqual(provider['Service_Stage'],'Active')
        self.assertEqual(provider['OptiBrain_Last_Service_On'],NOW.astimezone(ri.operations.TIMEZONE).date().isoformat())
        changes=[effect for effect in self.engine.state['effects'].values() if effect['scope']=='crm.service.activate']
        self.assertEqual(len(changes),1)
        source=json.loads((self.root/'sources'/(changes[0]['trigger']+'.json')).read_text())
        self.assertEqual(source['timeline'][0]['source'],'crm_ui')
        self.assertIn('completion_evidence',source)
        self.assertTrue(self.lineage['completed'])
        count=self.client.mutations;self.engine.completions()
        self.assertEqual(self.client.mutations,count)

    def test_api_completion_missing_notes_and_wrong_site_never_activate(self):
        self.rows['600'].update(Installation_Status='Completed',Completion_Notes='Proof')
        self.client.timeline['600']=[status_event('600','Completed',source='crm_api')]
        self.engine.completions();self.assertEqual(self.client.mutations,0)
        self.client.timeline['600']=[status_event('600','Completed')]
        self.rows['600']['Completion_Notes']=''
        self.engine.completions();self.assertEqual(self.client.mutations,0)
        self.rows['600']['Completion_Notes']='Proof';self.rows['201']['Service_Location']={'id':'other'}
        self.engine.completions();self.assertEqual(self.client.mutations,0)

    def test_existing_active_reference_service_has_no_write_and_preserves_old_deal(self):
        self.engine.ownership['records']['500']['ownership']='REAL_REFERENCE'
        self.rows['500']['Service_Stage']='Active'
        old=copy.deepcopy(self.rows['500']);self.complete()
        self.assertEqual(self.client.records['500'],old)
        self.assertFalse(any(effect['scope']=='crm.service.activate' for effect in self.engine.state['effects'].values()))
        context=self.lineage['visits']['600']['context']
        self.assertEqual(context['deal_id'],'201')
        self.assertEqual(self.client.records['500']['Linked_Deal']['id'],'199')

    def test_reference_service_that_is_not_active_requires_human_not_write(self):
        self.engine.ownership['records']['500']['ownership']='REAL_REFERENCE';self.complete()
        self.assertEqual(self.client.mutations,0)
        self.assertIn('completion:600',self.engine.state['attention'])

    def test_owner_suspended_service_is_never_reactivated(self):
        self.rows['500']['Service_Stage']='Suspended';self.complete()
        self.assertEqual(self.client.mutations,0)
        self.assertFalse(self.lineage.get('completed'))

    def test_return_visit_reuses_service_preserves_original_and_is_unscheduled_idempotent(self):
        self.rows['600'].update(Installation_Status='Revisit Required',Instructions_Notes='Customer site access unavailable')
        self.client.timeline['600']=[status_event('600','Revisit Required')]
        self.engine.completions()
        self.assertEqual(len(self.lineage['return_visits']),1)
        child=next(iter(self.lineage['return_visits'].values()))
        record=self.client.records[child['installation_id']]
        self.assertEqual(record['Installation_Status'],'Requested')
        self.assertNotIn('Scheduled_Date',record)
        self.assertEqual(record['Linked_Service']['id'],'500')
        self.assertEqual(self.rows['600']['Installation_Status'],'Revisit Required')
        self.assertEqual(sum(r['_module']=='Services' for r in self.client.records.values()),1)
        count=self.client.mutations;self.engine.completions()
        self.assertEqual(len(self.lineage['return_visits']),1);self.assertEqual(self.client.mutations,count)
        record.update(Installation_Status='Completed',Completion_Notes='Access restored and tests passed')
        self.client.timeline[record['id']]=[status_event(record['id'],'Completed',event_id='child-completed')]
        self.engine.completions()
        self.assertTrue(self.lineage['completed'])
        self.assertEqual(self.rows['600']['Installation_Status'],'Revisit Required')
        self.assertNotIn('operation:600',self.engine.state['attention'])
        self.engine.completions();self.assertNotIn('operation:600',self.engine.state['attention'])

    def test_blocked_reason_and_owner_schedule_only_create_attention(self):
        self.rows['600'].update(Installation_Status='Failed',Instructions_Notes='')
        self.engine.completions();self.assertEqual(self.client.mutations,0)
        self.assertIn('completion:600',self.engine.state['attention'])
        self.rows['600']['Instructions_Notes']='No access';self.engine.completions()
        self.assertIn('INSTALLATION BLOCKED',self.engine.state['attention']['operation:600']['why'])
        self.rows['600'].update(Installation_Status='Scheduled',Scheduled_Date=NOW.isoformat())
        self.client.timeline['600']=[status_event('600','Scheduled')]
        self.engine.completions();self.assertEqual(self.client.mutations,0)
        self.assertIn('scheduled_local',self.lineage['operational']['600']['plan'])

    def test_paid_books_observation_closes_only_owned_open_billing_task(self):
        self.complete();billing=self.engine.state['effects']['task:billing:201']['provider_id']
        plan=self.invoice()
        self.assertEqual(plan['financial_state'],'SATISFIED')
        self.assertEqual(self.client.records[billing]['Status'],'Completed')
        count=self.client.mutations;self.invoice();self.assertEqual(self.client.mutations,count)
        self.assertFalse(any(service=='books' or '/books/' in path for service,method,path,body in self.client.writes))

    def test_overdue_invoice_observation_creates_one_internal_task_without_collection_send(self):
        plan=self.invoice('sent',100)
        self.assertEqual(plan['attention'],'INVOICE OVERDUE')
        self.assertEqual(self.client.mutations,1)
        self.invoice('sent',100);self.assertEqual(self.client.mutations,1)
        self.assertTrue(all(service=='zohoapis' and '/Tasks' in path for service,method,path,body in self.client.writes))

    def test_one_paid_invoice_cannot_clear_deal_billing_when_another_is_unknown_or_unpaid(self):
        self.complete();billing=self.engine.state['effects']['task:billing:201']['provider_id']
        self.lineage['invoice_native_ids']=['800','801']
        self.invoice()
        self.assertEqual(self.client.records[billing]['Status'],'Not Started')
        self.assertEqual(self.lineage['financial_state'],'OPEN')
        self.lineage['invoices']['801']={'financial_state':'UNPAID'}
        self.invoice()
        self.assertEqual(self.client.records[billing]['Status'],'Not Started')
        self.lineage['invoices']['801']={'financial_state':'SATISFIED'}
        self.invoice()
        self.assertEqual(self.client.records[billing]['Status'],'Completed')
        self.assertEqual(self.lineage['financial_state'],'SATISFIED')

    def test_wrong_invoice_association_and_payment_disagreement_are_human(self):
        self.rows['201']['Service_Location']={'id':'999'}
        with self.assertRaises(ri.HumanAttention):self.invoice()
        self.assertEqual(self.client.mutations,0)
        self.rows['201']['Service_Location']={'id':'400'}
        with self.assertRaises(ri.HumanAttention):self.invoice('paid',25)
        self.assertEqual(self.client.mutations,0)

    def test_accepted_new_deal_reuses_durable_service_without_old_deal_overwrite(self):
        self.rows['500']['Service_Stage']='Active'
        self.engine.ownership['records'].pop('500')
        observation={'transaction_id':'700','number':'EST-1','status':'accepted','account_id':'200','deal_id':'201','site_id':'400'}
        self.lineage.pop('accepted')
        with patch.object(self.engine,'folder',side_effect=lambda key,parent,name:{'id':key,'attributes':{'name':name,'parent_id':parent}}):
            self.engine.accepted(self.rows['201'],self.lineage,observation)
        self.assertEqual(self.engine.ownership['records']['500']['ownership'],'REAL_REFERENCE')
        self.assertEqual(self.rows['500']['Linked_Deal']['id'],'199')
        self.assertEqual(sum(r['_module']=='Services' for r in self.client.records.values()),1)
        self.assertFalse(any('/Services' in path for service,method,path,body in self.client.writes))

    def test_accepted_scope_change_and_protected_durable_service_never_create_effect(self):
        self.lineage.update(accepted_service_types='CCTV',accepted_estimate_id='700')
        with self.assertRaises(ri.HumanAttention):self.engine.accepted(self.rows['201'],self.lineage,{'transaction_id':'700'})
        self.assertEqual(self.client.mutations,0)
        self.lineage.update(accepted_service_types='Structured Cabling')
        self.engine.protected.add('500')
        observation={'transaction_id':'700','number':'EST-1','status':'accepted','account_id':'200','deal_id':'201','site_id':'400'}
        with self.assertRaises(ri.HumanAttention):self.engine.accepted(self.rows['201'],self.lineage,observation)
        self.assertEqual(self.client.mutations,0)

    def test_unproven_support_producer_remains_human_and_no_case_write(self):
        result=self.engine.prepare_support_case('support1',{'subject':'Camera issue','description':'No image','emergency':False},
            {'decision':'PREPARE_INTERNAL','deal_id':'201'})
        self.assertEqual(result['decision'],'HUMAN')
        self.assertEqual(self.client.mutations,0)

    def test_exact_site_formatting_reuses_but_spelling_collision_is_human(self):
        address={'street':'123 Main Street','unit':'Unit 2','city':'Montréal','province':'Québec','postal_code':'H1A 1A1','country':'Canada'}
        site={'id':'400','Linked_Account':{'id':'200'},**ri.site_fields(address)}
        normalized={**address,'street':'123 Main St.','unit':'Suite 002','city':'Montreal','province':'QC','postal_code':'h1a1a1'}
        self.assertEqual(ri.safe_site_match([site],'200',normalized)['decision'],'REUSE')
        self.assertEqual(ri.safe_site_match([site],'200',{**address,'street':'123 Mian Street'})['decision'],'HUMAN')
