from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parents[1]/'apps/workflow-api'))
import business_work as work
import business_sources as sources
import content_expansion as content
import runner
from attribution_binding import proposal,verify_readback
from test_business_autopilot import fixtures
from workflow.automation.acquisition_store import AcquisitionStore,digest
from workflow.automation.manager_store import ManagerStore
from review import Review
NOW=datetime(2026,11,14,14,0,tzinfo=timezone.utc)


def business():
    return {'schema':1,'captured_at':NOW.isoformat(),'snapshot_ids':['s1'],
      'mail':{'observed_at':NOW.isoformat(),'coverage':'BOUNDED','inquiries':[{'message_id':'1794236484734162601','account_id':sources.ACCOUNT,'language':'en','received_at':(NOW-timedelta(days=5)).isoformat(),
         'fields':{'company':'TEST ONLY Garage Ltd','name':'Example Contact','email':'garage@example.invalid','service':'Cabling','notes':'Ten workstations; 342 feet stated by customer'}}]},
      'crm':{'observed_at':NOW.isoformat(),'partial':True,'leads':[{'id':'lead1','Company':'TEST ONLY Building Ltd','First_Name':'Example','Last_Name':'Contact'}],
        'tasks':[{'id':'task1','Subject':'Review new inquiry','Due_Date':'2026-10-06','Status':'Not Started','What_Id':{'id':'lead1'}}]},
      'calendar':{'observed_at':NOW.isoformat(),'calendar_id':'info@opticable.ca','events':[{'id':'meeting1','summary':'TEST ONLY partnership meeting','status':'confirmed','start_time':'2026-11-18T13:00:00-05:00','end_time':'2026-11-18T13:20:00-05:00','my_response_status':'needsAction'}]}}


class BusinessTests(unittest.TestCase):
 def test_real_records_create_finished_drafts_scope_agenda_and_exact_task_link(self):
    assets,report=work.generate(business(),{},NOW)
    self.assertEqual(len(report['opportunities']),3);self.assertEqual(len(assets),5)
    self.assertIn('342 feet','\n'.join(x['content'] for x in assets));self.assertTrue(any('0–3 min' in x['content'] for x in assets))
    self.assertTrue(all(x['business_private'] for x in assets));self.assertEqual(report['external_mutations'],0)
    self.assertTrue(any(x.get('reply_status')=='UNKNOWN' for x in report['opportunities']))
 def test_repeated_and_next_day_cycles_do_not_regenerate_actionable_work(self):
    first,report=work.generate(business(),{},NOW);ctx={'artifact_hashes':[sha256(x['content'].encode()).hexdigest() for x in first]}
    self.assertEqual(work.generate(business(),ctx,NOW)[0],[])
    self.assertEqual(work.generate(business(),ctx,NOW+timedelta(hours=12))[0],[])
 def test_stale_failed_sources_dont_claim_current_customer_state(self):
    out,report=work.generate(business(),{},NOW+timedelta(days=2))
    self.assertEqual(report['opportunities'],[]);self.assertEqual(len(report['blocked']),3)
    self.assertTrue(all('/priorities/' in a['logical_path'] for a in out))
 def test_similar_names_do_not_link_task_and_lead(self):
    v=business();v['crm']['tasks'][0]['What_Id']={'id':'other'}
    _,report=work.generate(v,{},NOW);self.assertFalse(any(x['kind']=='OVERDUE_NATIVE_TASK' for x in report['opportunities']))
 def test_synthetic_excluded_but_genuine_fixture_work_not_suppressed(self):
    v=business();v['mail']['inquiries'][0]['fields']['company']='OPTIBRAIN TEST CANARY'
    _,r=work.generate(v,{},NOW);self.assertFalse(any(x['kind']=='INQUIRY_SCOPE_REVIEW' for x in r['opportunities']))
    self.assertFalse(work.synthetic({'Company':'Genuine electrical contractor','Description':'Install lighting fixtures'}))
 def test_numeric_native_ids_fail_instead_of_rounding(self):
    with self.assertRaises(ValueError):work.stable_id(1794236484734162601)
    self.assertEqual(work.stable_id('1794236484734162601'),'1794236484734162601')


class SourceTests(unittest.TestCase):
 def test_rate_limit_stops_without_retry_or_write(self):
    client=Mock();client.request.return_value={'ok':False,'status':429}
    with self.assertRaises(ValueError):sources.Reader(client).get('zohoapis','/crm/v8/Tasks',{'per_page':50})
    self.assertEqual(client.request.call_count,1)
 def test_fixed_read_endpoints_and_total_budget_cannot_be_bypassed(self):
    client=Mock();client.request.return_value={'ok':True,'data':[]};reader=sources.Reader(client)
    for service,path in [('projects','/portal'),('zohoapis','/crm/v8/Leads/1/actions/convert'),('mail','/api/accounts/'+sources.ACCOUNT+'/messages')]:
      with self.assertRaises(PermissionError):reader.get(service,path,{})
    for _ in range(5):reader.get('zohoapis','/crm/v8/Tasks',{'per_page':50})
    with self.assertRaises(PermissionError):reader.get('zohoapis','/crm/v8/Leads',{})
    self.assertTrue(all(c.args[1]=='GET' for c in client.request.call_args_list));self.assertEqual(reader.calls,5)
 def test_native_table_parser_uses_string_detail_identity_and_not_rounded_content_id(self):
    details={'messageId':'1794236484734162601','receivedTime':'1794236484725','fromAddress':'notifications@zohoforms.com','toAddress':'soumissions@opticable.ca'}
    body='<table>'+''.join('<tr><td>'+k+'</td><td>:</td><td>'+v+'</td></tr>' for k,v in [('Company','TEST ONLY Demo'),('Name of the contact','Sample'),('Services','Cabling'),('Description of your needs','Fixtures at ten workstations')])+'</table>'
    parsed=sources.inquiry(details,body);self.assertEqual(parsed['message_id'],details['messageId']);self.assertEqual(parsed['fields']['notes'],'Fixtures at ten workstations')
    self.assertIsNone(sources.inquiry({**details,'fromAddress':'spoof@example.invalid'},body))
 def test_fresh_snapshot_uses_no_provider_and_daily_reservation_survives_interruption(self):
    with tempfile.TemporaryDirectory() as d:
      db=Path(d)/'existing.db';store=AcquisitionStore(db);store.snapshot(sources.SOURCE,'https://www.zohoapis.com/crm/v8/Tasks',business(),NOW)
      ManagerStore(db).receipt('business-source-read','2026-11-14',NOW,{'state':'RESERVED'})
      with patch('workflow.zoho_gateway.ZohoGatewayClient') as client:
       value,state=sources.refresh(db,None,NOW,store);self.assertEqual(state['state'],'CACHED');client.assert_not_called()
       store.snapshot(sources.SOURCE,'https://www.zohoapis.com/crm/v8/Tasks',{**business(),'captured_at':(NOW-timedelta(days=2)).isoformat()},NOW+timedelta(seconds=1))
       value,state=sources.refresh(db,None,NOW,store);self.assertEqual(state['state'],'HELD_PRIOR_DAILY_ATTEMPT');client.assert_not_called()


class NativeMappingTests(unittest.TestCase):
 def fixture(self):
    inquiry='obq_'+'c'*32
    return ({'inquiry_id':inquiry,'provider_receipt_id':'native1','acknowledgement_evidence':'provider:ack1','crm_lead_id':'lead1'},
            {'id':'lead1','Inquiry_ID':None,'First_Source':'historic_unknown','provider_evidence':'native:readback1'},
            [{'api_name':'Inquiry_ID','data_type':'text','length':255,'read_only':False,'field_read_only':False,'operation_type':{'api_update':True}}])
 def test_existing_native_field_maps_exact_attempt_and_first_touch_is_preserved(self):
    r,l,f=self.fixture();p=proposal(r,l,f);self.assertEqual(p['fields'],{'Inquiry_ID':r['inquiry_id']});self.assertNotIn('First_Source',p['fields'])
    self.assertFalse(p['native_schema_change_required']);self.assertFalse(p['execution_authorized'])
    native={**l,**p['fields']};self.assertTrue(verify_readback(p,native));self.assertFalse(verify_readback(p,{**native,'id':'other'}))
    self.assertEqual(proposal(r,native,f)['fields'],{})
 def test_legacy_conflict_unverified_ack_missing_contract_and_name_join_stop(self):
    r,l,f=self.fixture()
    for receipt,lead,fields in [(r,{**l,'Inquiry_ID':'OB-I-LEGACY'},f),({**r,'acknowledgement_evidence':None},l,f),(r,l,[]),(r,{**l,'id':'different','name':'same'},f),(r,l,[{**f[0],'length':10}])]:
      with self.subTest(receipt=receipt),self.assertRaises(ValueError):proposal(receipt,lead,fields)


class ExpandedContentTests(unittest.TestCase):
 def test_private_business_text_is_excluded_from_public_marketing_context(self):
    from cycle import context
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);raw='PRIVATE CUSTOMER DRAFT FOR TEST ONLY';h=sha256(raw.encode()).hexdigest();(p/'customer.txt').write_text(raw)
      db=p/'existing.db';AcquisitionStore(db).record('CONTENT_ASSET',{'path':'customer.txt','logical_path':'business-work/response/customer.txt','sha256':h,'business_private':True,'scope':'live'},source='platform:business_autopilot',native_id=h,url='https://opticable.ca/',now=NOW)
      ctx=context(db,p);self.assertEqual(ctx['prior_texts'],[]);self.assertIn(h,ctx['artifact_hashes'])
 def test_exact_runtime_manifest_rejects_tamper_and_extra_files(self):
    with tempfile.TemporaryDirectory() as d:
      p=Path(d);names=('engine.py','runner.py','content_bank.json','sandbox.py','content_variations.py','cycle.py','review.py','private_preview.py','business_work.py','business_sources.py','content_expansion.py')
      for name in names:
        (p/name).write_text('fixture '+name);(p/name).chmod(0o644)
      (p/'manifest.json').write_text(json.dumps({n:sha256((p/n).read_bytes()).hexdigest() for n in names}))
      (p/'manifest.json').chmod(0o644)
      self.assertEqual(len(runner.verify_runtime(p,require_root=False)),11)
      (p/'business_work.py').write_text('modified')
      with self.assertRaises(ValueError):runner.verify_runtime(p,require_root=False)
 def test_four_distinct_bilingual_finished_packs_and_no_customer_details(self):
    n,_=fixtures();out=content.generate(n,{},NOW);self.assertEqual(len(out),8);self.assertEqual(len({x['service'] for x in out}),4)
    for a in out:
      self.assertGreater(len(a['content'].split()),200);self.assertIn('FAQ',a['content']);self.assertIn('https://opticable.ca/',a['content']);self.assertEqual(a['estimated_incremental_cost'],'0')
    h=[sha256(x['content'].encode()).hexdigest() for x in out]
    self.assertEqual(content.generate(n,{'artifact_hashes':h},NOW+timedelta(days=1)),[])
 def test_feedback_produces_paired_revision_and_preserves_history(self):
    n,_=fixtures();out=content.generate(n,{},NOW);old=out[0];h=sha256(old['content'].encode()).hexdigest()
    ctx={'artifact_hashes':[sha256(x['content'].encode()).hexdigest() for x in out],'feedback':[{'service':old['service'],'language':old['language'],'choice':'REQUEST_REVISION','rule':'SHORTER','asset_sha256':h}]}
    new=content.generate(n,ctx,NOW);self.assertEqual(len(new),1);self.assertEqual(new[0]['revision_of'],h);self.assertLess(len(new[0]['content']),len(old['content']))
 def test_real_sandbox_dispatch_creates_business_work_and_deduplicates(self):
    n,s=fixtures()
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);runtime=root/'runtime';runtime.mkdir();out=root/'out';out.mkdir()
      for name in ('engine.py','runner.py','content_bank.json','cycle.py','content_variations.py','business_work.py','content_expansion.py'):
        shutil.copyfile(ROOT/name,runtime/name)
      shutil.copyfile(ROOT.parents[1]/'apps/workflow-api/workflow/automation/development_sandbox.py',runtime/'sandbox.py')
      request=out/'input.json';ctx={'business_v12':True,'business':business()}
      request.write_text(json.dumps({'native':n,'supplement':s,'context':ctx}));first=runner.run_child(runtime,out,request,NOW)
      self.assertTrue(any('/response-draft/' in x['logical_path'] for x in first));self.assertTrue(any(x.get('recipe')=='service-field-guide' for x in first))
      ctx.update(artifact_hashes=[x['sha256'] for x in first],completion_dates=['2026-11-14'])
      request.write_text(json.dumps({'native':n,'supplement':s,'context':ctx}));second=runner.run_child(runtime,out,request,NOW)
      # Existing V1 intent bank advances to another missing recipe, never repeats.
      self.assertTrue(all(x['sha256'] not in ctx['artifact_hashes'] for x in second));self.assertFalse(any(x.get('business_private') for x in second))


if __name__=='__main__':unittest.main()
