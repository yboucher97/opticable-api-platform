from copy import deepcopy
from datetime import datetime, timezone, timedelta
import unittest
from workflow.automation.recurring_lifecycle import bind_profile, project_service, build_recurring
from workflow.automation.business_observation import NativeReader,collect_recurring

NOW=datetime(2026,10,3,12,tzinfo=timezone.utc)
def fixture():
 service={'id':'1','Name':'OPTIBRAIN TEST — PTP','OptiBrain_Test':True,'Linked_Service_Location':{'id':'2'},'Linked_Deal':{'id':'3'},'Contract_Type':'Recurring Service','Service_Stage':'Active','OptiBrain_Installed_On':'2024-10-01','OptiBrain_Renewal_On':'2026-11-01','Service_Type':'Other'}
 site={'id':'2','Name':'OPTIBRAIN TEST — Site','OptiBrain_Test':True,'Linked_Account':{'id':'4'}}
 profile={'recurring_invoice_id':'5','customer_id':'6','status':'active','total':'100.00','currency_code':'CAD','recurrence_frequency':'months','repeat_every':1,'next_invoice_date':'2026-11-01'}
 customer={'contact_id':'6','zcrm_account_id':'4'}
 invoice={'invoice_id':'7','customer_id':'6','recurring_invoice_id':'5','status':'paid','total':'100.00','balance':'0','due_date':'2026-10-01'}
 finance={'id':'8','Invoice_ID':'7','Account_Name':{'id':'4'},'Potential_Name':{'id':'3'}}
 return service,site,profile,customer,invoice,finance
class RecurringTests(unittest.TestCase):
 def plan(self, service=None, invoice=None, profile=None, **kwargs):
  s,l,p,c,i,f=fixture();return project_service(service or s,l,profile or p,[invoice or i],now=NOW,**kwargs)
 def kinds(self,row):return {a['kind'] for a in row['attention']}
 def test_a_native_recurring_relationship_renewal(self):
  s,l,p,c,i,f=fixture();r=bind_profile(p,c,[s],{'2':l},[f],[i]);self.assertEqual(r['decision'],'LINKED');self.assertEqual(r['service_id'],'1');self.assertIn('RENEWAL',self.kinds(self.plan()))
 def test_b_paid_keeps_active(self):
  r=self.plan();self.assertEqual(r['billing_state'],'PAID');self.assertEqual(r['health'],'ACTIVE');self.assertEqual(r['service_stage'],'Active');self.assertFalse(r['financial_writes'])
 def test_c_overdue_does_not_cancel(self):
  i=fixture()[4];i.update(balance='100',status='overdue');r=self.plan(invoice=i);self.assertEqual(r['billing_state'],'OVERDUE');self.assertEqual(r['service_stage'],'Active');self.assertIn('RECURRING_BILLING',self.kinds(r));self.assertNotIn('ENDED_BILLING_REVIEW',self.kinds(r))
 def test_d_explicit_maintenance_due(self):
  s=fixture()[0];s['OptiBrain_Maintenance_Due']='2026-10-01';self.assertIn('MAINTENANCE',self.kinds(self.plan(service=s)));s['OptiBrain_Last_Service_On']='2026-10-02';self.assertNotIn('MAINTENANCE',self.kinds(self.plan(service=s)))
 def test_e_contract_review_not_invented_legal_expiry(self):
  p=fixture()[2];p['end_date']='2026-11-01';r=self.plan(profile=p);self.assertIn('BILLING_END_REVIEW',self.kinds(r));self.assertIn('RENEWAL',self.kinds(r));self.assertTrue(any('not legal contract expiry' in a['why'] for a in r['attention']))
 def test_f_cancelled_cleanup_preserves_books(self):
  s=fixture()[0];s.update(Service_Stage='Cancelled',OptiBrain_Maintenance_Due='2026-10-01');r=self.plan(service=s);self.assertEqual(r['health'],'ENDED');self.assertEqual(self.kinds(r),{'ENDED_BILLING_REVIEW'});self.assertFalse(r['service_mutations']);self.assertFalse(r['financial_writes'])
 def test_price_review_only_attention(self):
  r=self.plan();self.assertIn('PRICE_REVIEW',self.kinds(r));self.assertNotIn('PRICE_REVIEW',self.kinds(self.plan(context={'price_review_completed_for_year':2026})))
 def test_retention_needs_distinct_overdue_invoices(self):
  s,l,p,c,i,f=fixture();i.update(status='overdue',balance='20');j={**i,'invoice_id':'9'};r=project_service(s,l,p,[i,j],now=NOW);self.assertIn('RETENTION',self.kinds(r));self.assertNotIn('RETENTION',self.kinds(self.plan(invoice=i)))
 def test_review_suppression(self):
  for context in [{'delivery_problem':True},{'review_requested_recently':True}]:
   with self.subTest(context=context):self.assertNotIn('REVIEW_ELIGIBLE',self.kinds(self.plan(context=context)))
  self.assertNotIn('REVIEW_ELIGIBLE',self.kinds(self.plan(cases=[{'id':'20','Related_To':{'id':'4'},'Status':'Open'}])))
 def test_cancellation_request_is_human_no_financial_effect(self):
  r=self.plan(context={'cancellation_request':True});self.assertEqual(r['health'],'ENDING');self.assertFalse(r['external_sends']);self.assertFalse(r['financial_writes'])
 def test_paused_service_no_future_renewal(self):
  s=fixture()[0];s['Service_Stage']='Suspended';self.assertNotIn('RENEWAL',self.kinds(self.plan(service=s)))
 def test_wrong_native_link_denials(self):
  for kind in ['customer','account','site','deal','multiple_services','missing_deal']:
   with self.subTest(kind=kind):
    s,l,p,c,i,f=fixture();sv=[s]
    if kind=='customer':c['contact_id']='90'
    if kind=='account':f['Account_Name']={'id':'90'}
    if kind=='site':l['Linked_Account']={'id':'90'}
    if kind=='deal':f['Potential_Name']={'id':'90'}
    if kind=='multiple_services':sv.append({**s,'id':'90'})
    if kind=='missing_deal':f['Potential_Name']=None
    self.assertEqual(bind_profile(p,c,sv,{'2':l},[f],[i])['decision'],'HUMAN')
 def test_wrong_generated_invoice_denied(self):
  for k in ['customer_id','recurring_invoice_id']:
   with self.subTest(k=k):
    i=fixture()[4];i[k]='90'
    with self.assertRaises(ValueError):self.plan(invoice=i)
 def test_duplicate_invoice_denied(self):
  s,l,p,c,i,f=fixture()
  with self.assertRaises(ValueError):project_service(s,l,p,[i,i],now=NOW)
 def test_no_names_amounts_guess(self):
  s,l,p,c,i,f=fixture();self.assertEqual(bind_profile(p,c,[s],{'2':l},[],[i])['decision'],'HUMAN')
 def test_reviewed_link_crosschecks_every_native_parent(self):
  s,l,p,c,i,f=fixture();review={'profile_id':'5','customer_id':'6','account_id':'4','service_id':'1','site_id':'2','reviewed_at':NOW.isoformat(),'reviewed_by':'owner','proof':'explicit selection'}
  self.assertEqual(bind_profile(p,c,[s],{'2':l},[],[],reviewed=review)['decision'],'LINKED')
  for k in ['profile_id','customer_id','account_id','site_id','service_id']:
   with self.subTest(k=k):self.assertEqual(bind_profile(p,c,[s],{'2':l},[],[],reviewed={**review,k:'90'})['decision'],'HUMAN')
 def snapshot(self):
  s,l,p,c,i,f=fixture();return {'services':[s],'sites':[l],'accounts':[{'id':'4','Account_Name':'OPTIBRAIN TEST — A','OptiBrain_Test':True}],'profiles':[p],'customers':[c],'finance_invoices':[f],'generated':{'5':[i]}}
 def test_test_only_exclusion(self):
  r=build_recurring(self.snapshot(),now=NOW);self.assertEqual(r['rows'],[]);self.assertEqual(r['attention'],[])
 def test_replay_same_keys_zero_duplicate_cards(self):
  a=self.plan();b=self.plan();self.assertEqual([x['key'] for x in a['attention']],[x['key'] for x in b['attention']]);self.assertEqual(len({x['key'] for x in a['attention']}),len(a['attention']))
 def test_windows_update_without_new_task_key(self):
  s,l,p,c,i,f=fixture();a=project_service(s,l,p,[i],now=NOW-timedelta(days=50));b=project_service(s,l,p,[i],now=NOW)
  self.assertEqual(next(x['key'] for x in a['attention'] if x['kind']=='RENEWAL'),next(x['key'] for x in b['attention'] if x['kind']=='RENEWAL'))
 def test_no_dates_invented(self):
  s=fixture()[0];s.pop('OptiBrain_Renewal_On');s.pop('OptiBrain_Installed_On');self.assertFalse(self.kinds(self.plan(service=s))&{'RENEWAL','PRICE_REVIEW','MAINTENANCE','REVIEW_ELIGIBLE'})
 def test_get_only_native_adapter(self):
  class Client:
   def request(self,service,method,path,**kwargs):self.method=method;return {'ok':True,'status':200,'data':{'code':0}}
  c=Client();r=NativeReader(c);r.get('/books/v3/recurringinvoices');self.assertEqual(c.method,'GET')
  with self.assertRaises(ValueError):r.get('/marketing/write')
 def test_reader_fails_closed(self):
  for response in [{'ok':False,'status':200,'data':{'code':0}},{'ok':True,'status':200,'data':{'code':99}},{'ok':True,'status':403,'data':{} }]:
   with self.subTest(response=response):
    class C:
     def request(self,*a,**k):return response
    with self.assertRaises(ValueError):NativeReader(C()).get('/books/v3/recurringinvoices')
 def test_reader_budget(self):
  class C:
   def request(self,*a,**k):return {'ok':True,'status':200,'data':{'code':0}}
  r=NativeReader(C(),limit=1);r.get('/books/v3/invoices')
  with self.assertRaises(ValueError):r.get('/books/v3/invoices')
 def test_attention_upsell_deduped_per_site(self):
  x=self.snapshot();s=x['services'][0];l=x['sites'][0];s['OptiBrain_Test']=False;l['OptiBrain_Test']=False;x['accounts'][0].update(OptiBrain_Test=False,Account_Name='Customer');s['Name']='Cabling';s['Service_Type']='Cabling Installation';l['Name']='Site';x['profiles']=[]
  a=build_recurring(x,now=NOW);b=build_recurring(x,now=NOW);self.assertEqual(a,b);self.assertEqual(sum(r['kind']=='OPPORTUNITY' for r in a['attention']),1)
class CollectionTests(unittest.TestCase):
 def client(self, *, historical=False, unpaid=False):
  s,l,p,c,i,f=fixture();p['last_modified_time']='2026-10-01T08:19:16-04:00';i['date']='2026-03-25'
  if historical:i['customer_id']='90'
  if unpaid:i.update(status='unpaid',balance=100)
  responses={
   '/crm/v8/Accounts':{'data':[{'id':'4','Account_Name':'Customer'}],'info':{'more_records':False}},
   '/crm/v8/Services':{'data':[s],'info':{'more_records':False}},
   '/crm/v8/Service_Locations':{'data':[l],'info':{'more_records':False}},
   '/crm/v8/CustomModule5001':{'data':[f],'info':{'more_records':False}},
   '/crm/v8/Cases':{'data':[],'info':{'more_records':False}},
   '/crm/v8/Installations':{'data':[],'info':{'more_records':False}},
   '/books/v3/recurringinvoices':{'code':0,'recurring_invoices':[p],'page_context':{'has_more_page':False}},
   '/books/v3/recurringinvoices/5':{'code':0,'recurring_invoice':p},
   '/books/v3/contacts/6':{'code':0,'contact':c},
   '/books/v3/recurringinvoices/5/invoices':{'code':0,'invoice_history':[{'invoice_id':'7'}],'page_context':{'has_more_page':False}},
   '/books/v3/invoices/7':{'code':0,'invoice':i}}
  class Client:
   methods=[]
   def request(self,service,method,path,**kwargs):
    self.methods.append(method);return {'ok':True,'status':200,'data':deepcopy(responses[path])}
  return Client()
 def test_collects_actual_invoice_history_key(self):
  c=self.client();v=collect_recurring(NativeReader(c));self.assertEqual(v['generated']['5'][0]['invoice_id'],'7');self.assertEqual(set(c.methods),{'GET'})
 def test_historical_customer_discontinuity_quarantined(self):
  c=self.client(historical=True);v=collect_recurring(NativeReader(c));self.assertEqual(v['generated']['5'],[]);self.assertEqual(v['profile_exceptions'][0]['kind'],'HISTORICAL_CUSTOMER_DISCONTINUITY');self.assertFalse(v['profile_exceptions'][0]['automatic_association'])
 def test_current_unpaid_wrong_customer_blocks_observation(self):
  with self.assertRaises(ValueError):collect_recurring(NativeReader(self.client(historical=True,unpaid=True)))
 def test_test_profile_cannot_leak_unlinked_attention(self):
  x=RecurringTests().snapshot();x['profiles'][0]['recurrence_name']='OPTIBRAIN TEST — Recurring';x['accounts']=[];r=build_recurring(x,now=NOW);self.assertEqual(r['attention'],[])
if __name__=='__main__':unittest.main()
