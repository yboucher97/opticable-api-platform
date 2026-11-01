"""Isolated persistent end-to-end stage/failure fixtures. No provider transports."""
import copy,hashlib,json,os,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ops/rebuild'))
from common import atomic_json,digest,RebuildError
from durable_migration import Control,Runner,approvals,profile_binding,stage_order,verify_receipt
from migration_adapters import Adapters,STAGE_SCOPE,rollback_choice
from source_executor import verify_request,canonical,UNITS

class Fixture:
 def __init__(self,path):
  self.path=path;self.fail=None
  if not path.exists():atomic_json(path,{'stages':[],'effects':{},'dns':'148.113.249.7','queue_held':False,'source_fenced':False,'new_data':False,'worker_changed':False,'free':49*1024**3,'forms_held':False,'notification_delivered':True})
 def state(self):return json.loads(self.path.read_text())
 def observe(self,stage):return self.state()
 def evidence(self,stage):return [str(self.path),'fixture-independent-reopen']
 def preconditions(self,stage,before):
  if stage=='FORMS_HELD' and not before['notification_delivered']:raise RebuildError('notification_unavailable')
  if stage in ('RECOVERY_VERIFIED','TARGET_SYNCHRONIZED') and before['free']<48*1024**3:raise RebuildError('storage_exhausted_no_deletion')
 def verify(self,stage,before,after):
  if stage not in after['stages']:raise RebuildError('stage_not_done')
 def effect(self,stage,before,approval):
  s=self.state();self.preconditions(stage,s)
  s['effects'][stage]=s['effects'].get(stage,0)+1
  if stage=='FORMS_HELD':s['forms_held']=True
  if stage=='QUEUE_HELD':s['queue_held']=True
  if stage=='SOURCE_FROZEN':s['source_fenced']=True
  if stage=='INTAKE_RELEASED':s['new_data']=True
  if stage=='WORKER_HELD':s['worker_changed']=True
  if stage=='CUTOVER':s['dns']='15.235.100.76'
  if stage=='INTAKE_VERIFIED':s['queue_held']=False
  s['stages'].append(stage);atomic_json(self.path,s)
  if self.fail==stage:raise TimeoutError('lost ACK after committed effect')
  return {'transport':'fixture'}

class ExecutorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  from durable_migration import SCOPES
  self.p={'version':2,'execution_id':'fixture-run','source':{'host':'vps-214ba8cd','ip':'148.113.249.7'},'target':{'host':'vps-f8e9b20e','ip':'15.235.100.76'},'production_sha':'b'*40,'scopes':{s:{'action':s,'bounds':3600} for s in SCOPES},'steps':[],'runtime':{},'code_sha256':{},'hold_max_seconds':3600,'rollback_review_seconds':2700,'business_automation':'OFF','execution_enabled':False}
  self.a={'execution_id':'fixture-run','profile_sha256':profile_binding(self.p),'owner_authorization_reference':'ISOLATED_FIXTURE_NOT_LIVE_APPROVAL','owner_authorization_sha256':'a'*64,'issued_epoch':time.time()-1,'expires_epoch':time.time()+3500,'scopes':{s:{'approved':True,'binding_sha256':digest(self.p['scopes'][s])} for s in SCOPES}}
  self.ap=self.root/'approval.json';atomic_json(self.ap,self.a);self.io=Fixture(self.root/'platform.json');self.adapter=Adapters(self.p,self.io,self.root/'stages',self.ap)
 def tearDown(self):self.tmp.cleanup()
 def test_complete_persistent_execution_chain(self):
  previous=None
  for stage in STAGE_SCOPE:
   inputs=digest([previous,stage]);r=self.adapter.execute(stage,inputs);verify_receipt(r,self.p,stage,inputs)
   self.adapter=Adapters(self.p,Fixture(self.io.path),self.root/'stages',self.ap)
   r=self.adapter.verify(stage,inputs);previous=r['output_sha256']
  final=self.io.state();self.assertEqual(final['dns'],'15.235.100.76');self.assertTrue(final['source_fenced']);self.assertFalse(final['queue_held']);self.assertTrue(all(v==1 for v in final['effects'].values()))
 def test_lost_ack_after_every_stage_reconciles_no_duplicate(self):
  for stage in STAGE_SCOPE:
   with self.subTest(stage=stage):
    self.adapter.io.fail=stage
    with self.assertRaises(TimeoutError):self.adapter.execute(stage,stage)
    self.adapter=Adapters(self.p,Fixture(self.io.path),self.root/'stages',self.ap)
    self.assertEqual(self.adapter.execute(stage,stage)['status'],'PASS')
    self.assertEqual(self.io.state()['effects'][stage],1)
 def test_expired_approval_blocks_new_effect_but_not_readback(self):
  self.adapter.execute('QUEUE_HELD','x');self.a['expires_epoch']=time.time()-1;atomic_json(self.ap,self.a)
  self.assertEqual(self.adapter.verify('QUEUE_HELD','x')['status'],'PASS')
  with self.assertRaises(RebuildError):self.adapter.execute('SOURCE_FROZEN','y')
  self.assertNotIn('SOURCE_FROZEN',self.io.state()['stages'])
 def test_independent_scope_decisions(self):
  self.a['scopes']['crm_notification_recreation']['approved']=False;atomic_json(self.ap,self.a)
  self.assertTrue(approvals(self.p,self.ap,required=('queue_hold',)))
  with self.assertRaises(RebuildError):approvals(self.p,self.ap,required=('crm_notification_recreation',))
 def test_arming_does_not_invalidate_exact_action_bindings(self):
  changed=copy.deepcopy(self.p);changed.update(execution_enabled=True,rollback_verified=True,source_reboot_fence_verified=True)
  self.assertEqual(profile_binding(changed),profile_binding(self.p));approvals(changed,self.ap,required=('queue_hold',))
  changed['scopes']['dns_cutover']['bounds']=7200
  with self.assertRaises(RebuildError):approvals(changed,self.ap,required=('dns_cutover',))
 def test_storage_exhaustion_before_mutation_preserves_existing_state(self):
  s=self.io.state();s['free']=47*1024**3;atomic_json(self.io.path,s)
  with self.assertRaises(RebuildError):self.adapter.execute('TARGET_SYNCHRONIZED','x')
  self.assertFalse(self.adapter.path('TARGET_SYNCHRONIZED').exists());self.assertNotIn('TARGET_SYNCHRONIZED',self.io.state()['stages'])
 def test_notification_failure_prevents_window(self):
  s=self.io.state();s['notification_delivered']=False;atomic_json(self.io.path,s)
  with self.assertRaises(RebuildError):self.adapter.execute('FORMS_HELD','x')
  self.assertFalse(self.io.state()['forms_held'])
 def test_external_uncertainty_never_retries(self):
  atomic_json(self.adapter.path('CUTOVER'),{'input_sha256':'x','before_state':self.io.state()})
  with self.assertRaises(RebuildError):self.adapter.execute('CUTOVER','x')
  self.assertNotIn('CUTOVER',self.io.state()['effects'])
 def test_restart_control_persists_stage_and_audit(self):
  c=Control(self.root/'actions.db','fixture-run');c.transition({'completed_stages':['PREPARED','SOURCE_FROZEN'],'authority':'OLD'},'fixture')
  c=Control(self.root/'actions.db','fixture-run');self.assertIn('SOURCE_FROZEN',c.state()['completed_stages'])
  from common import database_snapshot
  self.assertGreater(database_snapshot(c.path)['audit_chains_verified'],0)
 def test_conditional_rollback_before_release(self):
  state={'dns':'148.113.249.7','queue_held':True,'forms_held':True,'source_fenced':True,'new_data':False,'worker_changed':False}
  self.assertEqual(rollback_choice(['SOURCE_FROZEN'],state),'RESTORE_OLD_UNDER_EXACT_ROLLBACK_APPROVAL')
 def test_no_blind_rollback_after_NEW_data_or_unknown_DNS(self):
  state={'dns':'148.113.249.7','queue_held':True,'forms_held':True,'source_fenced':True}
  for changes,done in [({'new_data':True},[]),({},['INTAKE_RELEASED']),({'dns':'15.235.100.76'},[]),({'worker_changed':True},[])]:
   self.assertEqual(rollback_choice(done,{**state,**changes}),'CONTAIN_AND_RECONCILE_NEW')
 def test_missing_hold_prevents_rollback(self):
  self.assertEqual(rollback_choice([],{'dns':'148.113.249.7'}),'REQUIRES_OWNER_NO_AUTHORITY_CHANGE')
 def test_signed_OLD_protocol_rejects_arbitrary_shell(self):
  cfg={'execution_id':'fixture-run','source':self.p['source'],'target':self.p['target'],'package_sha256':'x','scopes':{'source_freeze_final_sync':{'source_executor_sha256':__import__('source_executor').sha(__import__('source_executor').__file__)}}}
  payload={'verb':'bash -c anything','execution_id':'fixture-run','source':self.p['source'],'target':self.p['target'],'package_sha256':'x','issued_epoch':time.time(),'expires_epoch':time.time()+60}
  with self.assertRaises(RuntimeError):verify_request({'payload':payload,'signature':''},cfg)
 def test_fence_covers_apps_timers_and_oneshot_writers(self):
  self.assertIn('opticable-workflow-api.service',UNITS);self.assertIn('opticable-customer-communications.timer',UNITS);self.assertIn('optibrain-backup.service',UNITS)


class SignedBridgeTests(unittest.TestCase):
 def setUp(self):
  import subprocess,source_executor as se
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.se=se
  subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(self.root/'private.pem')],check=True,capture_output=True)
  subprocess.run(['openssl','pkey','-in',str(self.root/'private.pem'),'-pubout','-out',str(self.root/'public.pem')],check=True,capture_output=True)
  self.scope={'source_executor_sha256':se.sha(se.__file__),'action':'exact-fixture-freeze'}
  self.cfg={'execution_id':'fixture-run','source':{'host':'vps-214ba8cd','ip':'148.113.249.7'},'target':{'host':'vps-f8e9b20e','ip':'15.235.100.76'},'package_sha256':'p'*64,'public_key':str(self.root/'public.pem'),'scopes':{'source_freeze_final_sync':self.scope}}
  self.payload={'verb':'status','execution_id':'fixture-run','source':copy.deepcopy(self.cfg['source']),'target':copy.deepcopy(self.cfg['target']),'package_sha256':'p'*64,'issued_epoch':time.time()-1,'expires_epoch':time.time()+60}
 def tearDown(self):self.tmp.cleanup()
 def sign(self,payload):
  import base64,subprocess
  (self.root/'message').write_bytes(canonical(payload));subprocess.run(['openssl','pkeyutl','-sign','-inkey',str(self.root/'private.pem'),'-rawin','-in',str(self.root/'message'),'-out',str(self.root/'signature')],check=True,capture_output=True)
  return {'payload':copy.deepcopy(payload),'signature':base64.b64encode((self.root/'signature').read_bytes()).decode()}
 def test_real_ED25519_status_and_tampered_packet(self):
  wire=self.sign(self.payload);self.assertEqual(verify_request(wire,self.cfg)['verb'],'status');wire['payload']['verb']='freeze'
  with self.assertRaises(RuntimeError):verify_request(wire,self.cfg)
 def test_signed_freeze_without_owner_scope_denied(self):
  self.payload['verb']='freeze'
  with self.assertRaises(RuntimeError):verify_request(self.sign(self.payload),self.cfg)
 def test_signed_exact_scope_and_expiry(self):
  self.payload.update(verb='freeze',scope_approval={'approved':True,'binding_sha256':hashlib.sha256(canonical(self.scope)).hexdigest(),'owner_authorization_reference':'FIXTURE_ONLY','owner_authorization_sha256':'a'*64,'issued_epoch':time.time()-1,'expires_epoch':time.time()+60})
  self.assertEqual(verify_request(self.sign(self.payload),self.cfg)['verb'],'freeze')
  self.payload['scope_approval']['expires_epoch']=time.time()-1
  with self.assertRaises(RuntimeError):verify_request(self.sign(self.payload),self.cfg)
 def test_changed_host_or_revision_denied(self):
  self.payload['target']['ip']='127.0.0.1'
  with self.assertRaises(RuntimeError):verify_request(self.sign(self.payload),self.cfg)
  cfg=copy.deepcopy(self.cfg);cfg['scopes']['source_freeze_final_sync']['source_executor_sha256']='f'*64
  with self.assertRaises(RuntimeError):verify_request(self.sign(self.payload),cfg)

class AuthorityTests(unittest.TestCase):
 setUp=ExecutorTests.setUp
 tearDown=ExecutorTests.tearDown
 def test_decision_recorder_defaults_to_no_consent_and_pins_message(self):
  from migration_authority import issue
  message=self.root/'owner.txt';message.write_text('ISOLATED FIXTURE authorization text, never live consent.');message.chmod(0o600)
  d=self.root/'decisions.json';atomic_json(d,{s:{'approved':False} for s in self.p['scopes']})
  result=issue(self.p,message,'FIXTURE_ONLY',d,profile_binding(self.p))
  self.assertFalse(any(v['approved'] for v in result['scopes'].values()));self.assertEqual(result['owner_authorization_sha256'],hashlib.sha256(message.read_bytes()).hexdigest())
  with self.assertRaises(RebuildError):issue(self.p,message,'FIXTURE_ONLY',d,'wrong-reviewed-package')

class ForcedSSHTests(unittest.TestCase):
 def test_internal_commands_shells_and_SFTP_are_unreachable(self):
  from source_ssh_command import dispatch
  for args in ([],['status'],['install-fence'],['supervise'],['notify-failure'],['job freeze'],['bash'],['execute; id'],['sftp'],['execute','extra']):
   with self.subTest(args=args),self.assertRaises(SystemExit),patch('os.execve') as execute:
    dispatch(args);execute.assert_not_called()
 def test_exact_protocol_replaces_process_with_fixed_sanitized_environment(self):
  from source_ssh_command import dispatch
  with patch('os.execve') as execute:
   dispatch(['execute']);args=execute.call_args.args
   self.assertEqual(args[1][-1],'execute');self.assertEqual(set(args[2]),{'PATH','LANG','PYTHONDONTWRITEBYTECODE'})

class StreamRecoveryTests(unittest.TestCase):
 def test_interrupted_transfer_resumes_verified_prefix_without_a_second_copy(self):
  import io
  from source_executor import verified_stream
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'recovery';data=os.urandom(2*1024**2+19);p.write_bytes(data);out=io.BytesIO();offset=100003
   verified_stream(p,offset,hashlib.sha256(data[:offset]).hexdigest(),out)
   self.assertEqual(data[:offset]+out.getvalue(),data)
 def test_wrong_partial_prefix_fails_before_emitting_any_recovery_bytes(self):
  import io
  from source_executor import verified_stream
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'recovery';p.write_bytes(b'verified archive');out=io.BytesIO()
   with self.assertRaises(RuntimeError):verified_stream(p,3,'wrong',out)
   self.assertEqual(out.getvalue(),b'');self.assertEqual(p.read_bytes(),b'verified archive')
 def test_all_nine_SQLite_stores_preserve_learning_corrections_and_audit_on_backup(self):
  from common import database_snapshot
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for i in range(9):
    p=root/('source-'+str(i)+'.db');snapshot=root/('snapshot-'+str(i)+'.db')
    with sqlite3.connect(p) as db:
     db.executescript('CREATE TABLE learning(id PRIMARY KEY,body); CREATE TABLE corrections(id PRIMARY KEY,body); CREATE TABLE historical_events(id PRIMARY KEY,body);')
     for table in ('learning','corrections','historical_events'):db.execute('INSERT INTO '+table+' VALUES(?,?)',(i,'unique accumulated state '+str(i)))
    before=database_snapshot(p)
    with sqlite3.connect(p) as src,sqlite3.connect(snapshot) as dst:src.backup(dst)
    self.assertEqual(database_snapshot(snapshot),before)

class IndependentWatchdogTests(unittest.TestCase):
 def test_watchdog_can_sign_when_runner_runtime_is_absent(self):
  from migration_adapters import runtime_directory
  with patch('migration_adapters.Path.is_dir',side_effect=[False,True]):self.assertEqual(runtime_directory(),'/run/optibrain-migration-watchdog')
 def test_no_runtime_fails_closed(self):
  from migration_adapters import runtime_directory
  with patch('migration_adapters.Path.is_dir',return_value=False),self.assertRaises(RuntimeError):runtime_directory()

class ConditionalRollbackExecutionTests(unittest.TestCase):
 setUp=ExecutorTests.setUp
 tearDown=ExecutorTests.tearDown
 def prepare_live(self,released=False):
  from types import SimpleNamespace
  from migration_adapters import WORKER,DNS,QUEUE
  c=Control(self.root/'rollback-actions.db','fixture-run');c.transition({'completed_stages':['SOURCE_FROZEN']+(['INTAKE_RELEASED'] if released else []),'current_stage':'SOURCE_FROZEN','authority':'OLD','status':'FAILED'},'fixture')
  self.p['runtime']['worker_before_versions_sha256']=digest({'version':'original'});self.p['scopes']['worker_hold_deployment']['before_settings_sha256']=digest({'bindings':[]})
  calls=[]
  def edge(path):
   return {'content':'148.113.249.7'} if path==DNS else {'settings':{'delivery_paused':True}} if path==QUEUE else {'bindings':[]} if path==WORKER+'/settings' else {'version':'original'}
  def source(verb,**kw):
   if verb=='rollback':calls.append('restore_OLD')
   return {'fenced':True}
  live=SimpleNamespace(c=c,root=self.root,edge=edge,source=source,forms=lambda:{'held':True},approval=lambda scope:{'conditional_rollback_approved':True,'conditional_OLD_queue_resume_approved':True},edge_write=lambda *args:calls.append('resume_queue'))
  return live,c,calls
 def test_real_conditional_rollback_function_restores_only_approved_pre_NEW_state(self):
  from types import SimpleNamespace
  from migration_adapters import conditional_rollback
  live,c,calls=self.prepare_live();health=SimpleNamespace(stdout=b'{"API":{"status":"ok"},"services":{"API":"active"}}')
  with patch('migration_adapters.Live',return_value=live),patch('migration_adapters.run',return_value=health):conditional_rollback(self.p)
  self.assertEqual(calls,['restore_OLD','resume_queue']);self.assertEqual(c.state()['status'],'ROLLED_BACK')
 def test_real_conditional_rollback_function_retains_NEW_and_never_reverses_DNS(self):
  from migration_adapters import conditional_rollback
  live,c,calls=self.prepare_live(True)
  with patch('migration_adapters.Live',return_value=live),patch('migration_adapters.run') as run:conditional_rollback(self.p);run.assert_not_called()
  self.assertEqual(calls,[]);self.assertEqual(c.state()['status'],'REQUIRES_OWNER');self.assertEqual(c.state()['rollback_decision'],'CONTAIN_AND_RECONCILE_NEW')

class CanonicalStageAuditTests(unittest.TestCase):
 setUp=ExecutorTests.setUp
 tearDown=ExecutorTests.tearDown
 def test_stage_has_exact_approval_before_effect_and_finishes_only_after_readback(self):
  from migration_adapters import Live
  live=Live.__new__(Live);live.p=self.p;live.c=Control(self.root/'stage-audit.db','fixture-run')
  grant={'owner_authorization_reference':'ISOLATED_FIXTURE_OWNER','expires_epoch':time.time()+100};live.approval=lambda scope:grant
  with patch('migration_adapters.file_hash',return_value='f'*64):live.stage_intent('QUEUE_HELD',{'held':False},self.a,'i'*64)
  aid='migration-stage:fixture-run:QUEUE_HELD';self.assertEqual(live.c.audit.store.get(aid)['status'],'STARTED')
  live.stage_verified('QUEUE_HELD',{'after_state':{'held':True},'output_sha256':digest({'held':True})})
  self.assertEqual(live.c.audit.store.get(aid)['status'],'SUCCEEDED')
  with self.assertRaises(RebuildError):live.stage_intent('QUEUE_HELD',{'held':False},self.a,'i'*64)

if __name__=='__main__':unittest.main(verbosity=2)
