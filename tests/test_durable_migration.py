import copy,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/rebuild'))
from common import RebuildError,digest
from durable_migration import Control,Runner,SCOPES,verify_receipt,approvals,watchdog
from owner_notifications import body_for,OWNER,Mail

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.c=Control(self.root/'actions.db','test-run')
  self.p={'version':1,'execution_id':'test-run','source':{'host':'vps-214ba8cd','ip':'148.113.249.7'},'target':{'host':'vps-f8e9b20e','ip':'15.235.100.76'},'scopes':{s:{'limit':s} for s in SCOPES},'steps':[],'execution_enabled':False,'rollback_verified':False,'source_reboot_fence_verified':False}
  self.r=Runner(self.p,self.c,self.root/'approval.json',self.root/'health.json');self.r.tick()
 def tearDown(self):self.tmp.cleanup()
 def receipt(self,stage='QUEUE_HELD'):
  return {'status':'PASS','execution_id':'test-run','stage':stage,'input_sha256':'in','output_sha256':'f'*64,'source':self.p['source'],'target':self.p['target'],'before_state':{},'after_state':{},'evidence':['independent-provider-GET'],'verified_epoch':time.time()}
 def approval(self):
  a={'execution_id':'test-run','profile_sha256':digest(self.p),'owner_authorization_reference':'actual-owner-message','owner_authorization_sha256':'x'*64,'issued_epoch':time.time()-1,'expires_epoch':time.time()+100,'scopes':{s:{'approved':True,'binding_sha256':digest(self.p['scopes'][s])} for s in SCOPES}}
  f=self.root/'approval.json';f.write_text(json.dumps(a));f.chmod(0o600);return a,f
 def test_prepare_no_effect_without_delivery(self):
  self.assertEqual(self.c.state()['status'],'REQUIRES_OWNER');self.assertEqual(self.c.state()['completed_stages'],['PREPARED'])
  self.assertEqual(self.c.state()['blocker'],'owner_notification_delivery_unverified')
 def test_checkpoint_survives_reopen(self):
  self.c.transition({'evidence':['hash:123']},'test');self.assertEqual(Control(self.c.path,'test-run').state()['evidence'],['hash:123'])
 def test_audit_chains_verify(self):
  from common import database_snapshot
  self.c.transition({'a':1},'test');self.assertGreater(database_snapshot(self.c.path)['audit_chains_verified'],0)
 def test_deduplicated_alert_intent(self):
  self.assertTrue(self.c.alert_intent('incident','hash')[1]);self.assertFalse(Control(self.c.path,'test-run').alert_intent('incident','hash')[1])
 def test_no_completion_from_exit_code(self):
  bad=self.receipt();bad['evidence']=[]
  with self.assertRaises(RebuildError):verify_receipt(bad,self.p,'QUEUE_HELD','in')
 def test_wrong_source_rejected(self):
  bad=self.receipt();bad['source']={'host':'wrong'}
  with self.assertRaises(RebuildError):verify_receipt(bad,self.p,'QUEUE_HELD','in')
 def test_wrong_run_rejected(self):
  bad=self.receipt();bad['execution_id']='other'
  with self.assertRaises(RebuildError):verify_receipt(bad,self.p,'QUEUE_HELD','in')
 def test_stale_receipt_rejected(self):
  bad=self.receipt();bad['verified_epoch']-=121
  with self.assertRaises(RebuildError):verify_receipt(bad,self.p,'QUEUE_HELD','in')
 def test_future_receipt_rejected(self):
  bad=self.receipt();bad['verified_epoch']+=30
  with self.assertRaises(RebuildError):verify_receipt(bad,self.p,'QUEUE_HELD','in')
 def test_verified_receipt(self):self.assertEqual(verify_receipt(self.receipt(),self.p,'QUEUE_HELD','in')['status'],'PASS')
 def test_eight_scopes_independent(self):
  a,f=self.approval()
  for s in SCOPES:
   with self.subTest(scope=s):
    bad=copy.deepcopy(a);bad['scopes'][s]['approved']=False;f.write_text(json.dumps(bad))
    with self.assertRaises(RebuildError):approvals(self.p,f)
 def test_stale_approval(self):
  a,f=self.approval();a['expires_epoch']=time.time()-1;f.write_text(json.dumps(a))
  with self.assertRaises(RebuildError):approvals(self.p,f)
 def test_changed_profile_approval(self):
  a,f=self.approval();p=copy.deepcopy(self.p);p['execution_enabled']=True
  with self.assertRaises(RebuildError):approvals(p,f)
 def test_scope_binding_mismatch(self):
  a,f=self.approval();a['scopes']['dns_cutover']['binding_sha256']='other';f.write_text(json.dumps(a))
  with self.assertRaises(RebuildError):approvals(self.p,f)
 def test_overlong_approval(self):
  a,f=self.approval();a['expires_epoch']=time.time()+86401;f.write_text(json.dumps(a))
  with self.assertRaises(RebuildError):approvals(self.p,f)
 def test_broad_approval_permissions_rejected(self):
  a,f=self.approval();f.chmod(0o644)
  with self.assertRaises(RebuildError):approvals(self.p,f)
 def test_watchdog_detects_stall_without_resuming(self):
  self.c.transition({'hold_started_epoch':time.time()-3601,'runner_heartbeat_epoch':0},'test')
  r=watchdog(self.c,self.p,{'checked_epoch':time.time(),'status':'PASS'})
  self.assertIn('CRITICAL_hold_limit_reached',r['issues']);self.assertIn('runner_heartbeat_stale',r['issues']);self.assertEqual(self.c.state()['authority'],'OLD')
 def setup_stage(self,old=None,retry='NEVER'):
  self.c.transition({'completed_stages':['PREPARED','APPROVED'],'current_stage':'APPROVED','status':'APPROVED','last_output_sha256':None},'test')
  step={'stage':'QUEUE_HELD','reviewed':True,'retry':retry,'timeout_seconds':60,'execute':{},'verify':{}}
  self.p['steps']=[step]
  self.c.transition({'profile_sha256':digest(self.p)},'test_profile')
  inputs=digest({'profile':digest(self.p),'previous_verified_output':None,'stage':'QUEUE_HELD'})
  if old:self.c.save_attempt('QUEUE_HELD',{'attempt':old,'input_sha256':inputs,'state':'ATTEMPTED','at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()})
  return step,inputs
 def test_lost_ack_never_reexecutes_provider(self):
  step,inputs=self.setup_stage(1)
  with patch.object(self.r,'gates'),patch.object(self.r,'readback',side_effect=RebuildError('unknown')),patch.object(self.r,'execute') as execute:
   self.r.tick();execute.assert_not_called();self.assertIn('uncertain_effect',self.c.state()['blocker'])
 def test_lost_ack_verified_reconciles_without_write(self):
  step,inputs=self.setup_stage(1);receipt=self.receipt();receipt['input_sha256']=inputs
  with patch.object(self.r,'gates'),patch.object(self.r,'readback',return_value=receipt),patch.object(self.r,'execute') as execute:
   self.r.tick();execute.assert_not_called();self.assertIn('QUEUE_HELD',self.c.state()['completed_stages'])
 def test_local_retry_bounded(self):
  self.setup_stage(3,'IDEMPOTENT_LOCAL')
  with patch.object(self.r,'gates'),patch.object(self.r,'readback',side_effect=RebuildError('unknown')),patch.object(self.r,'execute') as execute:
   self.r.tick();execute.assert_not_called();self.assertIn('bounded_retries',self.c.state()['blocker'])
 def test_single_execution_lock(self):
  with self.c.exclusive():
   with self.assertRaises(RebuildError):
    with Control(self.c.path,'test-run').exclusive():pass
 def test_customer_destination_impossible_in_body(self):
  content=body_for('TEST','test-run',{'current_stage':'PREPARED','authority':'OLD'},'/home/optibrain/optibrain-migration-progress-20261101.txt');self.assertIn('single authorized owner-only',content)
  with self.assertRaises(RebuildError):body_for('CUSTOMER','test-run',{},'other')
 def test_mail_transport_rejects_customer(self):
  mail=object.__new__(Mail)
  with self.assertRaises(RebuildError):mail.request('POST','/api/accounts/1083319000000008002/messages',body={'toAddress':'customer@example.com'})
 def test_mail_transport_rejects_other_effect(self):
  mail=object.__new__(Mail)
  with self.assertRaises(RebuildError):mail.request('DELETE','/api/accounts/1083319000000008002/messages')

 def notification_policy(self):
  import owner_notifications as n
  f=self.root/'notify-policy.json';f.write_text(json.dumps({'recipient':OWNER,'account_id':n.ACCOUNT,'authority_reference':n.AUTHORITY_REFERENCE,'expires_epoch':time.time()+1000,'code_sha256':n.file_hash(n.__file__),'report_reference':'/home/optibrain/optibrain-migration-progress-20261101.txt'}));f.chmod(0o600);return f
 def test_owner_send_has_explicit_canonical_approval_and_delivery(self):
  import owner_notifications as n
  calls=[]
  class Fake:
   def request(self,method,path,**kw):
    calls.append(method)
    return {'accountId':n.ACCOUNT,'primaryEmailAddress':OWNER} if method=='GET' else {'messageId':'123'}
  delivered={'state':'DELIVERED','message_id':'456','evidence':'Provider Inbox readback'}
  with patch.object(n,'delivery',return_value=delivered):
   result=n.notify(self.c,self.p,self.notification_policy(),'TEST','one-test',mail_factory=Fake,delays=(0,))
   again=n.notify(self.c,self.p,self.notification_policy(),'TEST','one-test',mail_factory=Fake,delays=(0,))
  self.assertEqual(calls.count('POST'),1);self.assertEqual(result['state'],'DELIVERED');self.assertEqual(again['state'],'DELIVERED')
  action=self.c.audit.store.get('migration-owner-alert:test-run:one-test');self.assertEqual(action['status'],'SUCCEEDED');self.assertTrue(action['approval_record'])
 def test_lost_mail_ack_is_get_only_reconciled(self):
  import owner_notifications as n
  calls=[]
  class Fake:
   def request(self,method,path,**kw):
    calls.append(method)
    if method=='POST':raise TimeoutError('lost acknowledgement')
    return {'accountId':n.ACCOUNT,'primaryEmailAddress':OWNER}
  policy=self.notification_policy()
  with self.assertRaises(TimeoutError):n.notify(self.c,self.p,policy,'TEST','lost-ack',mail_factory=Fake,delays=(0,))
  with patch.object(n,'delivery',return_value={'state':'DELIVERED','message_id':'found'}):
   self.assertEqual(n.notify(self.c,self.p,policy,'TEST','lost-ack',mail_factory=Fake,delays=(0,))['state'],'DELIVERED')
  self.assertEqual(calls.count('POST'),1)
 def test_notifier_account_identity_blocks_transport(self):
  import owner_notifications as n
  calls=[]
  class Fake:
   def request(self,method,path,**kw):
    calls.append(method);return {'accountId':'wrong','primaryEmailAddress':OWNER}
  with self.assertRaises(RebuildError):n.notify(self.c,self.p,self.notification_policy(),'TEST','wrong-account',mail_factory=Fake,delays=(0,))
  self.assertNotIn('POST',calls)

 def test_filtered_received_owner_message_is_delivery(self):
  import owner_notifications as n
  class Fake:
   def request(self,method,path,**kw):
    if path.endswith('/folders'):return [{'folderId':'1083319000000008014','folderName':'Inbox'},{'folderId':'1083319000000633001','folderName':'OptiBrain'},{'folderId':'other','folderType':'Inbox','folderName':'Other'}]
    if path.endswith('/search'):return [{'folderId':'1083319000000633001','messageId':'received','subject':'unique'}]
    return {'subject':'unique','fromAddress':OWNER,'toAddress':OWNER,'receivedTime':str(int(time.time()*1000))}
  result=n.delivery(Fake(),'unique',time.time()-5)
  self.assertEqual(result['state'],'DELIVERED');self.assertEqual(result['message_id'],'received')
 def test_sent_copy_does_not_prove_delivery(self):
  import owner_notifications as n
  class Fake:
   def request(self,method,path,**kw):
    if path.endswith('/folders'):return [{'folderId':'1083319000000008014','folderName':'Inbox'}]
    return [{'folderId':'1083319000000008022','messageId':'outgoing','subject':'unique'}]
  self.assertIsNone(n.delivery(Fake(),'unique',time.time()-5))

 def test_unissued_approval_is_owner_gate(self):
  a,f=self.approval();a['issued_epoch']=None;a['expires_epoch']=None;f.write_text(json.dumps(a))
  with self.assertRaises(RebuildError):approvals(self.p,f)
 def test_reconcile_after_approval_expiry_does_not_need_new_effect_authority(self):
  step,inputs=self.setup_stage(1);receipt=self.receipt();receipt['input_sha256']=inputs
  with patch.object(self.r,'gates',side_effect=RebuildError('expired')),patch.object(self.r,'readback',return_value=receipt),patch.object(self.r,'execute') as execute:
   self.r.tick();execute.assert_not_called();self.assertIn('QUEUE_HELD',self.c.state()['completed_stages'])
 def test_late_hold_readback_does_not_extend_deadline(self):
  step,inputs=self.setup_stage(1);row=self.c.attempt('QUEUE_HELD');start=time.time()-3500
  row['at']=__import__('datetime').datetime.fromtimestamp(start,__import__('datetime').timezone.utc).isoformat();self.c.save_attempt('QUEUE_HELD',row)
  receipt=self.receipt();receipt['input_sha256']=inputs
  with patch.object(self.r,'readback',return_value=receipt):self.r.tick()
  self.assertLessEqual(self.c.state()['hold_started_epoch'],start+0.001)

 def test_source_report_has_fixed_safe_envelope(self):
  from source_status import validate_report
  self.assertTrue(validate_report(b'OPTIBRAIN MIGRATION PROGRESS\nStatus: PARTIAL'))
  for data in [b'Other text',b'OPTIBRAIN MIGRATION PROGRESS'+b'a'*65536,b'OPTIBRAIN MIGRATION PROGRESS\x00',b'OPTIBRAIN MIGRATION PROGRESS\nBearer secretvalue']:
   with self.subTest(data=data[:30]):
    with self.assertRaises(AssertionError):validate_report(data)

 def test_forms_hold_alone_starts_global_maintenance_clock(self):
  self.c.transition({'forms_hold_started_epoch':time.time()-3601},'test')
  value=watchdog(self.c,self.p,{'checked_epoch':time.time(),'status':'PASS'})
  self.assertIn('CRITICAL_hold_limit_reached',value['issues'])

 def test_detached_stage_survives_runner_disconnect_without_parallel_attempt(self):
  step,inputs=self.setup_stage(1,'IDEMPOTENT_LOCAL');row=self.c.attempt('QUEUE_HELD');row['unit']='fixture-detached-stage';self.c.save_attempt('QUEUE_HELD',row)
  with patch.object(self.r,'unit_running',return_value=True),patch.object(self.r,'execute') as execute,patch.object(self.r,'readback') as readback:
   self.r.tick();execute.assert_not_called();readback.assert_not_called()
  self.assertEqual(self.c.attempt('QUEUE_HELD')['attempt'],1)

if __name__=='__main__':unittest.main(verbosity=2)
