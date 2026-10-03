from copy import deepcopy
from datetime import datetime,timezone
import unittest
from workflow.automation.finance_links import resolve_finance, validate_confirmation, linkage_attention, recurring_reviews
from workflow.automation.measurement import populations
from workflow.automation.business_observation import enrich_finance, NativeReader
from test_marketing_attribution import fixture

class FinanceLinkTests(unittest.TestCase):
 def rows(self,s=None):return populations(s or fixture())[0]
 def test_forward_a_estimate_invoice_site_multiple_services(self):
  s=fixture();s['deals'][0]['Service_Location']={'id':'5'};s['services'].append({**s['services'][0],'id':'16'})
  s['finance_invoices'][0]['Potential_Name']=None;s['books_invoices'][0]['estimate_id']='8'
  r=resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))
  self.assertEqual((r['deal_id'],r['site_ids'],r['service_ids']),('4',['5'],['16','6']))
 def test_b_new_deal_does_not_borrow_old_customer_opportunity(self):
  s=fixture();s['deals'].append({**s['deals'][0],'id':'14'})
  s['finance_invoices'][0]['Potential_Name']=None;s['books_invoices'][0]['zcrm_potential_id']='14'
  self.assertEqual(resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))['deal_id'],'14')
 def test_reverse_native_estimate_invoice_ids(self):
  s=fixture();s['finance_invoices'][0]['Potential_Name']=None;s['books_estimate_index']['8']['invoice_ids']=['11']
  r=resolve_finance(s['books_invoices'][0],'invoices',self.rows(s));self.assertEqual(r['deal_id'],'4')
  self.assertEqual(r['classification'],'DERIVED DETERMINISTICALLY')
 def test_parent_customer_conflict_never_associates(self):
  s=fixture();s['books_invoices'][0]['estimate_id']='8';s['books_estimate_index']['8']['customer_id']='99'
  self.assertTrue(resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))['conflict'])
 def review(self,kind='invoices',rid='11'):
  return {'kind':kind,'record_id':rid,'customer_id':'9','account_id':'1','deal_id':'4','site_id':'5',
   'reviewed_by':'Opticable owner','reviewed_at':'2026-10-03T03:00:00+00:00','proof':'Explicit owner choice'}
 def test_owner_confirmed_projection_keeps_sources_unchanged(self):
  s=fixture();s['finance_invoices'][0]['Potential_Name']=None;s['finance_reviews']={'invoices:11':self.review()};before=deepcopy(s)
  r=resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))
  self.assertEqual(r['classification'],'OWNER CONFIRMED');self.assertEqual(s,before)
 def test_owner_wrong_parents_denied(self):
  for field in ('customer_id','account_id','deal_id','site_id'):
   with self.subTest(field=field):
    s=fixture();s['finance_reviews']={'invoices:11':{**self.review(),field:'99'}}
    self.assertTrue(resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))['conflict'])
 def test_unconfirmed_future_or_no_actor_denied(self):
  for change in ({'reviewed_at':'2099-01-01T00:00:00Z'},{'reviewed_by':''},{'proof':''},{'reviewed_at':'2026-10-03'}):
   with self.subTest(change=change):
    with self.assertRaises(ValueError):validate_confirmation({**self.review(),**change},self.rows())
 def test_owner_conflict_cannot_override_native(self):
  s=fixture();s['deals'].append({**s['deals'][0],'id':'14'});s['finance_reviews']={'invoices:11':{**self.review(),'deal_id':'14'}}
  self.assertTrue(resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))['conflict'])
 def test_test_estimate_native_invoice_descendant_is_excluded(self):
  for reverse in (False,True):
   with self.subTest(reverse=reverse):
    s=fixture();s['books_estimate_index']['8']['OptiBrain_Test']=True
    if reverse:s['books_estimate_index']['8']['invoice_ids']=['11']
    else:s['books_invoices'][0]['estimate_id']='8'
    self.assertEqual(self.rows(s)['invoices'],{})
    from workflow.automation.marketing_attribution import build_marketing
    self.assertTrue(all(not g['invoice_value'] for g in build_marketing(s)['groups']))
 def test_owner_profile_cannot_override_native_deal(self):
  from workflow.automation.recurring_lifecycle import bind_profile
  s=fixture();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9','zcrm_potential_id':'14'}]
  rows=self.rows(s);review={**self.review('profiles','12'),'profile_id':'12','service_id':'6'}
  self.assertEqual(bind_profile(s['profiles'][0],s['customers'][0],s['services'],rows['sites'],[],[],reviewed=review)['decision'],'HUMAN')
 def test_c_recurring_review_generated_invoice(self):
  s=fixture();s['profiles']=[{'recurring_invoice_id':'12','customer_id':'9'}]
  s['books_invoices'][0]['recurring_invoice_id']='12';s['finance_invoices'][0]['Potential_Name']=None
  s['finance_reviews']={'profiles:12':{**self.review('profiles','12'),'service_id':'6'}}
  r=resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))
  self.assertEqual((r['deal_id'],r['service_ids']),('4',['6']))
 def test_d_ambiguous_batch_no_guess_or_provider_task(self):
  s=fixture();s['finance_invoices'][0]['Potential_Name']=None
  r=linkage_attention(s,self.rows(s));self.assertEqual(len(r),1);self.assertEqual(r[0]['candidate_deals'],['4'])
  self.assertFalse(r[0]['automatic_guess']);self.assertFalse(r[0]['provider_task_created'])
 def test_e_replay_stable_attention_and_review(self):
  s=fixture();s['finance_invoices'][0]['Potential_Name']=None
  self.assertEqual(linkage_attention(s,self.rows(s)),linkage_attention(s,self.rows(s)))
 def test_existing_service_original_deal_preserved_with_accepted_evidence(self):
  s=fixture();s['deals'][0]['Service_Location']={'id':'5'}
  s['services'][0]['Linked_Deal']={'id':'14'}
  s['accepted_work']={'4':{'accepted':True,'accepted_estimate_id':'8','service_ids':['6']}}
  r=resolve_finance(s['books_invoices'][0],'invoices',self.rows(s));self.assertEqual(r['service_ids'],['6'])
  self.assertEqual(s['services'][0]['Linked_Deal']['id'],'14')
 def test_missing_accepted_parent_cannot_claim_reused_service(self):
  s=fixture();s['services'][0]['Linked_Deal']={'id':'14'}
  s['accepted_work']={'4':{'accepted':True,'accepted_estimate_id':'99','service_ids':['6']}}
  self.assertEqual(resolve_finance(s['books_invoices'][0],'invoices',self.rows(s))['service_ids'],[])
 def test_test_finance_and_descendants_excluded(self):
  s=fixture();s['accounts'][0]['OptiBrain_Test']=True
  self.assertEqual(linkage_attention(s,self.rows(s)),[])

class DetailTests(unittest.TestCase):
 def client(self,actual):
  class C:
   methods=[]
   def request(self,service,method,path,**kwargs):
    self.methods.append(method);kind='invoice' if 'invoices' in path else 'estimate'
    return {'ok':True,'status':200,'data':{'code':0,kind:deepcopy(actual)}}
  return C()
 def sample(self):
  return {'estimate_id':'8','customer_id':'9','last_modified_time':'2026-10-03T00:00:00Z'}, {'estimate_id':'8','customer_id':'9','last_modified_time':'2026-10-03T00:00:00Z','zcrm_potential_id':'4','invoice_ids':['11']}
 def test_detail_get_retains_native_parent(self):
  row,full=self.sample();c=self.client(full);r=NativeReader(c,limit=1)
  v=enrich_finance(r,{'books_estimate_index':{'8':row},'books_invoices':[]})
  self.assertEqual(v['books_estimate_index']['8']['zcrm_potential_id'],'4');self.assertEqual(c.methods,['GET'])
 def test_exact_unchanged_version_reuses_cache(self):
  row,full=self.sample();r=NativeReader(self.client(full),limit=0)
  v=enrich_finance(r,{'books_estimate_index':{'8':row}},previous={'books_estimate_index':{'8':full}})
  self.assertEqual(v['finance_detail_coverage']['pending'],0);self.assertEqual(r.reads,0)
 def test_changed_version_never_reuses_old_deal(self):
  row,full=self.sample();row['last_modified_time']='2026-10-03T01:00:00Z';r=NativeReader(self.client(full),limit=0)
  v=enrich_finance(r,{'books_estimate_index':{'8':row}},previous={'books_estimate_index':{'8':full}})
  self.assertEqual(v['finance_detail_coverage']['pending'],1);self.assertNotIn('zcrm_potential_id',v['books_estimate_index']['8'])
 def test_customer_changed_blocks_publish(self):
  row,full=self.sample();full['customer_id']='99';r=NativeReader(self.client(full),limit=1)
  with self.assertRaises(ValueError):enrich_finance(r,{'books_estimate_index':{'8':row}})
 def test_uses_remaining_budget_without_overshoot(self):
  row,full=self.sample();r=NativeReader(self.client(full),limit=0)
  v=enrich_finance(r,{'books_estimate_index':{'8':row}})
  self.assertEqual(r.reads,0);self.assertEqual(v['finance_detail_coverage']['pending'],1)
