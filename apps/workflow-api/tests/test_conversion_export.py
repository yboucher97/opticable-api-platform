from copy import deepcopy
from datetime import datetime,timezone
from io import BytesIO
import json,unittest
from unittest.mock import Mock,patch
from workflow.automation import conversion_export as c
from test_marketing_attribution import fixture

NOW=datetime(2026,10,3,14,tzinfo=timezone.utc)

def control():
 d={'account_id':'6808491878','action_id':'123456','type':'UPLOAD_CLICKS','status':'ENABLED',
  'primary_for_goal':False,'used_in_custom_goal':False,'native_verification_receipt':'test-fixture-native-receipt',
  'verified_at':NOW.isoformat(),'value_basis':'NO_VALUE','currency_code':'CAD',
  'always_use_default_value':False,'default_value':1}
 return {'schema':1,'enabled':False,'eligible_after':'2026-10-03T00:00:00Z','expires_at':'2026-11-03T00:00:00Z',
  'destinations':{'qualified_lead':d,'estimate_accepted':{**d,'value_basis':'ACCEPTED_ESTIMATE_GROSS'},
   'invoice_paid':{**d,'value_basis':'FULLY_PAID_INVOICE_GROSS'}}}

def event(kind='qualified_lead',rid='3'):
 return {'kind':kind,'record_id':rid,'version':1,'occurred_at':NOW.isoformat(),
  'proof':{'native_record_id':rid,'verified':True,'immutable_source_sha256':'f'*64,'timestamp_basis':'CRM_UI_TRANSITION',
   'credits_refunds_checked':True},'consent':{'ad_user_data':'GRANTED','evidence':'test consent receipt'},
  'click':{'gclid':'UNIT_SYNTHETIC_ID_ONLY','provenance':'GENUINE_PROVIDER_CLICK','test_only':False,
   'immutable_source_sha256':'e'*64,'captured_at':'2026-10-03T01:00:00Z'}}

class ConversionPlanTests(unittest.TestCase):
 def plan(self,e=None,s=None,p=None):return c.build_plan(e or event(),s or fixture(),p or control(),now=NOW)
 def test_qualified_no_invented_money_or_pii(self):
  p=self.plan();payload=p['body']['events'][0]
  self.assertEqual(payload['conversionValue'],0);self.assertEqual(payload['currency'],'CAD');self.assertNotIn('userData',payload)
  self.assertEqual(payload['eventSource'],'WEB');self.assertTrue(p['body']['validateOnly'])
 def test_positive_lead_default_is_overridden_with_zero(self):
  p=control();p['destinations']['qualified_lead']['default_value']=999
  self.assertEqual(self.plan(p=p)['body']['events'][0]['conversionValue'],0)
 def test_destination_forcing_default_value_denies_all_outcomes(self):
  for kind,rid in [('qualified_lead','3'),('estimate_accepted','8'),('invoice_paid','11')]:
   p=control();p['destinations'][kind]['always_use_default_value']=True
   with self.subTest(kind=kind),self.assertRaises(ValueError):self.plan(event(kind,rid),p=p)
 def test_unknown_lead_currency_denied(self):
  p=control();p['destinations']['qualified_lead'].pop('currency_code')
  with self.assertRaises(ValueError):self.plan(p=p)
 def test_identity_excludes_timestamp_and_value(self):
  self.assertEqual(c.event_key(event()),c.event_key({**event(),'occurred_at':'2026-10-03T13:00:00Z','value':999}))
 def test_independent_outcomes_have_distinct_identity(self):
  self.assertNotEqual(c.event_key(event()),c.event_key(event('estimate_accepted','8')))
 def test_test_owned_ancestor_denies_export(self):
  for name in ('accounts','leads','deals'):
   with self.subTest(name=name):
    s=fixture();s[name][0]['OptiBrain_Test']=True
    with self.assertRaises(ValueError):self.plan(s=s)
 def test_synthetic_click_or_missing_privacy_denied(self):
  for field,value in [('provenance','SYNTHETIC'),('test_only',True),('gclid',''),('immutable_source_sha256','')]:
   e=event();e['click'][field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):self.plan(e=e)
  for value in ({},{'ad_user_data':'DENIED','evidence':'x'},{'ad_user_data':'GRANTED'}):
   with self.subTest(consent=value),self.assertRaises(ValueError):self.plan(e={**event(),'consent':value})
 def test_wrong_destination_or_bidding_use_denied(self):
  for k,v in [('account_id','1'),('status','REMOVED'),('type','WEBPAGE_CODELESS'),('primary_for_goal',True),('used_in_custom_goal',True)]:
   p=control();p['destinations']['qualified_lead'][k]=v
   with self.subTest(k=k),self.assertRaises(ValueError):self.plan(p=p)
 def test_future_old_unaware_or_before_activation_denied(self):
  for at in ('2026-10-04T00:00:00Z','2026-01-01T00:00:00Z','2026-10-03','2026-10-02T01:00:00Z'):
   with self.subTest(at=at),self.assertRaises(ValueError):self.plan(e={**event(),'occurred_at':at})
 def test_created_time_is_not_outcome_time(self):
  e=event();e['proof']['timestamp_basis']='RECORD_CREATED_TIME'
  with self.assertRaises(ValueError):self.plan(e=e)
 def test_braid_waits_for_compatible_destination(self):
  e=event();e['click']['wbraid']=e['click'].pop('gclid')
  with self.assertRaises(ValueError):self.plan(e=e)
  p=control();p['destinations']['qualified_lead']['braid_supported']=True
  self.assertIn('wbraid',self.plan(e=e,p=p)['body']['events'][0]['adIdentifiers'])
 def test_accepted_and_paid_values_distinct_defined_basis(self):
  s=fixture();s['books_estimate_index']['8'].update(total='250',currency_code='CAD')
  self.assertEqual(self.plan(event('estimate_accepted','8'),s)['body']['events'][0]['conversionValue'],250)
  self.assertEqual(self.plan(event('invoice_paid','11'))['body']['events'][0]['conversionValue'],200)
 def test_unlinked_finance_wrong_customer_no_value(self):
  for change in ('deal','customer'):
   s=fixture()
   if change=='deal':s['finance_invoices'][0]['Potential_Name']=None
   else:s['books_invoices'][0]['customer_id']='90'
   with self.subTest(change=change),self.assertRaises(ValueError):self.plan(event('invoice_paid','11'),s)
 def test_recurring_payment_not_new_acquisition(self):
  s=fixture();s['books_invoices'][0]['recurring_invoice_id']='12'
  with self.assertRaises(ValueError):self.plan(event('invoice_paid','11'),s)
 def test_credits_refunds_or_partial_payment_denied(self):
  e=event('invoice_paid','11');e['proof']['credits_refunds_checked']=False
  with self.assertRaises(ValueError):self.plan(e)
  s=fixture();s['books_invoices'][0]['balance']='10'
  with self.assertRaises(ValueError):self.plan(event('invoice_paid','11'),s)
 def test_destination_verification_cannot_be_permanent(self):
  p=control();p['destinations']['qualified_lead']['verified_at']='2026-01-01T00:00:00Z'
  with self.assertRaises(ValueError):self.plan(p=p)
 def test_nonroot_cannot_obtain_upload_authority(self):
  with patch.object(c.os,'geteuid',return_value=1000),self.assertRaises(PermissionError):c.trusted_control()
 def test_stop_precedes_token_and_transport(self):
  p=control();plan=self.plan(p=p);oauth=Mock();client=c.DataManager(oauth)
  with patch.object(c,'trusted_control',return_value=p),patch.object(c,'verify_plan'),patch.object(c,'destination'),patch('httpx.post') as post:
   with self.assertRaises(ValueError):client.ingest(plan,live=True)
   oauth.access_token.assert_not_called();post.assert_not_called()
 def test_forged_plan_denied_before_token(self):
  client=c.DataManager(Mock())
  with patch.object(c,'trusted_control',return_value=control()),patch.object(c,'verify_plan',side_effect=ValueError('different native evidence')):
   with self.assertRaises(ValueError):client.ingest(self.plan(),live=True)
   client.oauth.access_token.assert_not_called()
 def test_live_family_requires_one_exact_event_and_separate_enable(self):
  p=control();p['enabled']=True;d=p['destinations']['qualified_lead'];d['local_enabled']=True
  p['validated_families']={'qualified_lead':{'passed':True,'destination_sha256':c.digest(d)}}
  client=c.DataManager(Mock())
  for allowed in ([],['0'*64],['0'*64,'1'*64]):
   d['allowed_event_keys']=allowed;p['validated_families']['qualified_lead']['destination_sha256']=c.digest(d)
   with self.subTest(allowed=allowed),patch.object(c,'trusted_control',return_value=p),patch.object(c,'verify_plan'),self.assertRaises(ValueError):
    client.authorize(self.plan(p=p),live=True)
  d['allowed_event_keys']=[c.event_key(event())];p['validated_families']['qualified_lead']['destination_sha256']=c.digest(d)
  with patch.object(c,'trusted_control',return_value=p),patch.object(c,'verify_plan'):
   self.assertEqual(client.authorize(self.plan(p=p),live=True),p)
  d['local_enabled']=False;p['validated_families']['qualified_lead']['destination_sha256']=c.digest(d)
  with patch.object(c,'trusted_control',return_value=p),patch.object(c,'verify_plan'),self.assertRaises(ValueError):
   client.authorize(self.plan(p=p),live=True)
 def test_central_conversion_grant_is_exact_and_one_use(self):
  client=c.DataManager(Mock());p=self.plan();client.authorize=Mock();body={**p['body'],'validateOnly':False}
  with c.conversion_scope(client,p,live=True,claim={'key':p['key'],'payload_hash':p['payload_hash']}):
   with self.assertRaises(ValueError):c.check_transport(client,'google_datamanager','POST','/v1/campaigns',body,{})
   self.assertTrue(c.check_transport(client,'google_datamanager','POST','/v1/events:ingest',body,{}))
   with self.assertRaises(ValueError):c.check_transport(client,'google_datamanager','POST','/v1/events:ingest',body,{})
   self.assertTrue(c.check_transport(client,'google_datamanager','POST','/v1/events:ingest',body,{},recheck=True))
  self.assertFalse(c.check_transport(client,'google_datamanager','POST','/v1/events:ingest',body,{}))
 def test_direct_transport_without_export_context_denied(self):
  from workflow.automation.mutation_control import require_business_transport
  client=c.DataManager(Mock())
  with patch('workflow.automation.lifecycle_control.check_transport',return_value=False),patch('workflow.automation.customer_send_control.check_transport',return_value=False),patch('workflow.automation.mutation_control.read_control',side_effect=ValueError('no authority')):
   with self.assertRaises(ValueError):require_business_transport(client,'google_datamanager','POST','/v1/events:ingest',self.plan()['body'])
   client.oauth.access_token.assert_not_called()

class Missing(Exception):
 response={'Error':{'Code':'NoSuchKey'}}
class S3:
 def __init__(self):self.objects={}
 def get_object(self,*,Bucket,Key):
  if Key not in self.objects:raise Missing()
  return {'Body':BytesIO(self.objects[Key])}
 def put_object(self,*,Bucket,Key,Body,ContentType,IfNoneMatch):
  if Key in self.objects:raise ValueError('Conditional creation denied')
  assert IfNoneMatch=='*';self.objects[Key]=Body

class ConversionEffectTests(unittest.TestCase):
 def setUp(self):
  self.plan=c.build_plan(event(),fixture(),control(),now=NOW);self.claims=c.ConversionClaims(S3());self.client=Mock()
  self.client.ingest.return_value={'requestId':'request-one'}
 def test_validation_has_no_offhost_claim_or_effect(self):
  r=c.export_one(self.plan,self.client,None);self.assertEqual(r['uploads'],0)
  self.assertEqual(self.claims.client.objects,{});self.client.ingest.assert_called_once_with(self.plan,live=False)
 def test_replay_after_success_is_reconciliation_only(self):
  self.assertEqual(c.export_one(self.plan,self.client,self.claims,live=True)['uploads'],1)
  self.assertEqual(c.export_one(self.plan,self.client,self.claims,live=True)['uploads'],0)
  self.client.ingest.assert_called_once()
 def test_lost_ack_never_reposts_after_local_state_loss(self):
  self.client.ingest.side_effect=TimeoutError('provider may have committed')
  with self.assertRaises(ValueError):c.export_one(self.plan,self.client,self.claims,live=True)
  restored=c.ConversionClaims(self.claims.client)
  self.assertEqual(c.export_one(self.plan,self.client,restored,live=True)['state'],'RECONCILIATION_REQUIRED')
  self.client.ingest.assert_called_once()
 def test_changed_value_same_identity_holds(self):
  c.export_one(self.plan,self.client,self.claims,live=True)
  with self.assertRaises(ValueError):c.export_one({**self.plan,'payload_hash':'0'*64},self.client,self.claims,live=True)
  self.client.ingest.assert_called_once()
 def test_claim_failure_prevents_provider(self):
  self.claims.put=Mock(side_effect=TimeoutError())
  with self.assertRaises(TimeoutError):c.export_one(self.plan,self.client,self.claims,live=True)
  self.client.ingest.assert_not_called()
 def test_own_kill_before_claim_preserves_other_families(self):
  self.client.authorize.side_effect=ValueError('export stopped')
  with self.assertRaises(ValueError):c.export_one(self.plan,self.client,self.claims,live=True)
  self.assertEqual(self.claims.client.objects,{});self.client.ingest.assert_not_called()
 def test_provider_processing_needs_destination_and_one_event(self):
  row={'destination':self.plan['body']['destinations'][0],'requestStatus':'SUCCESS','eventsIngestionStatus':{'recordCount':'1'}}
  self.client.status.return_value={'requestStatusPerDestination':[row]}
  self.assertEqual(c.reconcile(self.plan,self.client,'request-one')['state'],'PROVIDER_PROCESSING_PASS')
  for change in ({'requestStatus':'PROCESSING'},{'warningInfo':{'warningCounts':[1]}},{'errorInfo':{'errorCounts':[1]}}):
   self.client.status.return_value={'requestStatusPerDestination':[{**row,**change}]}
   self.assertEqual(c.reconcile(self.plan,self.client,'request-one')['state'],'RECONCILIATION_REQUIRED')
 def test_wrong_action_diagnostics_denied(self):
  self.client.status.return_value={'requestStatusPerDestination':[{'destination':{'productDestinationId':'different'},'requestStatus':'SUCCESS'}]}
  with self.assertRaises(ValueError):c.reconcile(self.plan,self.client,'request-one')

if __name__=='__main__':unittest.main()
