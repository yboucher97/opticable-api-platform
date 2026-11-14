from datetime import datetime,timedelta,timezone
import base64
import hashlib
from http.cookies import SimpleCookie
import http.client
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parents[1]/'apps/workflow-api'))
from workflow.automation.acquisition_store import AcquisitionStore
from workflow.automation.action_evidence import ActionEvidence
from workflow.automation.inquiry_lineage import build_inquiry_funnel
from review import Review
import content_variations as content
from private_preview import serve
NOW=datetime.now(timezone.utc)


class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.assets=self.root/'artifacts';self.assets.mkdir();self.db=self.root/'existing.db'
  raw=b'An original useful camera scope draft.';h=hashlib.sha256(raw).hexdigest();(self.assets/'draft.txt').write_bytes(raw)
  self.item={'logical_path':'campaigns/week/camera/ip-cameras/en/linkedin/draft/post.txt','path':'draft.txt','sha256':h,'scope':'live','evidence_ids':['source-native-1']}
  AcquisitionStore(self.db).record('CONTENT_ASSET',self.item,source='platform:business_autopilot',native_id=h,url='https://opticable.ca/',now=NOW)
  with ActionEvidence(self.db).connect() as db:ActionEvidence.setup(db)
  self.review=Review(self.db,self.assets);self.owner={'actor':'owner:opticable-review','expires_at':NOW+timedelta(hours=4)}
 def payload(self,choice='APPROVE',**kwargs):return {'id':self.item['sha256'],'version':self.item['sha256'],'choice':choice,'reason':'Make it shorter','request_id':secrets.token_hex(16),**kwargs}
 def test_all_fields_and_actual_content(self):
  row,raw=self.review.item(self.item['sha256']);self.assertIn(b'useful',raw)
  self.assertEqual(row['service'],'ip-cameras');self.assertEqual(row['language'],'en');self.assertEqual(row['estimated_cost']['internal_incremental'],'0')
  self.assertEqual(len(self.review.catalog(query='camera')),1);self.assertEqual(self.review.catalog(query='missing'),[])
 def test_approve_reject_revision_expiry_and_audit_chain(self):
  p=self.payload();one=self.review.decision(p,self.owner,NOW);self.assertEqual(one,self.review.decision(p,self.owner,NOW));self.assertEqual(self.review.status(self.review.item(self.item['sha256'])[0],NOW),'APPROVE')
  self.assertEqual(self.review.status(self.review.item(self.item['sha256'])[0],NOW+timedelta(hours=3)),'EXPIRED')
  for choice in ['REJECT','REQUEST_REVISION']:
   self.review.decision(self.payload(choice),self.owner,NOW+timedelta(seconds=1));self.assertEqual(self.review.status(self.review.item(self.item['sha256'])[0],NOW+timedelta(seconds=2)),choice)
  plan=ActionEvidence(self.db).get(self.review.action_id({**self.item,'execution_scope':self.review.item(self.item['sha256'])[0]['execution_scope']}));self.assertIsNone(plan['approval_record'])
  with self.assertRaises(ValueError):ActionEvidence.executable(plan,NOW+timedelta(hours=3))
  self.assertEqual(len(self.review.history(self.review.item(self.item['sha256'])[0])),3)
  with sqlite3.connect(self.db) as db:
   with self.assertRaises(sqlite3.IntegrityError):db.execute("delete from action_evidence")
 def test_no_client_actor_scope_expiry_or_authorization(self):
  for key,value in [('actor','owner'),('expires_at','2099-01-01'),('scope','publish'),('execution_authorized',True)]:
   with self.subTest(key=key),self.assertRaises(ValueError):self.review.decision(self.payload(**{key:value}),self.owner,NOW)
  with self.assertRaises(PermissionError):self.review.decision(self.payload(),{**self.owner,'expires_at':NOW},NOW)
  with self.assertRaises(PermissionError):self.review.decision(self.payload(),{**self.owner,'actor':'client-claimed-owner'},NOW)
 def test_never_grants_external_execution_for_any_review_state(self):
  item=self.review.item(self.item['sha256'])[0]
  for choice in ['APPROVE','REJECT','REQUEST_REVISION']:
   self.review.decision(self.payload(choice),self.owner,NOW)
   for operation in ['publish','paid_model','spend','deploy','customer_send']:
    self.assertFalse(self.review.external_authorized(item,operation,NOW));self.assertFalse(self.review.external_authorized(item,operation,NOW+timedelta(days=2)))
 def test_changed_content_cannot_be_approved(self):
  (self.assets/'draft.txt').write_bytes(b'tampered')
  with self.assertRaises(ValueError):self.review.decision(self.payload(),self.owner,NOW)
 def test_http_owner_identity_csrf_and_refresh(self):
  credentials=self.root/'owner.json';credentials.write_text(json.dumps({'username':'opticable-review','password':'fixture-only','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()}))
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  stop=threading.Event();thread=threading.Thread(target=serve,args=(self.assets,credentials,self.review),kwargs={'port':port,'stop_event':stop,'session_seconds':1},daemon=True);thread.start()
  self.addCleanup(stop.set)
  for _ in range(30):
   try:c=http.client.HTTPConnection('127.0.0.1',port,timeout=5);c.request('GET','/review/');r=c.getresponse();r.read();self.assertEqual(r.status,401);break
   except ConnectionRefusedError:time.sleep(.02)
  auth={'Authorization':'Basic '+base64.b64encode(b'opticable-review:fixture-only').decode()}
  c.request('GET','/review/session',headers=auth);r=c.getresponse();cookie=r.getheader('Set-Cookie').split(';')[0];session=json.loads(r.read())
  body=json.dumps(self.payload());base={**auth,'Content-Type':'application/json','Cookie':cookie,'Origin':f'http://127.0.0.1:{port}'}
  c.request('POST','/review/decision',body,base);r=c.getresponse();r.read();self.assertEqual(r.status,403)
  c.request('POST','/review/decision',body,{**base,'X-Review-CSRF':session['csrf']});r=c.getresponse();value=json.loads(r.read());self.assertEqual(r.status,200);self.assertEqual(value['actor'],'owner:opticable-review');self.assertFalse(value['execution_authorized'])
  c.request('POST','/review/session/refresh',headers={**base,'X-Review-CSRF':session['csrf']});r=c.getresponse();self.assertEqual(r.status,200);new_cookie=r.getheader('Set-Cookie').split(';')[0];renewed=json.loads(r.read())
  c.request('POST','/review/decision',json.dumps(self.payload()),{**base,'X-Review-CSRF':session['csrf']});r=c.getresponse();r.read();self.assertEqual(r.status,403)
  time.sleep(1.1)
  c.request('POST','/review/decision',json.dumps(self.payload()),{**base,'Cookie':new_cookie,'X-Review-CSRF':renewed['csrf']});r=c.getresponse();r.read();self.assertEqual(r.status,403)
  c.request('PUT','/review/decision',body,{**base,'X-Review-CSRF':session['csrf']});r=c.getresponse();r.read();self.assertEqual(r.status,405)
  credentials.write_text(json.dumps({'username':'opticable-review','password':'fixture-only','expires_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}))
  c.request('GET','/review/',headers=auth);r=c.getresponse();r.read();self.assertEqual(r.status,410)
  c.close();stop.set();thread.join(2)


class LineageTests(unittest.TestCase):
 def fixture(self):
  attempt='obq_'+'a'*32
  receipt={'provider_receipt_id':'provider-1','inquiry_id':attempt,'test_only':False,'provider_evidence':'native:receipt:1','crm_lead_id':'lead-1','attribution':{'source':'google','campaign_id':'123','provider':'google_ads','account_id':'680','landing_page':'/en/cameras/'}}
  lead={'id':'lead-1','inquiry_id':attempt,'test_only':False,'provider_evidence':'crm:readback:1','qualification':'OWNER_VERIFIED_QUALIFIED','qualification_evidence':'owner:exact-lead-1'}
  return receipt,lead
 def test_duplicate_notification_one_inquiry_and_unique_qualified_lead(self):
  r,l=self.fixture();out=build_inquiry_funnel([r,r],[l]);self.assertEqual(out['observed_unique_inquiries'],1);self.assertEqual(out['verified_qualified_leads'],1);self.assertIsNone(out['recognized_revenue']);self.assertEqual(out['linked'][0]['campaign_identity'],'CAPTURED_UNVERIFIED')
 def test_names_or_email_never_link_and_historic_unknowns_preserved(self):
  r,l=self.fixture();l.pop('inquiry_id');l.update(name='Same Name',email='same@example.invalid');r.update(name='Same Name',email='same@example.invalid')
  out=build_inquiry_funnel([r],[l]);self.assertEqual(out['exact_linked_leads'],0);self.assertTrue(out['historical_unknowns_preserved'])
 def test_native_campaign_scope_and_real_stage_chain(self):
  r,l=self.fixture();campaign={'id':'123','provider':'google_ads','account_id':'680','evidence':'native:campaign-123'}
  out=build_inquiry_funnel([r],[l],[{'id':'deal-1','lead_id':'lead-1','test_only':False,'provider_evidence':'CRM','stage':'Closed Won','stage_evidence':'native:stage'}],[{'id':'q1','deal_id':'deal-1','test_only':False,'provider_evidence':'BOOKS'}],campaigns=[campaign])
  self.assertEqual(out['linked'][0]['campaign_identity'],'NATIVE_VERIFIED');self.assertEqual(out['linked_won_deals'],1);self.assertEqual(out['linked_quotes'],1)
 def test_conflicts_and_tests_stop_without_duplicate_business_effects(self):
  r,l=self.fixture();out=build_inquiry_funnel([r,{**r,'crm_lead_id':'other'}],[l]);self.assertEqual(out['exact_linked_leads'],0)
  out=build_inquiry_funnel([{**r,'test_only':True}],[l]);self.assertEqual(out['observed_unique_inquiries'],0);self.assertEqual(out['provider_writes'],0)


class ContentTests(unittest.TestCase):
 def native(self):return {'collection':{'at':NOW.isoformat(),'period':{'from':'2026-11-05','to':'2026-11-11'}},'snapshots':[{'source':'platform:gsc:query_page','id':'a'*64,'data':{'rows':[{'keys':['commercial security cameras','https://opticable.ca/en/services/security-camera-systems/'],'impressions':74,'clicks':0},{'keys':['audit wifi','https://opticable.ca/fr/checklist-audit-wifi-commercial/'],'impressions':108,'clicks':0}]}}]}
 def test_funnel_separates_observed_traffic_and_unknown_business_outcomes(self):
  from cycle import funnel
  value=funnel(self.native(),{'crm_inventory':{'quotes':101,'recognized_revenue':None}})
  self.assertIsNone(value['traffic']['sessions']);self.assertEqual(value['business_inventory']['quotes'],101);self.assertIsNone(value['qualified_leads'])
 def test_meaningful_new_articles_bounded_intent_and_no_repetition(self):
  first=content.generate(self.native(),{},NOW);self.assertEqual(len(first),4);self.assertTrue(any('AI loss prevention' in r['content'] for r in first))
  hashes=[hashlib.sha256(r['content'].encode()).hexdigest() for r in first]
  second=content.generate(self.native(),{'artifact_hashes':hashes},NOW);self.assertTrue(all(r['service']=='commercial-networking' for r in second))
  hashes += [hashlib.sha256(r['content'].encode()).hexdigest() for r in second]
  self.assertEqual(content.generate(self.native(),{'artifact_hashes':hashes},NOW),[])
 def test_feedback_makes_new_version_without_overwriting_original(self):
  first=content.generate(self.native(),{},NOW);old=next(r for r in first if r['service']=='ai-loss-prevention' and r['language']=='en');h=hashlib.sha256(old['content'].encode()).hexdigest()
  context={'artifact_hashes':[hashlib.sha256(r['content'].encode()).hexdigest() for r in first], 'feedback':[{'service':'ai-loss-prevention','choice':'REQUEST_REVISION','rule':'SHORTER','asset_sha256':h}]}
  new=content.generate(self.native(),context,NOW);candidate=next(r for r in new if r['service']=='ai-loss-prevention' and r['language']=='en');self.assertLess(len(candidate['content']),len(old['content']));self.assertEqual(candidate['revision_of'],h)
 def test_claim_rights_and_duplicate_quality_gate(self):
  for text in ['Save 50% with guaranteed results','A customer story: our client saved money','Review5 stars','ROI of 12','stock photo']:
   with self.subTest(text=text),self.assertRaises(ValueError):content.quality(text,['native'])
  with self.assertRaises(ValueError):content.quality('New original draft',[])
  with self.assertRaises(ValueError):content.quality('Original draft',['source'],licensing='UNKNOWN')
  with self.assertRaises(ValueError):content.quality('Repeated draft',['source'],history=['Repeated draft'])


if __name__=='__main__':unittest.main()
