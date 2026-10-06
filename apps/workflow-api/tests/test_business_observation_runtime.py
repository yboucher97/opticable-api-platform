"""Bounded incremental collection with fake native GETs and isolated checkpoints."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest.mock import patch
import unittest
from workflow.automation import observation_runtime as runtime
from workflow.automation.business_observation import NativeReader, ReadBudgetExceeded, same_version
from workflow.automation.recurring_lifecycle import build_recurring

NOW=datetime(2026,10,6,3,tzinfo=timezone.utc)
OLD=(NOW-timedelta(hours=6)).isoformat()
VERSION='2026-10-01T00:00:00Z'


class NativeFixture:
    def __init__(self, profiles=23, customers=38):
        self.calls=[];self.fail={};self.pages={};self.records={};self.histories={}
        self.customers=[{'contact_id':str(2000+i),'last_modified_time':VERSION,'zcrm_account_id':'','currency_code':'CAD'} for i in range(customers)]
        self.invoices=[{'invoice_id':str(3000+i),'customer_id':self.customers[(i//2)%4 if i<profiles*2 else i%customers]['contact_id'],
            'last_modified_time':VERSION,'status':'paid','balance':'0','total':'10','currency_code':'CAD','date':'2026-10-01','due_date':'2026-10-01',
            'zcrm_potential_id':'','estimate_id':''} for i in range(120)]
        self.estimates=[{'estimate_id':str(4000+i),'customer_id':self.customers[i%customers]['contact_id'],'last_modified_time':VERSION,
            'status':'draft','date':'2026-10-01','total':'10','currency_code':'CAD','zcrm_potential_id':'','invoice_ids':[]} for i in range(90)]
        self.profiles=[{'recurring_invoice_id':str(5000+i),'customer_id':self.customers[i%4]['contact_id'],'last_modified_time':VERSION,
            'status':'inactive','start_date':'2026-01-01','currency_code':'CAD','sub_total':'10','total':'10','repeat_every':1,'recurrence_frequency':'months'} for i in range(profiles)]
        for i,p in enumerate(self.profiles):
            invoices=self.invoices[i*2:i*2+2]
            for v in invoices:v['customer_id']=p['customer_id'];v['recurring_invoice_id']=p['recurring_invoice_id']
            self.histories[p['recurring_invoice_id']]=invoices
        for kind,rows,id_key in [('contacts',self.customers,'contact_id'),('invoices',self.invoices,'invoice_id'),('estimates',self.estimates,'estimate_id'),('recurringinvoices',self.profiles,'recurring_invoice_id')]:
            self.records.update({'/books/v3/'+kind+'/'+r[id_key]:r for r in rows})
    def request(self,service,method,path,query=None):
        assert method=='GET' and service=='zohoapis'
        self.calls.append((method,path,deepcopy(query)))
        if path in self.fail:return {'ok':False,'status':self.fail[path],'data':{}}
        if path.startswith('/crm/v8/'):
            return {'ok':True,'status':200,'data':{'data':self.pages.get(path,[]),'info':{'more_records':False}}}
        kind=path.split('/')[3];body={'code':0}
        if path=='/books/v3/organizations':body['organizations']=[{'organization_id':'802337532','currency_code':'CAD'}]
        elif path.endswith('/invoices') and kind=='recurringinvoices':
            body['invoice_history']=[{'invoice_id':v['invoice_id']} for v in self.histories[path.split('/')[4]]]
            body['page_context']={'has_more_page':False}
        elif path in self.records:
            key={'contacts':'contact','invoices':'invoice','estimates':'estimate','recurringinvoices':'recurring_invoice'}[kind]
            body[key]=deepcopy(self.records[path])
        else:
            key={'contacts':'contacts','invoices':'invoices','estimates':'estimates','recurringinvoices':'recurring_invoices',
                 'customerpayments':'customerpayments','expenses':'expenses'}[kind]
            body[key]=deepcopy({'contacts':self.customers,'invoices':self.invoices,'estimates':self.estimates,'recurringinvoices':self.profiles}.get(kind,[]))
            if kind in {'contacts','invoices','estimates','recurringinvoices'}:
                id_key={'contacts':'contact_id','invoices':'invoice_id','estimates':'estimate_id','recurringinvoices':'recurring_invoice_id'}[kind]
                body[key]=[{k:r[k] for k in (id_key,'customer_id','last_modified_time','date','status','total','balance','currency_code','next_invoice_date') if k in r} for r in body[key]]
            body['page_context']={'has_more_page':False}
        return {'ok':True,'status':200,'data':body}
    def previous(self, marketing=False):
        snapshot={n:[] for n in ('accounts','services','sites','finance_invoices','cases','installations')}
        snapshot.update(observed_at=OLD,profiles=deepcopy(self.profiles),customers=deepcopy(self.customers[:4]),
            generated=deepcopy(self.histories),profile_exceptions=[])
        if marketing:snapshot.update(leads=[],contacts=[],deals=[],finance_estimates=[],books_invoices=deepcopy(self.invoices),
            books_estimate_index={r['estimate_id']:deepcopy(r) for r in self.estimates},customers=deepcopy(self.customers))
        return {'schema':3,'observed_at':OLD,'snapshot':snapshot,'recurring':build_recurring(snapshot,now=NOW-timedelta(hours=6)),
                'marketing':{'schema':1,'scope':'live','read_only':True,'groups':[],'observed_at':OLD,'outcomes':[],'customer_value':[]} if marketing else None}


class ObservationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.saved=self.root/'business-observation.json';self.outputs={}
        def atomic(path,value,*args):
            self.outputs[path.name]=deepcopy(value)
            if path==self.saved:path.write_text(json.dumps(value))
        for target,value in [('ROOT',self.root),('DISPLAY',self.root/'recurring.json')]:
            p=patch.object(runtime,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(runtime.Path,'exists',lambda path:path.parent==self.root and path.is_file());p.start();self.addCleanup(p.stop)
        p=patch.object(runtime.lc,'trusted_json',lambda path,*args:json.loads(path.read_text()));p.start();self.addCleanup(p.stop)
        p=patch('workflow.automation.real_internal.atomic',side_effect=atomic);p.start();self.addCleanup(p.stop)
        for target in ('os.chown','os.chmod'):
            p=patch(target);p.start();self.addCleanup(p.stop)
        p=patch('grp.getgrnam',return_value=SimpleNamespace(gr_gid=1001));p.start();self.addCleanup(p.stop)
    def observe(self,client,previous=None,reads=24,now=NOW):
        if previous is not None:self.saved.write_text(json.dumps(previous))
        e=SimpleNamespace(client=client,reads=reads,dry_run=False,state={'deals':{}})
        try:runtime.observe(e,now=now)
        except ValueError:pass
        return json.loads(self.saved.read_text()),e
    def test_budget_below_total_demand_warm_reuse_completes_marketing(self):
        client=NativeFixture();v,e=self.observe(client,client.previous())
        self.assertEqual(v['collection']['state'],'COMPLETE');self.assertIsNotNone(v['marketing'])
        self.assertLessEqual(e.reads,160);self.assertLess(len(client.calls),100)
        self.assertEqual(v['collection']['stages']['recurring']['state'],'COMPLETE')
        self.assertEqual(v['collection']['stages']['marketing']['state'],'COMPLETE')
    def test_required_stage_fairness_cold_checkpoint_converges(self):
        client=NativeFixture();v,e=self.observe(client)
        self.assertEqual(v['collection']['state'],'PARTIAL')
        for name in ('marketing','recurring'):
            stage=v['collection']['stages'][name];self.assertGreater(stage['provider_reads'],0)
            self.assertLessEqual(stage['provider_reads'],stage['budget'])
        self.assertLessEqual(e.reads,160);self.assertTrue(v['detail_checkpoint'])
        client.calls=[];nextv,_=self.observe(client,now=NOW+timedelta(hours=1))
        self.assertEqual(nextv['collection']['state'],'COMPLETE');self.assertLess(len(client.calls),100)
    def test_customer_detail_reuse_preserves_source_dates(self):
        client=NativeFixture();v,_=self.observe(client,client.previous(marketing=True))
        self.assertFalse(any('/contacts/' in path for _,path,_ in client.calls))
        self.assertTrue(all(d['source_at']==OLD for path,d in v['detail_checkpoint'].items() if '/contacts/' in path))
        self.assertEqual(v['collection']['modules']['customers']['source_at'],NOW.isoformat())
    def test_generated_history_read_even_when_profile_version_unchanged(self):
        client=NativeFixture();self.observe(client,client.previous(marketing=True))
        histories=[path for _,path,_ in client.calls if '/recurringinvoices/' in path and path.endswith('/invoices')]
        self.assertEqual(len(histories),23)
        self.assertFalse(any('/invoices/' in path for _,path,_ in client.calls))
    def test_changed_customer_reads_only_changed_id(self):
        client=NativeFixture();previous=client.previous(marketing=True)
        client.customers[5]['last_modified_time']='2026-10-02T00:00:00Z'
        v,_=self.observe(client,previous)
        paths=[path for _,path,_ in client.calls if '/contacts/' in path]
        self.assertEqual(paths,['/books/v3/contacts/2005'])
        self.assertEqual(v['detail_checkpoint'][paths[0]]['source_at'],NOW.isoformat())
    def test_stage_exhaustion_explicit_no_provider_overshoot(self):
        client=NativeFixture();v,e=self.observe(client,reads=150)
        self.assertLessEqual(e.reads,160)
        self.assertTrue(any(m.get('attempt_state')=='SKIPPED_BUDGET' for m in v['collection']['modules'].values()))
        self.assertEqual(v['collection']['state'],'PARTIAL')
    def test_marketing_failed_recurring_success_last_good_independent(self):
        client=NativeFixture();prior=client.previous(marketing=True);client.fail['/books/v3/estimates']=503
        v,_=self.observe(client,prior)
        self.assertEqual(v['collection']['stages']['recurring']['state'],'COMPLETE')
        self.assertEqual(v['collection']['stages']['marketing']['state'],'PARTIAL')
        self.assertEqual(v['marketing']['observed_at'],OLD)
        self.assertEqual(v['snapshot']['books_estimate_index'],prior['snapshot']['books_estimate_index'])
        m=v['collection']['modules']['books_estimate_index']
        self.assertEqual((m['state'],m['source_at'],m['error_code']),('STALE_REUSED',OLD,503))
        self.assertEqual(m['failed_reads'],1)
        self.assertEqual(self.outputs['marketing.json']['observed_at'],OLD)
        self.assertEqual(self.outputs['marketing.json']['collection']['state'],'PARTIAL')
    def test_last_good_customer_detail_preserved_on_failed_changed_refresh(self):
        client=NativeFixture();prior=client.previous(marketing=True)
        client.customers[5]['last_modified_time']='2026-10-02T00:00:00Z';client.fail['/books/v3/contacts/2005']=500
        v,_=self.observe(client,prior)
        self.assertEqual(v['detail_checkpoint']['/books/v3/contacts/2005']['data'],prior['snapshot']['customers'][5])
        self.assertEqual(v['last_good_modules']['customers']['source_at'],OLD)
        self.assertEqual(v['collection']['modules']['customers']['state'],'STALE_REUSED')
    def test_missing_marketing_published_with_explicit_partial_status(self):
        client=NativeFixture();client.fail['/books/v3/estimates']=403
        v,_=self.observe(client,client.previous())
        self.assertIsNone(v['marketing']);self.assertEqual(v['collection']['state'],'PARTIAL')
        self.assertIn('business.json',self.outputs)
        self.assertEqual(self.outputs['business.json']['snapshot']['collection']['state'],'PARTIAL')
        self.assertNotIn('marketing.json',self.outputs)
    def test_optional_failure_preserves_successful_required_modules(self):
        client=NativeFixture();client.fail['/books/v3/expenses']=503
        v,_=self.observe(client,client.previous(marketing=True))
        self.assertEqual(v['collection']['state'],'COMPLETE');self.assertIsNotNone(v['marketing'])
        self.assertEqual(v['collection']['stages']['business_optional']['state'],'PARTIAL')
    def test_legacy_schema3_migration_no_missing_module_claim(self):
        client=NativeFixture();v,_=self.observe(client,client.previous(),reads=160)
        self.assertEqual(v['schema'],3);self.assertEqual(v['collection']['schema'],1)
        self.assertNotIn('deals',v['snapshot']);self.assertEqual(v['collection']['modules']['deals']['state'],'SKIPPED_BUDGET')
    def test_cached_partial_attempt_does_not_redate_source(self):
        client=NativeFixture();client.fail['/books/v3/estimates']=500
        v,_=self.observe(client,client.previous(marketing=True));client.calls=[]
        nextv,_=self.observe(client,now=NOW+timedelta(minutes=5))
        self.assertEqual(client.calls,[]);self.assertEqual(v['observed_at'],nextv['observed_at'])
        self.assertEqual(nextv['attempted_at'],NOW.isoformat());self.assertEqual(self.outputs['marketing.json']['observed_at'],OLD)
    def test_marketing_success_recurring_failure_preserves_independent_modules(self):
        client=NativeFixture();client.fail['/books/v3/recurringinvoices/5000/invoices']=503
        v,_=self.observe(client,client.previous(marketing=True))
        self.assertEqual(v['collection']['stages']['marketing']['state'],'COMPLETE')
        self.assertEqual(v['collection']['stages']['recurring']['state'],'PARTIAL')
        self.assertEqual(v['marketing']['observed_at'],NOW.isoformat())
        self.assertEqual(v['recurring']['observed_at'],OLD)
        self.assertEqual(len(v['snapshot']['books_invoices']),120)
    def test_view_build_failure_cannot_redate_last_good_marketing(self):
        client=NativeFixture()
        with patch.object(runtime,'build_marketing',side_effect=TypeError('unsafe payload text')):
            v,_=self.observe(client,client.previous(marketing=True))
        self.assertEqual(v['collection']['stages']['marketing']['state'],'FAILED')
        self.assertEqual(v['collection']['stages']['marketing']['error_type'],'TypeError')
        self.assertEqual(self.outputs['marketing.json']['observed_at'],OLD)
        self.assertNotIn('unsafe payload text',json.dumps(v['collection']))
    def test_failed_recurring_checkpoint_cannot_overwrite_fresh_customer(self):
        client=NativeFixture();previous=client.previous(marketing=True)
        client.customers[0].update(last_modified_time='2026-10-02T00:00:00Z',currency_code='USD')
        client.fail['/books/v3/recurringinvoices/5000/invoices']=503
        v,_=self.observe(client,previous)
        customer=next(r for r in v['snapshot']['customers'] if r['contact_id']=='2000')
        self.assertEqual(customer['currency_code'],'USD')
        self.assertEqual(v['collection']['modules']['customers']['state'],'COMPLETE')
        self.assertEqual(v['last_good_modules']['recurring_details']['data']['customers'][0]['currency_code'],'CAD')
        self.assertEqual(v['last_good_modules']['recurring_details']['source_at'],OLD)
    def test_customer_without_transactions_still_required_for_context(self):
        client=NativeFixture(customers=40)
        v,_=self.observe(client,client.previous())
        self.assertEqual(len(v['snapshot']['customers']),40)
        self.assertEqual(v['collection']['modules']['customers']['state'],'COMPLETE')
    def test_public_aggregate_excludes_customer_and_conversion_ids(self):
        client=NativeFixture();self.observe(client,client.previous(marketing=True))
        self.assertNotIn('customer_value',self.outputs['marketing.json']);self.assertNotIn('outcomes',self.outputs['marketing.json'])
    def test_exact_bound_and_one_above(self):
        client=NativeFixture();r=NativeReader(client,limit=2)
        for _ in range(2):r.get('/books/v3/invoices')
        self.assertEqual(r.reads,2)
        with self.assertRaises(ReadBudgetExceeded):r.get('/books/v3/invoices')
        self.assertEqual((r.reads,len(client.calls),r.attempted),(2,2,3))
    def test_duplicate_listing_is_failed_not_verified_empty(self):
        client=NativeFixture();client.pages['/crm/v8/Deals']=[{'id':'1'},{'id':'1'}]
        v,_=self.observe(client,client.previous(marketing=True))
        self.assertEqual(v['collection']['modules']['deals']['state'],'STALE_REUSED')
        self.assertEqual(v['snapshot']['deals'],[])
        self.assertEqual(v['collection']['stages']['marketing']['state'],'PARTIAL')
    def test_malformed_row_records_error_without_discarding_other_stage(self):
        client=NativeFixture();client.pages['/crm/v8/Deals']=[None]
        v,_=self.observe(client,client.previous(marketing=True))
        self.assertEqual(v['collection']['modules']['deals']['error_type'],'ValueError')
        self.assertEqual(v['collection']['stages']['recurring']['state'],'COMPLETE')
    def test_unchanged_detail_keeps_current_listing_facts_and_original_detail_date(self):
        client=NativeFixture();previous=client.previous(marketing=True)
        client.profiles[0]['next_invoice_date']='2026-11-01'
        client.invoices[0]['balance']='2';client.invoices[0]['status']='partially_paid'
        v,_=self.observe(client,previous)
        invoice=next(r for r in v['snapshot']['books_invoices'] if r['invoice_id']=='3000')
        self.assertEqual(invoice['balance'],'2')
        self.assertEqual(v['snapshot']['generated']['5000'][0]['status'],'partially_paid')
        self.assertEqual(v['snapshot']['profiles'][0]['next_invoice_date'],'2026-11-01')
        self.assertEqual(v['detail_checkpoint']['/books/v3/invoices/3000']['source_at'],OLD)
    def test_malformed_transport_response_counted_as_failed_read(self):
        client=SimpleNamespace(request=lambda *a,**kw:None);reader=NativeReader(client,limit=1)
        with self.assertRaises(ValueError):reader.get('/books/v3/invoices')
        self.assertEqual((reader.reads,reader.successful,reader.failed),(1,0,1))
    def test_stale_reused_listing_cannot_certify_unchanged_details(self):
        client=NativeFixture(profiles=1);prior=client.previous(marketing=True)
        client.invoices[0]['balance']='2';client.invoices[0]['status']='partially_paid'
        client.fail['/books/v3/invoices']=503
        v,_=self.observe(client,prior)
        self.assertEqual(v['collection']['modules']['books_invoices']['state'],'STALE_REUSED')
        self.assertEqual(v['collection']['stages']['recurring']['state'],'COMPLETE')
        self.assertTrue(any(path=='/books/v3/invoices/3000' for _,path,_ in client.calls))
        self.assertEqual(v['snapshot']['generated']['5000'][0]['balance'],'2')
        self.assertEqual(v['detail_checkpoint']['/books/v3/invoices/3000']['source_at'],NOW.isoformat())
    def test_detail_identity_and_version_required(self):
        a={'contact_id':'1','last_modified_time':VERSION}
        for changes in ({'contact_id':'2'},{'last_modified_time':None},{'last_modified_time':'bad'},{'last_modified_time':'2026-10-01'}):
            with self.subTest(changes=changes):self.assertFalse(same_version(a,{**a,**changes},'contact_id'))
