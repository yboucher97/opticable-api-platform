"""Baseline -> candidate -> baseline-read probe -> safe candidate recovery.

Fixture DB only, no live DB, no listeners and no providers. Baseline dispatch is
explicitly unsafe: its legacy handler contains the removed mutation authority.
Safe recovery retains the corrected code and preserves V2 journals/approvals.
"""
import argparse,hashlib,json,os,shutil,socket,sqlite3,subprocess,sys,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASELINE='52f11d4fc14d8582c03837e0317f849efe8aa3d7'

def blocked(*args,**kwargs):raise AssertionError('External network prohibited in recovery exercise')
def audit_hash(database):
 with sqlite3.connect(database) as conn:
  return hashlib.sha256(json.dumps(conn.execute('SELECT * FROM automation_audit ORDER BY id').fetchall(),sort_keys=True,default=str).encode()).hexdigest()
def child(code,directory,mode):
 os.environ.clear();os.environ.update(PATH='/usr/bin:/bin',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',SITE_WORKFLOW_OUTPUT_ROOT=str(directory/'output'),OPTICABLE_AUTOMATION_DB_PATH=str(directory/'state.db'))
 os.chdir(directory);sys.path.insert(0,str(code/'apps/workflow-api'))
 socket.socket.connect=socket.socket.connect_ex=socket.socket.sendto=blocked;socket.create_connection=socket.getaddrinfo=blocked
 from workflow.automation.store import AutomationStore
 from workflow.automation.events import EventLedger
 from workflow.automation.desired_journal import DesiredJournal
 from workflow.automation.engine import AutomationEngine
 from workflow.automation.models import AutomationEvent,WorkflowDefinition
 database=directory/'state.db';store=AutomationStore(database);EventLedger(store)
 definition=WorkflowDefinition.model_validate({'id':'compat.smoke','name':'Smoke','trigger':{'event_types':['compat.internal']},'steps':[{'id':'safe','action':'core.set','with':{'values':{'ok':True}}}]})
 engine=AutomationEngine(store,directory/'definitions')
 if mode=='baseline-init':
  store.upsert_workflow(definition);store.audit(category='desired_state_v1',action='manual',actor='fixture',success=False,target='operation',metadata={'body_hash':'a'*64,'operation_id':'123'})
  engine.ingest(AutomationEvent(event_type='compat.internal',source='internal',event_id='baseline-event',idempotency_key='baseline-key'))
 elif mode=='candidate-state':
  from workflow.automation.outbound_approval import OutboundApprovalLedger
  from datetime import datetime,timedelta,timezone
  ledger=OutboundApprovalLedger(store);ids={}
  for state in ('consumed','manual','consuming'):
   approval=ledger.issue(actor='human:fixture',action_type='send_new_email',source_type='lead',source_id='123',source_version='2026-09-28T18:00:00Z',account_id='456',recipient='client@example.test',from_address='info@opticable.ca',subject='fixture subject',content='fixture body',expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
   with ledger.lock():
    ledger.mark_consuming(approval)
    if state=='consumed':ledger.mark_consumed(approval,provider_operation_id='789')
    if state=='manual':ledger.mark_manual(approval,error='provider_unconfirmed')
   ids[state]=approval.approval_id
  journal=DesiredJournal(store)
  with journal.lock():
   journal.record('started','compat-provider-operation',{'body_hash':'b'*64,'policy':'phase6-sales-v1'},'fixture')
   journal.record('manual','compat-provider-operation',{'body_hash':'b'*64,'operation_id':'789'},'fixture')
  (directory/'approvals.json').write_text(json.dumps(ids))
  engine.ingest(AutomationEvent(event_type='compat.internal',source='internal',event_id='candidate-event',idempotency_key='candidate-key'))
  # Persist an old unsafe queued definition; never execute it with baseline code.
  unsafe=WorkflowDefinition.model_validate({'id':'compat.legacy','name':'Unsafe legacy snapshot','trigger':{'event_types':['compat.queued']},'steps':[{'id':'write','action':'lifecycle.crm_promote_lead','with':{'lead':{'email':'fixture@example.test'},'qualification':{'promotion_allowed':True}}}]})
  store.upsert_workflow(unsafe)
  store.ingest_event_and_runs(AutomationEvent(event_type='compat.queued',source='fixture',event_id='queued-event',idempotency_key='queued-key'))
  (directory/'approval-proof.hash').write_text(audit_hash(database))
  files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.name in {'approvals.json','approval-proof.hash'} or p.name.endswith('.lock')}
  assert len(files)>=4
  (directory/'persistent-proofs.json').write_text(json.dumps(files))
 elif mode=='baseline-read':
  from fastapi.testclient import TestClient
  from workflow.api import app
  # No lifespan/worker/definition reload; startup-to-dispatch is not authorized.
  assert TestClient(app).get('/health').json()['version']=='1.10.0'
  assert store.queued_envelopes(limit=10)
  assert len(store.recent_audit())>=4
  assert DesiredJournal(store).unresolved('compat-provider-operation')
  assert DesiredJournal(store).last('compat-provider-operation',('manual',))['metadata']['operation_id']=='789'
  assert audit_hash(database)==(directory/'approval-proof.hash').read_text()
  from workflow.automation.providers.lifecycle_extended import register_lifecycle_extended_actions
  from unittest.mock import Mock
  calls=[]
  def fake_request(service,method,path,**kwargs):
   calls.append((method,path))
   if method=='GET': return {'data':{'data':[]}}
   return {'data':{'data':[{'code':'SUCCESS','details':{'id':'1001'}}]}}
  provider=Mock();provider.request.side_effect=fake_request
  register_lifecycle_extended_actions(engine,provider,Mock(),store)
  # A disposable copied DB proves baseline dispatch can revive the legacy writer.
  engine.recover_pending(limit=10)
  assert any(method=='POST' and path=='/crm/v8/Contacts' for method,path in calls)
  assert any(method=='POST' and path=='/crm/v8/Deals' for method,path in calls)
  print(json.dumps({'baseline_reads_v2':True,'baseline_dispatch_safe':False,'reason':'legacy mutation handler remains available'}));return
 elif mode=='forward-recover':
  from workflow.automation.outbound_approval import OutboundApprovalLedger
  from workflow.automation.providers.lifecycle_extended import register_lifecycle_extended_actions
  from unittest.mock import Mock
  ledger=OutboundApprovalLedger(store);ids=json.loads((directory/'approvals.json').read_text())
  for state,identity in ids.items():assert ledger.inspect(identity)['state']==state
  provider=Mock();register_lifecycle_extended_actions(engine,provider,Mock(),store)
  engine.recover_pending(limit=10)
  provider.request.assert_not_called()
  assert all(r['status']!='queued' for r in store.recent_runs())
  assert (directory/'approvals.json').exists()
  for relative,digest in json.loads((directory/'persistent-proofs.json').read_text()).items():
   assert hashlib.sha256((directory/relative).read_bytes()).hexdigest()==digest
  with sqlite3.connect(database) as conn:
   assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   assert conn.execute('PRAGMA user_version').fetchone()[0]==2
   assert conn.execute("SELECT COUNT(*) FROM automation_audit WHERE category='desired_state_v1'").fetchone()[0]==3
  assert DesiredJournal(store).unresolved('compat-provider-operation')
  assert DesiredJournal(store).last('compat-provider-operation',('manual',))['metadata']['operation_id']=='789'
  event=AutomationEvent(event_type='compat.internal',source='internal',event_id='candidate-event',idempotency_key='candidate-key')
  assert engine.ingest(event).duplicate
  for state,identity in ids.items():assert ledger.inspect(identity)['state']==state
  print(json.dumps({'forward_recovery':'PASS','approval_states_preserved':True,'queued_mutations_blocked':True,'dedupe_preserved':True,'provider_operation_journal_preserved':True,'persistent_files_preserved':True}));return
 with sqlite3.connect(database) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==2
 print(json.dumps({'mode':mode,'schema':2,'provider_writes':0}))

def exercise():
 with tempfile.TemporaryDirectory(prefix='phase6-recovery-fixture-') as temp:
  root=Path(temp);baseline=root/'baseline-code';baseline.mkdir();archive=root/'baseline.tar'
  subprocess.run(['/usr/bin/git','-C',str(ROOT),'archive','--format=tar','--output='+str(archive),BASELINE],check=True,capture_output=True)
  with tarfile.open(archive) as source:
   if any(not (m.isfile() or m.isdir()) for m in source.getmembers()):raise RuntimeError('unsafe_source_archive')
   source.extractall(baseline,filter='data')
  state=root/'state';state.mkdir()
  output=[]
  for code,mode in ((baseline,'baseline-init'),(ROOT,'candidate-state'),(baseline,'baseline-read'),(ROOT,'forward-recover')):
   directory=state
   if mode=='baseline-read':
    directory=root/'baseline-probe';directory.mkdir()
    with sqlite3.connect(state/'state.db') as src,sqlite3.connect(directory/'state.db') as dst:src.backup(dst)
    shutil.copyfile(state/'approval-proof.hash',directory/'approval-proof.hash')
   p=subprocess.run([sys.executable,'-I',str(Path(__file__).resolve()),'--child',mode,'--code',str(code),'--directory',str(directory)],capture_output=True,text=True,timeout=90)
   if p.returncode:raise RuntimeError('recovery_'+mode+': '+p.stderr[-3000:])
   output.append(json.loads(p.stdout.splitlines()[-1]))
  return {'result':'PASS','baseline':BASELINE,'direct_baseline_rollback_safe':False,'forward_recovery':'PASS','strategy':'forward-only-preserve-v2','phases':output,'live_state_used':False,'provider_writes':0,'customer_sends':0,'books_mutations':0,'crm_mutations':0,'lead_conversions':0}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--baseline',default=BASELINE);parser.add_argument('--child');parser.add_argument('--code',type=Path);parser.add_argument('--directory',type=Path);args=parser.parse_args()
 if args.baseline!=BASELINE:raise SystemExit('Unapproved baseline')
 if args.child:child(args.code,args.directory,args.child)
 else:print(json.dumps(exercise()))
