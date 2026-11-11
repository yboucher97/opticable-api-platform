"""Closed pre-NEW windows retain evidence, action IDs, clocks and alert history."""
import copy,json,sys,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/rebuild'))
from common import atomic_json,digest,file_hash,RebuildError
from durable_migration import Control,Runner,SCOPES,profile_binding,stamp
from migration_authority import issue,window_changes
import migration_adapters as adapters
from test_migration_executor import Fixture

class WindowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.c=Control(self.root/'actions.db','fixture-window-root')
  self.p={'version':2,'execution_id':self.c.run_id,'source':{'host':'OLD','ip':'148.113.249.7'},
   'target':{'host':'NEW','ip':'15.235.100.76'},'production_sha':'b'*40,
   'scopes':{s:{'action':s} for s in SCOPES},'steps':[],
   'runtime':{'windowed_maintenance_evidence':True},'code_sha256':{},
   'hold_max_seconds':3600,'rollback_review_seconds':2700,'business_automation':'OFF'}
  self.c.transition({'status':'PREPARED','authority':'OLD','completed_stages':['PREPARED'],
   'forms_hold_started_epoch':None,'hold_started_epoch':None},'fixture')
  self.owner=self.root/'owner.txt';self.owner.write_text('FIXTURE_ONLY: approve independent reviewed scopes and both pages ready.');self.owner.chmod(0o600)
  self.decisions=self.root/'decisions.json'
  atomic_json(self.decisions,{s:{'approved':s!='crm_notification_recreation',
   'conditional_rollback_approved':s=='source_freeze_final_sync',
   'conditional_OLD_queue_resume_approved':s=='safe_queue_observer_resume'} for s in SCOPES})
 def tearDown(self):self.tmp.cleanup()
 def receipt(self,offset=0):
  return issue(self.p,self.owner,'FIXTURE_ONLY_NO_LIVE_AUTHORITY_'+str(offset),self.decisions,profile_binding(self.p),now=time.time()-2+offset)
 def begin(self,out):
  snapshot=self.root/('prior-'+str(out['issued_epoch'])+'.json');atomic_json(snapshot,self.c.state())
  changes=window_changes(self.p,self.c,out,snapshot)
  self.c.transition(changes,'fixture_actual_authorization')
  atomic_json(self.root/'approval.json',out);return changes
 def close(self,**changes):
  proof={'status':'CLOSED_VERIFIED_PRE_NEW_ROLLBACK','source':{'fenced':False,'state':{'event':'ROLLED_BACK','new_data_observed':False}},
   'NEW_never_released':True,'Worker_original':True,'DNS':{'content':'148.113.249.7'},
   'queue':{'settings':{'delivery_paused':False}},'forms':{x:{'http_status':200,'live_form_elements':1,'maintenance_message_present':False} for x in ('FR','EN')}}
  proof.update(changes);path=self.root/'closed.json';atomic_json(path,proof)
  self.c.transition({'status':'ROLLED_BACK','authority':'OLD','forms_hold_started_epoch':None,
   'hold_started_epoch':None,'maintenance_closeout':{'path':str(path),'sha256':file_hash(path)}},'fixture_closeout')
  return path
 def test_window_namespace_requires_explicit_reviewed_configuration(self):
  self.p['runtime']['windowed_maintenance_evidence']=False
  with self.assertRaisesRegex(RebuildError,'windowed_evidence_configuration_not_reviewed'):
   self.begin(self.receipt())
 def test_active_clock_prevents_new_authority_and_does_not_change_state(self):
  self.c.transition({'forms_hold_started_epoch':time.time()-10},'fixture_held');before=self.c.state()
  with self.assertRaisesRegex(RebuildError,'previous_maintenance_window_not_closed'):self.begin(self.receipt())
  self.assertEqual(self.c.state(),before)
 def test_new_window_preserves_old_attempt_and_alert_ledger(self):
  self.c.save_attempt('QUEUE_HELD',{'attempt':1,'state':'VERIFIED','input_sha256':'old'})
  self.c.alert_intent('original-owner-incident','original-body')
  before=self.c.attempt('QUEUE_HELD');old_id=self.c.action_id('migration-provider','queue_hold')
  self.begin(self.receipt());new_id=self.c.action_id('migration-provider','queue_hold')
  self.assertNotEqual(old_id,new_id);self.assertIsNone(self.c.attempt('QUEUE_HELD'))
  self.c.save_attempt('QUEUE_HELD',{'attempt':1,'state':'ATTEMPTED','input_sha256':'new'})
  with self.c.connect() as db:
   prior=json.loads(db.execute("SELECT state_json FROM migration_attempts WHERE stage='QUEUE_HELD'").fetchone()[0])
   self.assertEqual(prior,before);self.assertEqual(db.execute('SELECT count(*) FROM migration_attempts').fetchone()[0],2)
   self.assertEqual(db.execute('SELECT count(*) FROM migration_alerts').fetchone()[0],1)
  self.assertEqual(self.c.run_id,'fixture-window-root')
 def test_closed_window_cannot_mint_more_receipts_from_same_owner_reference(self):
  out=self.receipt();self.begin(out);self.close()
  reused=copy.deepcopy(out);reused['issued_epoch']+=1
  with self.assertRaisesRegex(RebuildError,'fresh_window_owner_authorization_reference_required'):
   self.begin(reused)
 def test_missing_closeout_blocks_rearm_after_source_freeze(self):
  self.c.transition({'completed_stages':['PREPARED','APPROVED','SOURCE_FROZEN'],'status':'ROLLED_BACK'},'fixture')
  with self.assertRaises((RebuildError,FileNotFoundError,IsADirectoryError)):self.begin(self.receipt())
 def test_changed_closeout_blocks_new_window(self):
  self.c.transition({'completed_stages':['PREPARED','SOURCE_FROZEN']},'fixture')
  path=self.close();path.write_text('{}')
  with self.assertRaisesRegex(RebuildError,'closed_window_proof_changed'):self.begin(self.receipt())
 def test_NEW_boundary_never_rearms(self):
  self.c.transition({'completed_stages':['PREPARED','INTAKE_RELEASED']},'fixture');self.close()
  with self.assertRaisesRegex(RebuildError,'NEW_boundary_forbids_window_rearm'):self.begin(self.receipt())
 def test_newer_NEW_data_in_closeout_never_rearms(self):
  self.c.transition({'completed_stages':['PREPARED','SOURCE_FROZEN']},'fixture')
  self.close(source={'fenced':False,'state':{'event':'ROLLED_BACK','new_data_observed':True}})
  with self.assertRaisesRegex(RebuildError,'closed_pre_NEW_rollback_not_independently_verified'):self.begin(self.receipt())
 def test_both_conditional_permissions_required(self):
  out=self.receipt();out['scopes']['source_freeze_final_sync']['conditional_rollback_approved']=False
  with self.assertRaisesRegex(RebuildError,'conditional_rollback_permissions_required'):self.begin(out)
 def test_evidence_and_actions_are_separate_for_two_closed_windows(self):
  first=self.begin(self.receipt());first_id=self.c.action_id('migration-provider','queue_hold')
  with patch.object(adapters,'CONTROL',self.root),patch.object(adapters,'ROOT',self.root/'evidence'):
   one=adapters.Live(self.p).root;one.joinpath('QUEUE_HELD.json').write_text('preserved-first-intent')
   self.c.transition({'completed_stages':['PREPARED','APPROVED','SOURCE_FROZEN']},'fixture');self.close()
   second=self.begin(self.receipt(1));two=adapters.Live(self.p).root
  self.assertNotEqual(first['maintenance_window_id'],second['maintenance_window_id'])
  self.assertNotEqual(one,two);self.assertEqual((one/'QUEUE_HELD.json').read_text(),'preserved-first-intent')
  self.assertFalse((two/'QUEUE_HELD.json').exists())
  self.assertNotEqual(first_id,self.c.action_id('migration-provider','queue_hold'))
 def test_closed_Forms_receipt_cannot_be_reused_in_a_fresh_window(self):
  self.begin(self.receipt());live=adapters.Live.__new__(adapters.Live);live.p=self.p;live.c=self.c
  evidence={'execution_id':self.p['execution_id'],'scope_sha256':digest(self.p['scopes']['native_forms_maintenance']),
   'owner_action_reference':'FIXTURE_PRIOR_OWNER_CONFIRMATION','maintenance_window_id':'f'*24,
   'earliest_window_epoch':self.c.state()['forms_hold_started_epoch'],'disabled_epoch':time.time(),
   'disabled':['FR','EN']}
  with patch.object(adapters.Path,'exists',return_value=True),patch.object(adapters,'private_file'),patch.object(adapters,'load',return_value=evidence),patch.object(adapters,'urlopen') as network:
   with self.assertRaisesRegex(RebuildError,'Forms_owner_evidence_wrong_window'):live.forms()
   network.assert_not_called()
 def test_null_queue_clock_completion_uses_original_intent_and_preserves_Forms_clock(self):
  issued=time.time()-60;self.c.transition({'completed_stages':['PREPARED','APPROVED','FORMS_HELD'],'forms_hold_started_epoch':issued,'hold_started_epoch':None},'fixture')
  at=stamp();row={'attempt':1,'at':at,'input_sha256':'test'}
  receipt={'output_sha256':'e'*64,'evidence':['FIXTURE_ONLY'],'after_state':{}}
  Runner(self.p,self.c,self.root/'approval.json',self.root/'health.json').complete(self.c.state(),'QUEUE_HELD',receipt,row)
  self.assertIsInstance(self.c.state()['hold_started_epoch'],float)
  self.assertEqual(self.c.state()['forms_hold_started_epoch'],issued)
 def test_queue_intent_clock_is_persisted_before_any_transport(self):
  out=self.receipt();self.begin(out)
  self.c.transition({'hold_started_epoch':None},'fixture')
  step={'stage':'QUEUE_HELD','reviewed':True,'retry':'NEVER','timeout_seconds':10,'execute':{'fixture':1},'verify':{'fixture':2}}
  runner=Runner(self.p,self.c,self.root/'approval.json',self.root/'health.json')
  process=MagicMock();process.__enter__.return_value=process;process.poll.return_value=0
  def transport(*args,**kwargs):
   self.assertIsInstance(self.c.state()['hold_started_epoch'],float)
   return process
  with patch('durable_migration.pinned_command',return_value=['FIXTURE_ONLY_NO_COMMAND']),patch('durable_migration.subprocess.Popen',side_effect=transport),patch.object(runner,'readback',return_value={'FIXTURE_ONLY':'PASS'}):
   runner.execute(step,'fixture-input',1)
  row=self.c.attempt('QUEUE_HELD')
  self.assertEqual(self.c.state()['hold_started_epoch'],datetime.fromisoformat(row['at']).timestamp())
  self.assertEqual(self.c.state()['forms_hold_started_epoch'],out['issued_epoch'])
 def test_closed_preNEW_abort_then_new_full_chain_keeps_all_old_evidence(self):
  first=self.begin(self.receipt());platform=Fixture(self.root/'platform.json')
  old_root=self.root/'evidence'/first['maintenance_window_id']
  adapter=adapters.Adapters(self.p,platform,old_root,self.root/'approval.json')
  for stage in ('FORMS_HELD','QUEUE_HELD','SOURCE_FROZEN'):adapter.execute(stage,stage)
  original=(old_root/'SOURCE_FROZEN.verified.json').read_bytes()
  self.c.transition({'completed_stages':['PREPARED','APPROVED','FORMS_HELD','QUEUE_HELD','SOURCE_FROZEN']},'fixture')
  state=platform.state();state.update(stages=[],queue_held=False,forms_held=False,source_fenced=False)
  atomic_json(platform.path,state);self.close()
  second=self.begin(self.receipt(1));new_root=self.root/'evidence'/second['maintenance_window_id']
  adapter=adapters.Adapters(self.p,platform,new_root,self.root/'approval.json')
  for stage in adapters.STAGE_SCOPE:adapter.execute(stage,stage)
  state=platform.state();self.assertEqual(state['dns'],'15.235.100.76')
  self.assertTrue(state['source_fenced']);self.assertFalse(state['queue_held'])
  self.assertEqual(state['effects']['QUEUE_HELD'],2)
  self.assertEqual(state['effects']['CUTOVER'],1)
  self.assertEqual((old_root/'SOURCE_FROZEN.verified.json').read_bytes(),original)

class RollbackReadbackTests(unittest.TestCase):
 setUp=WindowTests.setUp
 tearDown=WindowTests.tearDown
 def fake(self,event='ROLLED_BACK',new_data=False):
  self.c.transition({'status':'ROLLING_BACK','completed_stages':['PREPARED','SOURCE_FROZEN']},'fixture')
  self.p['runtime']['worker_before_versions_sha256']=digest([])
  self.p['scopes']['worker_hold_deployment']['before_settings_sha256']=digest({})
  queue={'settings':{'delivery_paused':True}};calls=[]
  def edge(path):
   if path==adapters.DNS:return {'content':'148.113.249.7'}
   if path==adapters.QUEUE:return queue
   return [] if path.endswith('/versions') else {}
  def source(verb,**kw):
   calls.append(verb);return {'fenced':False,'state':{'event':event,'rollback_verified_epoch':time.time() if event=='ROLLED_BACK' else None,'new_data_observed':new_data}}
  def write(*args):calls.append('queue-resume');queue['settings']['delivery_paused']=False
  fake=SimpleNamespace(p=self.p,c=self.c,root=self.root/'stage',source=source,edge=edge,forms=lambda:{'held':True},
   approval=lambda scope:{'conditional_rollback_approved':True,'conditional_OLD_queue_resume_approved':True},edge_write=write)
  health={'host':self.p['source']['host'],'production_sha':self.p['production_sha'],'fenced':False,'API':{'status':'ok'},'services':{'API':'active'}}
  return fake,calls,SimpleNamespace(stdout=json.dumps(health).encode())
 def test_confirmed_source_restore_is_not_repeated_after_health_probe_interruption(self):
  fake,calls,response=self.fake()
  with patch.object(adapters,'Live',return_value=fake),patch.object(adapters,'run',return_value=response):
   result=adapters.conditional_rollback(self.p)
  self.assertEqual(result['status'],'ROLLED_BACK');self.assertNotIn('rollback',calls)
  self.assertEqual(calls.count('queue-resume'),1)
 def test_unexplained_fence_removal_never_resumes_queue(self):
  fake,calls,response=self.fake(event='UNKNOWN')
  with patch.object(adapters,'Live',return_value=fake),patch.object(adapters,'run',return_value=response):
   with self.assertRaisesRegex(RebuildError,'source_rollback_unverified_no_duplicate_restore'):
    adapters.conditional_rollback(self.p)
  self.assertNotIn('queue-resume',calls)
 def test_ambiguous_queue_resume_get_reconciles_after_source_restore_without_retry(self):
  fake,calls,response=self.fake()
  fake.edge(adapters.QUEUE)['settings']['delivery_paused']=False
  now=datetime.now(timezone.utc);aid=self.c.action_id('migration-provider','safe_queue_observer_resume')
  record=self.c.audit.envelope(aid,'fixture.approved_queue_resume',{'type':'RECOVERY','identity':'FIXTURE_ONLY'},now,
   initiator='OWNER',trigger='FIXTURE_ONLY_OWNER_AUTHORITY',mutation=True,approval_required=True,
   authority_class='OWNER_EXACT_MIGRATION',automatic_rule='Fixture only, no real provider',
   rollback_capability='COMPENSATING_ACTION_ONLY',before_state={'settings':{'delivery_paused':True}},
   proposed_state={'settings':{'delivery_paused':False}},consequence='Fixture JSON only',
   compensating_action='Retain fixture evidence',exact_versions={'package_sha256':profile_binding(self.p)},
   reason='Simulate a lost ACK after an approved conditional OLD resume')
  self.c.audit.store.plan(record,now)
  self.c.audit.store.approve(aid,'FIXTURE_ONLY_OWNER_AUTHORITY',now,binding=self.c.canonical.approval_binding(record),expires_at=datetime.fromtimestamp(time.time()+60,timezone.utc).isoformat())
  self.c.audit.store.start(aid,now,authority_check=lambda:None)
  def no_new_approval(scope):raise AssertionError('GET reconciliation must not execute a new approval scope')
  fake.approval=no_new_approval
  with patch.object(adapters,'Live',return_value=fake),patch.object(adapters,'run',return_value=response):
   result=adapters.conditional_rollback(self.p)
  self.assertEqual(result['status'],'ROLLED_BACK')
  self.assertEqual(self.c.audit.store.get(aid)['status'],'SUCCEEDED')
  self.assertNotIn('rollback',calls);self.assertNotIn('queue-resume',calls)
 def test_wrong_OLD_identity_never_resumes_delivery(self):
  fake,calls,response=self.fake();health=json.loads(response.stdout);health['production_sha']='0'*40
  response.stdout=json.dumps(health).encode()
  with patch.object(adapters,'Live',return_value=fake),patch.object(adapters,'run',return_value=response):
   with self.assertRaisesRegex(RebuildError,'OLD_private_API_not_healthy_do_not_resume_queue'):
    adapters.conditional_rollback(self.p)
  self.assertNotIn('queue-resume',calls)
 def test_source_NEW_marker_blocks_any_OLD_restore_even_without_local_release_file(self):
  fake,calls,response=self.fake(new_data=True)
  with patch.object(adapters,'Live',return_value=fake),patch.object(adapters,'run',return_value=response):
   result=adapters.conditional_rollback(self.p)
  self.assertEqual(result['blocker'],'CONTAIN_AND_RECONCILE_NEW')
  self.assertNotIn('rollback',calls);self.assertNotIn('queue-resume',calls)


class WindowCheckpointTests(unittest.TestCase):
 def test_encrypted_checkpoint_selection_preserves_nested_windows_without_collisions(self):
  from migration_checkpoint import copy_stage_evidence
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'evidence';destination=root/'sealed'
   source.mkdir();destination.mkdir()
   (source/'QUEUE_HELD.json').write_text('LEGACY PRESERVED')
   for window in ('a'*24,'b'*24):
    directory=source/'windows'/window;directory.mkdir(parents=True)
    (directory/'QUEUE_HELD.json').write_text(window)
    (directory/'source-control-SOURCE_FROZEN-1.tar.gz').write_bytes(b'CONTROL '+window.encode())
   (source/'not-owned.json').symlink_to(source/'QUEUE_HELD.json')
   oversized=source/'oversized.json'
   with oversized.open('wb') as file:file.truncate(1024**2)
   copy_stage_evidence(source,destination)
   self.assertEqual((destination/'QUEUE_HELD.json').read_text(),'LEGACY PRESERVED')
   for window in ('a'*24,'b'*24):
    self.assertEqual((destination/'windows'/window/'QUEUE_HELD.json').read_text(),window)
    self.assertTrue((destination/'windows'/window/'source-control-SOURCE_FROZEN-1.tar.gz').exists())
   self.assertFalse((destination/'not-owned.json').exists())
   self.assertFalse((destination/'oversized.json').exists())

if __name__=='__main__':unittest.main()
