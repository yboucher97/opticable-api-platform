#!/usr/bin/env python3
"""Concrete migration stages. Each effect has one intent and independent readback.
Fixture tests inject platform operations; live CLI never accepts a fixture path.
"""
import argparse,base64,configparser,hashlib,importlib.util,json,os,re,shlex,shutil,sqlite3,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from common import atomic_json,database_snapshot,digest,env_file,file_hash,private_file,require
from durable_migration import Control,approvals,load_profile,profile_binding,SCOPES
TOOL=Path('/opt/optibrain-rebuild-toolchain/migration-20261027')
ART=Path('/recovery/migration-preparation/intake-handoff-20261028')
CONTROL=Path('/var/lib/optibrain-rebuild')
ROOT=Path('/recovery/migration-preparation/autonomous-20261101/executor')
PYTHON='/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python'
ACCOUNT='81d07d311d1b51e5e04b451d1f254850'
QUEUE='/accounts/'+ACCOUNT+'/queues/31c6f7026fe142d8959a09613b87c5dd'
DNS='/zones/ea7b4f245feb0a98fb5534e73e761970/dns_records/8f10227bdeaa87597fd71cf7d499f133'
WORKER='/accounts/'+ACCOUNT+'/workers/scripts/opticable-control-plane'
STAGE_SCOPE={'FORMS_HELD':'native_forms_maintenance','QUEUE_HELD':'queue_hold','SOURCE_FROZEN':'source_freeze_final_sync','CAPTURED':'source_freeze_final_sync','RECOVERY_VERIFIED':'source_freeze_final_sync','TARGET_SYNCHRONIZED':'source_freeze_final_sync','INTAKE_RELEASED':'new_only_intake_release','PRIVATE_VERIFIED':'new_only_intake_release','WORKER_HELD':'worker_hold_deployment','CUTOVER':'dns_cutover','CRM_VERIFIED':'crm_notification_recreation','INTAKE_VERIFIED':'safe_queue_observer_resume','COMPLETE':'safe_queue_observer_resume'}
STAGES=('PREPARED','APPROVED',*STAGE_SCOPE)
TIMED_SCOPES=tuple(s for s in SCOPES if s!='crm_notification_recreation')

def window_approvals(profile,path):
 a=approvals(profile,path,required=TIMED_SCOPES)
 require(a['scopes']['source_freeze_final_sync'].get('conditional_rollback_approved') is True,'conditional_source_rollback_permission_required_before_window')
 require(a['scopes']['safe_queue_observer_resume'].get('conditional_OLD_queue_resume_approved') is True,'conditional_OLD_queue_resume_permission_required_before_window')
 return a

def run(argv,timeout=60,**kw):return subprocess.run(argv,check=True,capture_output=True,timeout=timeout,**kw)
def load(path):return json.loads(Path(path).read_text())
def utc(epoch):return datetime.fromtimestamp(epoch,timezone.utc).isoformat()

def runtime_directory():
 # The independent watchdog must still sign/reconcile when the runner is down.
 for name in ('/run/optibrain-migration','/run/optibrain-migration-watchdog'):
  if Path(name).is_dir():return name
 raise RuntimeError('migration_runtime_directory_missing')

def rollback_choice(done,observed):
 """Conservative split. Releasing NEW intake is the point of no blind return."""
 if observed.get('new_data') or 'INTAKE_RELEASED' in done or observed.get('dns')!='148.113.249.7' or observed.get('worker_changed'):
  return 'CONTAIN_AND_RECONCILE_NEW'
 if not observed.get('queue_held') or not observed.get('forms_held'):return 'REQUIRES_OWNER_NO_AUTHORITY_CHANGE'
 if 'SOURCE_FROZEN' in done or observed.get('source_fenced'):return 'RESTORE_OLD_UNDER_EXACT_ROLLBACK_APPROVAL'
 return 'RESUME_OLD_QUEUE_UNDER_EXACT_ROLLBACK_APPROVAL'

def verify_workflow_drain(profile,edge):
 # A terminal failure cannot be terminated safely; retain only exact approved evidence.
 path=profile['runtime']['workflow_instances_path']
 def entries(value):
  require(isinstance(value,(list,dict)),'malformed_workflow_status_response')
  rows=value if isinstance(value,list) else value.get('instances',value.get('items'))
  require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),'malformed_workflow_status_response');return rows
 for status in ('queued','running','paused','waitingForPause','waiting','rollingBack'):
  rows=entries(edge(path,{'status':status,'per_page':1}))
  require(not rows,'remote_workflow_not_drained:'+status)
 retained=profile['scopes']['source_freeze_final_sync'].get('retained_errored_workflows')
 approved={}
 if retained:
  approved=retained['instances'];require(isinstance(approved,dict) and len(approved)<100,'bounded_exact_terminal_error_set_required')
  proof=Path(retained['evidence_file']);private_file(proof)
  require(file_hash(proof)==retained['evidence_sha256'],'terminal_error_evidence_changed')
  saved=load(proof);snapshots={row['id']:digest(row['detail']) for row in saved['items']}
  require(snapshots==approved,'terminal_error_evidence_identity_mismatch')
  seal=load(CONTROL/'migration-offhost.json');require(seal.get('status')=='PASS' and seal.get('full_R2_readback')=='PASS' and datetime.fromisoformat(seal['at']).timestamp()>=proof.stat().st_mtime,'terminal_error_evidence_not_protected_offhost')
 rows=entries(edge(path,{'status':'errored','per_page':max(1,len(approved)+1)}))
 require(len(rows)<=len(approved) and len({row.get('id') for row in rows})==len(rows),'unknown_or_duplicate_terminal_workflow_error')
 for row in rows:
  ident=row.get('id');require(isinstance(ident,str) and ident in approved and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',ident),'unapproved_terminal_workflow_error')
  detail=edge(path+'/'+ident);require(detail.get('status')=='errored' and detail.get('end') and digest(detail)==approved[ident],'terminal_workflow_error_changed')
 # No status change, retry, restart, ACK, deletion or provider effect occurs here.
 return {'active_drained':True,'preserved_terminal_failures':len(rows)}

class Adapters:
 def __init__(self,p,platform,root,approval_path):
  self.p,self.io,self.root,self.approval_path=p,platform,Path(root),Path(approval_path);self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
 def path(self,stage):return self.root/(stage+'.json')
 def authorized(self,stage):return approvals(self.p,self.approval_path,required=() if stage=='CRM_VERIFIED' else (STAGE_SCOPE[stage],))
 def execute(self,stage,inputs):
  self.authorized(stage)
  path=self.path(stage)
  if path.exists():
   v=load(path);require(v['input_sha256']==inputs,'stage_input_changed')
   # Intent exists: reconcile only. Even a local adapter may include provider effects.
   try:return self.verify(stage,inputs)
   except Exception:
    require(stage in ('SOURCE_FROZEN','CAPTURED','RECOVERY_VERIFIED','TARGET_SYNCHRONIZED','PRIVATE_VERIFIED'),'uncertain_effect_reconcile_only')
    self.io.effect(stage,v['before_state'],self.authorized(stage))
    return self.verify(stage,inputs)
  before=self.io.observe(stage)
  self.io.preconditions(stage,before)
  intent={'execution_id':self.p['execution_id'],'stage':stage,'input_sha256':inputs,'before_state':before,'at_epoch':time.time(),'state':'ATTEMPTED','approval_sha256':file_hash(self.approval_path)}
  atomic_json(path,intent)
  if hasattr(self.io,'stage_intent'):self.io.stage_intent(stage,before,self.authorized(stage),inputs)
  result=self.io.effect(stage,before,self.authorized(stage))
  atomic_json(self.root/(stage+'.transport.json'),result)
  return self.verify(stage,inputs)
 def verify(self,stage,inputs):
  v=load(self.path(stage));require(v['input_sha256']==inputs,'stage_input_changed')
  # Do not accept the command result file as evidence of its own success.
  observed=self.io.observe(stage);self.io.verify(stage,v['before_state'],observed)
  receipt={'status':'PASS','execution_id':self.p['execution_id'],'stage':stage,'input_sha256':inputs,'source':self.p['source'],'target':self.p['target'],'before_state':v['before_state'],'after_state':observed,'output_sha256':digest(observed),'verified_epoch':time.time(),'effect_started_epoch':v['at_epoch'],'evidence':[str(self.path(stage)),*self.io.evidence(stage)]}
  atomic_json(self.root/(stage+'.verified.json'),receipt)
  if hasattr(self.io,'stage_verified'):self.io.stage_verified(stage,receipt)
  return receipt

class Live:
 def __init__(self,p):
  self.p=p;self.c=Control(CONTROL/'actions.db',p['execution_id']);self.cf=None
  window=self.c.window_id();self.root=ROOT/'windows'/window if window else ROOT
  self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
 def stage_intent(self,stage,before,authorization,inputs):
  if stage=='CRM_VERIFIED' and authorization['scopes']['crm_notification_recreation'].get('approved') is False:return
  scope=STAGE_SCOPE[stage];approval=self.approval(scope);aid=self.c.action_id('migration-stage',stage)
  store=self.c.audit.store;old=store.get(aid)
  if old:
   require(old['status']=='STARTED','verified_stage_cannot_be_reexecuted');return
  now=datetime.now(timezone.utc);mutating=stage in ('QUEUE_HELD','SOURCE_FROZEN','TARGET_SYNCHRONIZED','INTAKE_RELEASED','WORKER_HELD','CUTOVER','CRM_VERIFIED','INTAKE_VERIFIED')
  record=self.c.audit.envelope(aid,'migration.exact_stage.'+stage,{'type':'RECOVERY','identity':self.p['execution_id']+':'+stage},now,initiator='OWNER',trigger=approval['owner_authorization_reference'],before_state=before,proposed_state={'stage':stage,'scope_sha256':digest(self.p['scopes'][scope]),'input_sha256':inputs,'business_execution':'OFF'},reason='Exact action-bound owner migration scope',business_rationale='Preserve all history and a single production authority',authority_class='OWNER_EXACT_MIGRATION',automatic_rule='Reconcile uncertainty; bounded idempotent local retry only',mutation=mutating,approval_required=True,rollback_capability='COMPENSATING_ACTION_ONLY',consequence='Only the exact reviewed migration stage',compensating_action='Conditional pre-NEW rollback; otherwise retain OLD fence and preserve NEW',exact_versions={'package_sha256':profile_binding(self.p),'approval_sha256':file_hash('/etc/optibrain/migration/owner-approvals.json')})
  store.plan(record,now);store.approve(aid,approval['owner_authorization_reference'],now,binding=self.c.canonical.approval_binding(record),expires_at=utc(approval['expires_epoch']));store.start(aid,now,authority_check=lambda:self.approval(scope))
 def stage_verified(self,stage,receipt):
  store=self.c.audit.store;aid=self.c.action_id('migration-stage',stage);action=store.get(aid)
  if action and action['status']=='STARTED':store.finish(aid,datetime.now(timezone.utc),provider_success=True,actual_after=receipt['after_state'],verified=True,response={'independent_readback_sha256':receipt['output_sha256']})
 def evidence(self,stage):
  evidence=['independent-readback:'+stage,'canonical-actions.db',str(self.root/(stage+'.verified.json'))]
  if stage in ('SOURCE_FROZEN','CAPTURED','RECOVERY_VERIFIED','CUTOVER','INTAKE_VERIFIED','COMPLETE'):
   path=self.root/('source-control-'+stage+'-'+str(time.time_ns())+'.tar.gz');self.source('read-control',destination=path)
   import tarfile
   with tarfile.open(path,'r:gz') as archive:
    members=archive.getmembers();require(all(m.isfile() and '/' not in m.name and m.size<=10*1024**2 for m in members),'source_control_export_unsafe')
    values={m.name:archive.extractfile(m).read() for m in members};manifest=json.loads(values.pop('control-manifest.json'))
    require({n:hashlib.sha256(b).hexdigest() for n,b in values.items()}==manifest['files'],'source_control_export_hash_failed')
   evidence.append(str(path)+'#sha256='+file_hash(path))
  return evidence
 def source(self,verb,*,scope=None,extra=None,destination=None):
  payload={'verb':verb,'execution_id':self.p['execution_id'],'source':self.p['source'],'target':self.p['target'],'package_sha256':profile_binding(self.p),'issued_epoch':time.time(),'expires_epoch':time.time()+100,**(extra or {})}
  if scope:payload['scope_approval']=scope
  with tempfile.TemporaryDirectory(dir=runtime_directory(),prefix='signed-stage-') as t:
   msg=Path(t)/'payload';sig=Path(t)/'signature';msg.write_text(json.dumps(payload,sort_keys=True,separators=(',',':')))
   run(['openssl','pkeyutl','-sign','-inkey','/etc/optibrain/migration/source-stage-signing-key.pem','-rawin','-in',str(msg),'-out',str(sig)])
   wire=json.dumps({'payload':payload,'signature':base64.b64encode(sig.read_bytes()).decode()}).encode()
  cmd=['ssh','-i','/etc/optibrain/migration/source-stage-key','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/etc/optibrain/migration/source-known-hosts','-o','ConnectTimeout=10','optibrain@148.113.249.7','execute']
  if destination:
   path=Path(destination)
   if path.exists():
    payload['offset']=path.stat().st_size;payload['prefix_sha256']=file_hash(path)
    with tempfile.TemporaryDirectory(dir=runtime_directory(),prefix='signed-resume-') as t:
     msg=Path(t)/'payload';sig=Path(t)/'signature';msg.write_text(json.dumps(payload,sort_keys=True,separators=(',',':')))
     run(['openssl','pkeyutl','-sign','-inkey','/etc/optibrain/migration/source-stage-signing-key.pem','-rawin','-in',str(msg),'-out',str(sig)])
     wire=json.dumps({'payload':payload,'signature':base64.b64encode(sig.read_bytes()).decode()}).encode()
   with path.open('ab' if path.exists() else 'xb') as f:
    r=subprocess.run(cmd,input=wire,stdout=f,stderr=subprocess.PIPE,timeout=600);f.flush();os.fsync(f.fileno());require(r.returncode==0,'source_stream_failed_preserve_partial')
   return {'path':str(destination),'sha256':file_hash(destination)}
  return json.loads(run(cmd,input=wire,timeout=150 if verb=='providers' else 100 if verb=='preflight' else 35).stdout)
 def edge(self,path,params=None):
  if self.cf is None:
   os.environ.update(env_file('/etc/opticable-workflow-api.env'));sys.path.insert(0,'/opt/opticable-api-platform/apps/workflow-api')
   from workflow.config import load_settings
   from workflow.cloudflare_api import CloudflareApiClient
   self.cf=CloudflareApiClient(load_settings().cloudflare)
  result=self.cf.request(path,params=params)['data'];require(result.get('success') is True,'Cloudflare_GET_failed');return result['result']
 def edge_write(self,path,body,scope,method='PATCH'):
  before=self.edge(path);a=self.approval(scope)
  if scope=='dns_cutover':
   expected=self.p['scopes'][scope];require(before.get('name')==expected['name'] and all(before.get(k)==v for k,v in expected['before'].items()),'DNS_changed_since_approval')
  elif scope=='queue_hold':require(before.get('settings',{}).get('message_retention_period')==86400 and not before.get('settings',{}).get('delivery_paused',False),'queue_changed_since_approval')
  elif scope=='safe_queue_observer_resume':require(before.get('settings',{}).get('delivery_paused') is True,'queue_resume_before_changed')
  from workflow.automation.action_evidence import ActionEvidence,envelope,approval_binding
  from workflow.automation.mutation_control import technical_admin_call
  audit=ActionEvidence(CONTROL/'actions.db');aid=self.c.action_id('migration-provider',scope)
  require(audit.get(aid) is None,'provider_effect_already_attempted_GET_only')
  now=datetime.now(timezone.utc);record=envelope(aid,'EXACT_MIGRATION_'+scope.upper(),{'type':'CONFIGURATION','identity':path},now,provider='cloudflare',mutation=True,approval_required=True,approval_record=a,exact_versions={'package_sha256':profile_binding(self.p)},before_state=before,proposed_state=body,reason='Exact separately owner-approved migration scope',business_rationale='Preserve intake and a single authoritative server',rollback_capability='COMPENSATING_ACTION_ONLY',consequence='Exact approved migration configuration only',compensating_action='Conditional rollback; preserve NEW data and never blindly revert authority',authority_class='OWNER_EXACT_MIGRATION',automatic_rule='One transport; GET-only reconciliation after ambiguous outcome')
  audit.plan(record,now);audit.approve(aid,a['owner_authorization_reference'],now,binding=approval_binding(record),expires_at=utc(a['expires_epoch']));audit.start(aid,now,authority_check=lambda:None)
  with technical_admin_call(self.cf,'cloudflare',method,path,body,audit=audit,action_id=aid):result=self.cf.request(path,method=method,body=body)
  after=self.edge(path);expected=body.get('settings',body);actual=after.get('settings',after)
  require(all(actual.get(k)==v for k,v in expected.items()),'provider_after_mismatch')
  audit.finish(aid,datetime.now(timezone.utc),provider_success=True,actual_after=after,verified=True,response={'status':result['status']});return {'status':'TRANSPORT_COMPLETE'}
 def approval(self,scope):
  allv=approvals(self.p,'/etc/optibrain/migration/owner-approvals.json',required=(scope,));v=allv['scopes'][scope]
  return {**v,'issued_epoch':v.get('issued_epoch',allv['issued_epoch']),'expires_epoch':v.get('expires_epoch',allv['expires_epoch']),'owner_authorization_reference':v.get('owner_authorization_reference',allv['owner_authorization_reference']),'owner_authorization_sha256':v.get('owner_authorization_sha256',allv['owner_authorization_sha256'])}
 def forms(self):
  scope=self.p['scopes']['native_forms_maintenance'];receipt=Path('/etc/optibrain/migration/forms-maintenance-evidence.json')
  require(receipt.exists(),'OWNER_FORMS_UI_HOLD_REQUIRED_no_admin_API')
  private_file(receipt);r=load(receipt);require(r.get('execution_id')==self.p['execution_id'] and r.get('scope_sha256')==digest(scope) and r.get('owner_action_reference'),'Forms_owner_evidence_not_bound')
  window=self.c.window_id()
  if window:
   started=self.c.state().get('forms_hold_started_epoch')
   require(r.get('maintenance_window_id')==window and isinstance(started,(int,float))
    and r.get('earliest_window_epoch')==started and r.get('disabled_epoch',0)>=started,'Forms_owner_evidence_wrong_window')
  require(r.get('disabled')==['FR','EN'] and r.get('disabled_epoch',0)<=time.time() and time.time()-r['disabled_epoch']<3600,'Forms_hold_receipt_invalid')
  proofs={}
  for language,form in scope['forms'].items():
   slug='Formulairedemandedesoumission' if language=='FR' else 'RequestaQuote';url='https://forms.zohopublic.com/opticable/form/'+slug+'/formperma/'+form
   with urlopen(url,timeout=20) as response:body=response.read(2*1024**2).decode('utf-8','replace');status=response.status
   # Explicit configured bilingual message is required, never guess Zoho retry/retention.
   require('Temporary maintenance. No request is submitted.' in body and 'Veuillez réessayer plus tard.' in body and not re.search(r'<form\b',body,re.I),'Forms_still_accepting_or_hold_unproved')
   proofs[language]={'http':status,'body_sha256':hashlib.sha256(body.encode()).hexdigest(),'explicit_maintenance':True}
  return {'held':True,'disabled_epoch':r['disabled_epoch'],'proofs':proofs,'owner_evidence_sha256':file_hash(receipt)}
 def private_api(self):
  e=env_file('/etc/opticable-workflow-api.env');key=e[e.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]
  headers={'X-API-Key':key}
  values={}
  for name,path in [('health','/v1/system/health'),('intake','/v1/automation/event-health')]:
   with urlopen(Request('http://127.0.0.1:8100'+path,headers=headers),timeout=10) as r:values[name]=json.load(r)
  require(values['health'].get('status')=='ok','private_API_unhealthy');hold=values['intake'].get('intake_hold',{})
  require(hold.get('mode')=='hold-v1' and hold.get('capture_available') is True,'hold_receiver_not_ready')
  sys.path.insert(0,str(TOOL/'ops/rebuild'));from engine import SAFETY,APP_UNITS
  for unit in APP_UNITS:
   pid=run(['systemctl','show',unit,'-p','MainPID','--value']).stdout.decode().strip();require(pid!='0','app_not_running');env=dict(x.split(b'=',1) for x in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in x)
   require(all(env.get(k.encode(),b'').decode()==v for k,v in SAFETY.items()),'business_flags_not_OFF')
  return {'healthy':True,'hold_v1':True,'all45_off':True,'API_version':values['health'].get('version')}
 def public_api(self):
  import httpx
  e=env_file('/etc/opticable-workflow-api.env');headers={'X-API-Key':e[e.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]}
  # Fixed same-origin requests. Redirects never carry API credentials to login hosts.
  for name,key in [('CF-Access-Client-Id','CF_ACCESS_CLIENT_ID'),('CF-Access-Client-Secret','CF_ACCESS_CLIENT_SECRET')]:
   if e.get(key):headers[name]=e[key]
  r=httpx.get('https://optibrain.opticable.ca/v1/automation/event-health',headers=headers,timeout=20,follow_redirects=False);require(r.status_code==200,'public_receiver_access_not_verified')
  hold=r.json().get('intake_hold',{});require(hold.get('mode')=='hold-v1' and hold.get('capture_available'),'public_receiver_not_NEW_hold')
  return {'public_NEW_hold':True,'http':r.status_code,'body_sha256':digest(r.json())}
 def final_paths(self):
  s=self.source('status')['state'];require(re.fullmatch(r'\d{8}T\d{6}Z',s.get('generation','')) is not None,'verified_source_generation_missing');d=self.root/s['generation'];d.mkdir(mode=0o700,exist_ok=True)
  return s,d,d/('optibrain-backup-'+s['generation']+'.tar.gz')
 def observe(self,stage):
  if stage=='FORMS_HELD':return self.forms()
  if stage=='QUEUE_HELD':return {'queue':self.edge(QUEUE),'metrics':self.edge(QUEUE+'/metrics')}
  if stage in ('SOURCE_FROZEN','CAPTURED'):return self.source('status')
  if stage=='RECOVERY_VERIFIED':
   s,d,a=self.final_paths();receipt=load(d/'offhost.json') if (d/'offhost.json').exists() else {}
   return {'source':s,'archive_sha256':file_hash(a) if a.exists() else None,'offhost':receipt,'catalog_sha256':file_hash(d/'verified-catalog.json') if (d/'verified-catalog.json').exists() else None,'freeze_sha256':file_hash(d/'source-freeze.json') if (d/'source-freeze.json').exists() else None}
  if stage=='TARGET_SYNCHRONIZED':
   return {'state':load(CONTROL/'state.json'),'result':load(CONTROL/'result.json') if (CONTROL/'result.json').exists() else {}}
  if stage in ('INTAKE_RELEASED','PRIVATE_VERIFIED'):return self.private_api() if (ART/'approved-release-result.json').exists() else {'released':False}
  if stage=='WORKER_HELD':return {'settings':self.edge(WORKER+'/settings'),'versions':self.edge(WORKER+'/versions'),'queue':self.edge(QUEUE)}
  if stage=='CUTOVER':
   dns=self.edge(DNS);return {'dns':dns,'source':self.source('status'),'api':self.private_api(),'public':self.public_api() if dns.get('content')=='15.235.100.76' else None}
  if stage=='CRM_VERIFIED':
   v=self.crm(plan_only=True)
   decision=approvals(self.p,'/etc/optibrain/migration/owner-approvals.json',required=())['scopes']['crm_notification_recreation']
   if decision.get('approved') is False and v.get('status')=='READY_FOR_APPROVAL':v={**v,'disposition':'EXPLICIT_OWNER_DEFERRED_NO_WRITE'}
   return v
  if stage=='INTAKE_VERIFIED':
   unit='opticable-phase9-intake-receipts.timer';service='opticable-phase9-intake-receipts.service'
   return {'queue':self.edge(QUEUE),'api':self.private_api(),'timer':run(['systemctl','show',unit,'-p','ActiveState','--value']).stdout.decode().strip(),'collector_result':run(['systemctl','show',service,'-p','Result','--value']).stdout.decode().strip(),'observer_policy_sha256':file_hash(Path('/etc/optibrain/migration/observer-off.env')) if Path('/etc/optibrain/migration/observer-off.env').exists() else None,'dns':self.edge(DNS),'public':self.public_api()}
  if stage=='COMPLETE':
   return {'health':load(CONTROL/'migration-health.json'),'source':self.source('status'),'intake':self.observe('INTAKE_VERIFIED'),'forms_reopened':load('/etc/optibrain/migration/forms-reopened-evidence.json') if Path('/etc/optibrain/migration/forms-reopened-evidence.json').exists() else None}
  raise RuntimeError('unbound_stage')
 def preconditions(self,stage,before):
  if stage=='FORMS_HELD':
   # Do not begin a timed window unless every indispensable downstream scope is already granted.
   window_approvals(self.p,'/etc/optibrain/migration/owner-approvals.json')
   require(self.c.state().get('notification_test',{}).get('state')=='DELIVERED' and not self.c.state().get('notification_failure'),'owner_notification_unreliable')
  if stage=='QUEUE_HELD':
   q=before['queue'];require(q.get('queue_id')=='31c6f7026fe142d8959a09613b87c5dd' and q.get('settings',{}).get('message_retention_period')==86400 and not q.get('settings',{}).get('delivery_paused',False),'queue_before_changed')
   metrics=before['metrics'];oldest=metrics.get('oldest_message_timestamp_ms',0)
   require(metrics.get('backlog_count',0)==0 or oldest and time.time()-oldest/1000+3600<86400,'queue_retention_budget_insufficient')
  if stage=='SOURCE_FROZEN':
   require(self.forms()['held'] and self.edge(QUEUE)['settings'].get('delivery_paused') is True,'external_hold_missing')
   require(before['persistent_fence_installed'] and not before['fenced'],'source_fence_not_ready')
   verify_workflow_drain(self.p,self.edge)
  if stage in ('RECOVERY_VERIFIED','TARGET_SYNCHRONIZED'):
   require(shutil.disk_usage('/').free>=48*1024**3,'target_final_sync_capacity_below_48GiB_no_deletion')
  if stage=='CUTOVER':
   scope=self.p['scopes']['dns_cutover'];require(before['dns'].get('name')==scope['name'] and all(before['dns'].get(k)==v for k,v in scope['before'].items()) and before['source']['fenced'],'cutover_before_changed')
 def verify(self,stage,before,after):
  if stage=='FORMS_HELD':require(after.get('held'),'Forms_not_held')
  elif stage=='QUEUE_HELD':require(after['queue']['settings'].get('delivery_paused') is True,'queue_not_held')
  elif stage=='SOURCE_FROZEN':require(after['fenced'] and after['state'].get('frozen') and all(v in ('inactive','failed') for v in after['units'].values()),'source_not_frozen')
  elif stage=='CAPTURED':require(after['state'].get('archive_sha256') and after['state'].get('generation') and after['fenced'],'capture_not_finished')
  elif stage=='RECOVERY_VERIFIED':require(after['offhost'].get('status')=='PASS' and after['offhost']['source_sha256']==after['source']['archive_sha256']==after['archive_sha256'] and after['freeze_sha256']==after['source']['freeze_receipt_sha256'] and after['catalog_sha256'],'recovery_not_independently_verified')
  elif stage=='TARGET_SYNCHRONIZED':require(after['state'].get('completed') and not after['state'].get('pending_generation') and after['state']['generation']==self.source('status')['state']['generation'] and after['result'].get('ready_for_owner_cutover'),'final_sync_not_verified')
  elif stage in ('INTAKE_RELEASED','PRIVATE_VERIFIED'):require(after.get('hold_v1') and after.get('all45_off'),'private_hold_not_verified')
  elif stage=='WORKER_HELD':
   require(after['queue']['settings'].get('delivery_paused') is True,'Worker_deploy_changed_queue_hold')
   bindings=after['settings']['bindings'];require(any(b.get('name')=='CORE_INTAKE_HOLD_REQUIRED' and b.get('text')=='true' for b in bindings),'Worker_hold_binding_missing')
   require(self.worker_other_bindings(before['settings'])==self.worker_other_bindings(after['settings']),'Worker_other_bindings_changed')
   require(after['versions']!=before['versions'],'Worker_version_not_changed')
  elif stage=='CUTOVER':require(after['dns']['content']=='15.235.100.76' and after['dns']['proxied'] is True and after['source']['fenced'] and after.get('public',{}).get('public_NEW_hold'),'DNS_cutover_not_verified')
  elif stage=='CRM_VERIFIED':require(after.get('status')=='PASS_EXISTING_EXACT_CHANNEL' or after.get('disposition')=='EXPLICIT_OWNER_DEFERRED_NO_WRITE','CRM_channel_not_verified')
  elif stage=='INTAKE_VERIFIED':require(after['queue']['settings'].get('delivery_paused',False) is False and after['dns']['content']=='15.235.100.76' and after['timer']=='active' and after['collector_result']=='success' and after['observer_policy_sha256'],'safe_resume_not_verified')
  elif stage=='COMPLETE':require(after['health'].get('status')=='PASS' and after['source']['fenced'] and after.get('forms_reopened',{}).get('verified') is True,'completion_missing_current_backups_or_Forms_reopen')
 @staticmethod
 def worker_other_bindings(settings):return sorted([b for b in settings.get('bindings',[]) if b.get('name')!='CORE_INTAKE_HOLD_REQUIRED'],key=lambda b:b.get('name',''))
 def effect(self,stage,before,approvals_document):
  if stage in ('FORMS_HELD','PRIVATE_VERIFIED'):return {'read_only':True}
  if stage=='COMPLETE':
   run(['systemctl','start','optibrain-backup.service'],timeout=650);run(['systemctl','start','optibrain-phase2a-upload.service'],timeout=650)
   from migration_health import check
   atomic_json(CONTROL/'migration-health.json',check(self.p));return {'real_systemd_backup_and_offhost_readback':'REQUESTED_VERIFIED_BY_HEALTH'}
  if stage=='QUEUE_HELD':return self.edge_write(QUEUE,self.p['scopes']['queue_hold']['body'],'queue_hold')
  if stage in ('SOURCE_FROZEN','CAPTURED'):
   extra={}
   if stage=='SOURCE_FROZEN':extra['readiness']={'queue_held':True,'forms_held':self.forms()['held'],'workflows_drained':True,'owner_access_verified':self.current_proofs()['owner_access'],'providers_verified':self.current_proofs()['providers']}
   verb='freeze' if stage=='SOURCE_FROZEN' else 'capture';self.source(verb,scope=self.approval('source_freeze_final_sync'),extra=extra)
   end=time.monotonic()+(200 if verb=='freeze' else 650)
   while time.monotonic()<end:
    s=self.source('status');state=s['state']
    if state.get('frozen') and (verb=='freeze' or state.get('archive_sha256')):return {'source_journal_sha256':s['journal_sha256']}
    time.sleep(3)
   raise RuntimeError('source_job_unverified_reconcile_only')
  if stage=='RECOVERY_VERIFIED':return self.transfer_recovery()
  if stage=='TARGET_SYNCHRONIZED':
   s,d,a=self.final_paths();argv=[PYTHON,'-B',str(TOOL/'ops/rebuild/cli.py'),'final-sync','--manifest',str(CONTROL/'manifest.json'),'--catalog',str(d/'verified-catalog.json'),'--archive',str(a),'--generation',s['generation'],'--migration','--freeze-receipt',str(d/'source-freeze.json')]
   run(argv,timeout=850);return {'generation':s['generation']}
  if stage=='INTAKE_RELEASED':
   self.source('heartbeat',extra={'new_intake_exposed':True})  # Durable OLD-side no-return marker BEFORE NEW can accept anything.
   s,d,a=self.final_paths();approval=self.approval('new_only_intake_release');receipt={'approved':True,'phase':'NEW_INTAKE_HOLD_RELEASE_ONLY','candidate_sha':'ec9a8e85095b57faf21212000652912e08093da4','baseline_sha':self.p['production_sha'],'ci_run_id':40763886958,'approved_at':utc(approval['issued_epoch']),'expires_at':utc(approval['expires_epoch']),'artifact_sha256':file_hash(ART/'new-only-intake-release.py'),'freeze_receipt':str(d/'source-freeze.json'),'freeze_receipt_sha256':file_hash(d/'source-freeze.json'),'owner_authorization_reference':approval['owner_authorization_reference']};f=Path('/etc/optibrain/new-intake-release-owner-approval.json');atomic_json(f,receipt)
   run([PYTHON,'-B',str(ART/'new-only-intake-release.py'),str(f)],timeout=180);return {'candidate':receipt['candidate_sha']}
  if stage=='WORKER_HELD':return self.worker_deploy(before)
  if stage=='CUTOVER':
   from migration_origin import enable
   enable(self)
   return self.edge_write(DNS,self.p['scopes']['dns_cutover']['after'],'dns_cutover')
  if stage=='CRM_VERIFIED':
   if approvals_document['scopes']['crm_notification_recreation'].get('approved') is False:return {'read_only':True,'disposition':'EXPLICIT_OWNER_DEFERRED_NO_WRITE'}
   return self.crm(plan_only=False)
  if stage=='INTAKE_VERIFIED':
   self.resume_observer();return self.edge_write(QUEUE,{'queue_name':'opticable-business-events','settings':{'delivery_paused':False}},'safe_queue_observer_resume')
  raise RuntimeError('unbound_effect')
 def run_origin(self,argv):return run(argv,timeout=45)
 def origin_headers(self):
  e=env_file('/etc/opticable-workflow-api.env');return {'X-API-Key':e[e.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]}
 def current_proofs(self):
  proof=load('/var/lib/optibrain-rebuild/window-verification.json');private_file('/var/lib/optibrain-rebuild/window-verification.json')
  require(proof.get('package_sha256')==profile_binding(self.p) and 0<=time.time()-proof['verified_epoch']<1800,'current_window_proofs_missing_or_stale')
  require(all(proof.get(k) is True for k in ('owner_access','providers','identity','recovery','rollback','reboot_fence')),'window_proof_failed');return proof
 def transfer_recovery(self):
  s,d,a=self.final_paths()
  if not a.exists() or file_hash(a)!=s['archive_sha256']:self.source('read-archive',destination=a)
  a.chmod(0o600);require(file_hash(a)==s['archive_sha256'],'transfer_hash_mismatch')
  f=d/'source-freeze.json'
  if not f.exists() or file_hash(f)!=s['freeze_receipt_sha256']:self.source('read-receipt',destination=f)
  f.chmod(0o600);require(file_hash(f)==s['freeze_receipt_sha256'],'freeze_receipt_hash_mismatch')
  cipher=d/(a.name+'.age');creation=d/'cipher-created.json'
  if not cipher.exists():
   partial=d/(a.name+'.'+str(time.time_ns())+'.partial.age')
   run(['age','-r',Path('/etc/optibrain/age-recipient').read_text().strip(),'-o',str(partial),str(a)],timeout=240)
   partial.rename(cipher);atomic_json(creation,{'ciphertext_sha256':file_hash(cipher)})
  else:require(creation.exists() and load(creation)['ciphertext_sha256']==file_hash(cipher),'existing_cipher_unverified_preserve')
  # Existing create-only uploader; full encrypted GET, not HEAD/ETag alone.
  receipt=json.loads(run(['/usr/bin/python3','-B',str(Path(__file__)),'seal-final'],timeout=600).stdout);receipt.update(generation=s['generation'],source_sha256=s['archive_sha256'],encrypted_sha256=file_hash(cipher),object_key=receipt['object_key'],recipient_sha256=file_hash('/etc/optibrain/age-recipient'),verification_status='download_hash_verified',verified_at=utc(time.time()))
  atomic_json(d/'offhost.json',receipt)
  run([PYTHON,'-B',str(ART/'final_identity_check.py'),'--pins',str(ART/'final-identity-pins.json'),'--archive',str(a),'--sha256',s['archive_sha256']],timeout=180)
  sys.path.insert(0,str(TOOL/'ops/rebuild'));from recovery import build_catalog
  catalog=build_catalog(a,receipt,Path(runtime_directory()));atomic_json(d/'verified-catalog.json',catalog);return {'status':'PASS','generation':s['generation']}
 def worker_deploy(self,before):
  r=self.p['runtime'];bundle=Path(r['worker_bundle']);require(file_hash(bundle)==r['worker_bundle_sha256'],'Worker_bundle_changed')
  require(digest(before['settings'])==self.p['scopes']['worker_hold_deployment']['before_settings_sha256'],'Worker_settings_changed_requires_approval_refresh')
  require(self.edge(QUEUE)['settings'].get('delivery_paused') is True,'queue_must_be_held_for_Worker_deploy');self.private_api()
  # Root-owned frozen dry-run bundle/config and pinned installed Wrangler. No npm install or package resolution.
  require(file_hash(r['wrangler_script'])==r['wrangler_sha256'],'Wrangler_changed')
  for name,checksum in r['worker_tool_catalog'].items():
   from common import trusted_manifest
   trusted_manifest(name);require(file_hash(name)==checksum,'Worker_tool_dependency_changed')
  from workflow.automation.action_evidence import ActionEvidence,envelope,approval_binding
  aid='migration-worker:'+self.p['execution_id'];audit=ActionEvidence(CONTROL/'actions.db');require(audit.get(aid) is None,'Worker_effect_already_attempted')
  now=datetime.now(timezone.utc);approval=self.approval('worker_hold_deployment');proposal={'bundle_sha256':r['worker_bundle_sha256'],'config_sha256':file_hash(r['worker_config']),'hold':'true','other_bindings':'PRESERVE'}
  record=envelope(aid,'EXACT_MIGRATION_WORKER_HOLD',{'type':'CONFIGURATION','identity':WORKER},now,provider='cloudflare',mutation=True,approval_required=True,approval_record=approval,exact_versions={'package_sha256':profile_binding(self.p)},before_state=before,proposed_state=proposal,reason='Exact reviewed Worker hold deployment',business_rationale='Require durable hold receipt before queue acknowledgement',rollback_capability='COMPENSATING_ACTION_ONLY',consequence='Updates one existing Worker only',compensating_action='Hold queue; retain OLD fence; separately reconcile before any authority reversal',authority_class='OWNER_EXACT_MIGRATION',automatic_rule='One transport; GET-only reconcile lost acknowledgement')
  audit.plan(record,now);audit.approve(aid,approval['owner_authorization_reference'],now,binding=approval_binding(record),expires_at=utc(approval['expires_epoch']));audit.start(aid,now,authority_check=lambda:self.approval('worker_hold_deployment'))
  self.c.transition({'worker_deployment_intent':{'action_id':aid,'approval_reference':self.approval('worker_hold_deployment'),'bundle_sha256':r['worker_bundle_sha256'],'before_settings_sha256':digest(before['settings'])}},'worker_deployment_intent')
  require(not (self.root/'worker-attempted.json').exists(),'Worker_already_attempted_GET_only')
  atomic_json(self.root/'worker-attempted.json',{'at':time.time(),'bundle_sha256':file_hash(bundle),'approval_sha256':file_hash('/etc/optibrain/migration/owner-approvals.json')})
  e=env_file('/etc/opticable-workflow-api.env');os.environ.update(e)
  from workflow.config import load_settings
  cfg=load_settings().cloudflare
  # Exactly one approved deploy command. Logs retained privately, never email tokens.
  env={'PATH':'/usr/bin:/bin','HOME':'/root','CLOUDFLARE_API_TOKEN':cfg.api_token,'CLOUDFLARE_ACCOUNT_ID':ACCOUNT,'WRANGLER_SEND_METRICS':'false'}
  result=run(['/usr/bin/node',r['wrangler_script'],'deploy','--config',r['worker_config'],'--no-bundle',str(bundle),'--var','CORE_INTAKE_HOLD_REQUIRED:true','--keep-vars'],timeout=180,env=env)
  (self.root/'worker-deploy.log').write_bytes(result.stdout+result.stderr)
  after=self.observe('WORKER_HELD');self.verify('WORKER_HELD',before,after)
  audit.finish(aid,datetime.now(timezone.utc),provider_success=True,actual_after=after,verified=True,response={'bundle_sha256':file_hash(bundle)})
  return {'one_deploy_attempt':True}
 def crm(self,plan_only):
  # Reuse exact existing reconciler; fresh proposal is approval-bound before any POST.
  r=self.p['runtime'];os.environ.update(env_file('/etc/opticable-workflow-api.env'));os.environ['OPTIBRAIN_INTAKE_MODE']='hold-v1';os.environ['OPTICABLE_AUTOMATION_ENABLED']='false';os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY']=self.p['scopes']['crm_notification_recreation']['expires_at']
  script=Path('/opt/opticable-api-platform/ops/phase5/recreate_expired_notification.py') if not plan_only else Path(r['crm_script'])
  argv=[PYTHON,'-B',str(script),'--database','/var/lib/opticable-workflow-api/output/automation/automation.db','--expiry',self.p['scopes']['crm_notification_recreation']['expires_at']]
  if plan_only:
   sys.path.insert(0,'/opt/opticable-api-platform/apps/workflow-api')
   spec=importlib.util.spec_from_file_location('reviewed_crm_recreation',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   from dataclasses import replace
   from workflow.config import load_settings
   from workflow.zoho_oauth import ZohoOAuthManager
   from workflow.zoho_gateway import ZohoGatewayClient
   settings=load_settings()
   with tempfile.TemporaryDirectory(prefix='crm-read-') as t:
    auth=replace(settings.zoho_oauth,credentials_path=Path(t)/'credentials.json',access_cache_path=Path(t)/'cache.json')
    for src,dst in ((settings.zoho_oauth.credentials_path,auth.credentials_path),(ZohoOAuthManager(settings.zoho_oauth).cache_path,auth.access_cache_path)):
     if src.is_file():shutil.copyfile(src,dst);dst.chmod(0o600)
    client=ZohoGatewayClient(replace(settings.zoho_gateway,standby_enabled=False),ZohoOAuthManager(auth))
    doc=module.DesiredStateDocument.model_validate_json((module.ROOT/'apps/workflow-api/config/automation/desired-state/zoho-crm-notification.template.json').read_text())
    reconciler=module.controller(client,module.ReadOnlyStore(Path('/var/lib/opticable-workflow-api/output/automation/automation.db'))).registry.resolve(doc.resources[0])
    actual=reconciler.read(doc.resources[0])
    if actual is None:return module.proposal(client,module.ReadOnlyStore(Path('/var/lib/opticable-workflow-api/output/automation/automation.db')),doc,self.p['scopes']['crm_notification_recreation']['expires_at'])
    os.environ['OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY']=self.p['scopes']['crm_notification_recreation']['expires_at']
    destination,token,expiry,channel=reconciler.configuration(doc.resources[0])
    desired={'channel_id':channel,'events':['Leads.create','Leads.edit'],'expiry':expiry.isoformat(),'configuration_hash':digest([destination,token]),'authentication_matches':True,'destination_matches':True,'related_actions':False,'field_values':False,'conditions_absent':True}
    require(actual==desired,'CRM_channel_drift_or_expiry')
    return {'status':'PASS_EXISTING_EXACT_CHANNEL','channel_sha256':digest(actual),'actual':actual}
  proposed=json.loads(run(argv,timeout=60).stdout);scope=self.p['scopes']['crm_notification_recreation'];require(proposed['plan_hash']==scope.get('plan_hash') and proposed['prior_intent_sha256']==scope['prior_intent_sha256'],'CRM_exact_proposal_changed')
  a=self.approval('crm_notification_recreation');f=Path('/etc/optibrain/migration/crm-approval.json');atomic_json(f,{**proposed,'approved':True,'candidate_sha':self.p['scopes']['new_only_intake_release']['candidate_sha'],'approved_at':utc(a['issued_epoch']),'expires_at':utc(a['expires_epoch']),'receiver_hold_verified':True,'owner_authorization_reference':a['owner_authorization_reference']})
  result=run([*argv,'--approval',str(f)],timeout=90);return json.loads(result.stdout)
 def resume_observer(self):
  sys.path.insert(0,str(TOOL/'ops/rebuild'));from engine import SAFETY
  env=Path('/etc/optibrain/migration/observer-off.env');env.write_text('\n'.join(k+'='+v for k,v in SAFETY.items())+'\n');env.chmod(0o600)
  for suffix in ('service','timer'):
   unit='opticable-phase9-intake-receipts.'+suffix;src=TOOL/'ops/rebuild/reviewed/systemd'/unit;dest=Path('/etc/systemd/system')/unit
   if dest.is_symlink():require(os.readlink(dest)=='/dev/null','observer_unexpected_symlink');dest.rename(self.root/(unit+'.original-mask'))
   require(not dest.exists(),'observer_definition_changed');shutil.copyfile(src,dest);dest.chmod(0o644)
  drop=Path('/etc/systemd/system/opticable-phase9-intake-receipts.service.d/zzzz-migration-safe.conf');drop.parent.mkdir(exist_ok=True);drop.write_text('[Service]\nEnvironmentFile=\nEnvironmentFile=/etc/opticable-workflow-api.env\nEnvironmentFile=/etc/optibrain/phase9-receipt-export.env\nEnvironmentFile=/etc/optibrain/migration/observer-off.env\n');drop.chmod(0o644)
  run(['systemctl','daemon-reload']);run(['systemctl','start','opticable-phase9-intake-receipts.service'],timeout=120);run(['systemctl','enable','--now','opticable-phase9-intake-receipts.timer'])

def legacy_upload(module,client,cipher,key,root):
 # The legacy uploader emits progress. Keep helper stdout a single JSON result.
 from contextlib import redirect_stdout
 with redirect_stdout(sys.stderr):module.transfer(client,cipher,key,root)


def offhost(cipher,label):
 spec=importlib.util.spec_from_file_location('migration_existing_upload','/usr/local/lib/optibrain-backup/optibrain-phase2a-upload.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
 import boto3
 from botocore.config import Config
 values={}
 for line in Path('/etc/optibrain/phase2a.conf').read_text().splitlines():
  if line.strip() and not line.lstrip().startswith('#'):
   k,v=line.split('=',1);values[k.strip()]=shlex.split(v)[0]
 cred=configparser.ConfigParser();cred.read('/etc/optibrain/r2-uploader.env');c=boto3.client('s3',endpoint_url='https://'+values['OPTIBRAIN_PHASE2A_ACCOUNT_ID']+'.r2.cloudflarestorage.com',aws_access_key_id=cred['default']['aws_access_key_id'],aws_secret_access_key=cred['default']['aws_secret_access_key'],region_name='auto',config=Config(signature_version='s3v4',connect_timeout=10,read_timeout=45,retries={'mode':'standard','total_max_attempts':3}))
 c.meta.events.register('before-call.s3.PutObject',u.create_only_header);key='backups/'+datetime.now(timezone.utc).strftime('%Y/%m/%d')+'/migration-executor-'+label+'.tar.gz.age';legacy_upload(u,c,cipher,key,ROOT)
 head=c.head_object(Bucket=u.BUCKET,Key=key);v=c.get_object(Bucket=u.BUCKET,Key=key,IfMatch=head['ETag']);h=hashlib.sha256();size=0
 try:
  for b in v['Body'].iter_chunks(chunk_size=1024**2):h.update(b);size+=len(b)
 finally:v['Body'].close()
 require(h.hexdigest()==file_hash(cipher) and size==cipher.stat().st_size==head['ContentLength'],'offhost_full_hash_failed');return {'status':'PASS','object_key':key,'ciphertext_sha256':h.hexdigest(),'bytes':size,'full_get_verified':True}

def verified_OLD_health(live,p):
 monitor=['ssh','-i','/etc/optibrain/migration/source-probe-key','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/etc/optibrain/migration/source-known-hosts','-o','ConnectTimeout=10','optibrain@148.113.249.7','status']
 health=json.loads(run(monitor,timeout=30).stdout)
 require(health.get('host')==p['source']['host'] and health.get('production_sha')==p['production_sha']
  and not health.get('fenced') and health['API'].get('status')=='ok'
  and all(v=='active' for v in health['services'].values()),'OLD_private_API_not_healthy_do_not_resume_queue')
 return health

def conditional_rollback(p):
 live=Live(p);c=live.c;s=c.state() or {};done=s.get('completed_stages',[]);source=live.source('status')
 observed={'dns':live.edge(DNS)['content'],'source_fenced':source['fenced'],'queue_held':live.edge(QUEUE)['settings'].get('delivery_paused') is True,'forms_held':live.forms()['held'],'new_data':source.get('state',{}).get('new_data_observed') is True or 'INTAKE_RELEASED' in done or (live.root/'INTAKE_RELEASED.json').exists(),'worker_changed':'WORKER_HELD' in done or (live.root/'worker-attempted.json').exists() or digest(live.edge(WORKER+'/settings'))!=p['scopes']['worker_hold_deployment']['before_settings_sha256'] or digest(live.edge(WORKER+'/versions'))!=p['runtime']['worker_before_versions_sha256']}
 resume_id=c.action_id('migration-provider','safe_queue_observer_resume');resume_action=c.audit.store.get(resume_id)
 if (not observed['new_data'] and not observed['worker_changed'] and observed['dns']=='148.113.249.7'
  and not observed['source_fenced'] and not observed['queue_held'] and observed['forms_held']
  and source.get('state',{}).get('event')=='ROLLED_BACK' and source['state'].get('rollback_verified_epoch')
  and resume_action and resume_action['status'] in ('STARTED','SUCCEEDED')
  and resume_action['exact_versions'].get('package_sha256')==profile_binding(p)
  and resume_action['proposed_state'].get('settings',{}).get('delivery_paused') is False):
  verified_OLD_health(live,p)
  if resume_action['status']=='STARTED':
   c.audit.store.finish(resume_id,datetime.now(timezone.utc),provider_success=True,actual_after=live.edge(QUEUE),verified=True,response={'verification':'independent_GET_after_uncertain_ack_no_provider_retry'})
  return c.transition({'status':'ROLLED_BACK','authority':'OLD','rollback':'OLD healthy and original Worker; approved queue resume independently reconciled without retry; Forms await owner reopen'},'rollback_resume_readback_verified')
 choice=rollback_choice(done,observed)
 if s.get('rollback_decision')==choice and s.get('rollback_observed')==observed and s.get('status') in ('REQUIRES_OWNER','ROLLED_BACK'):return s
 c.transition({'rollback_decision':choice,'rollback_observed':observed},'conditional_rollback_review')
 if choice in ('CONTAIN_AND_RECONCILE_NEW','REQUIRES_OWNER_NO_AUTHORITY_CHANGE'):
  return c.transition({'status':'REQUIRES_OWNER','blocker':choice,'rollback':'OLD remains fenced; preserve all NEW state; no DNS reversal or stale restoration'},'rollback_contained')
 # Automatic compensation requires explicit rollback permission INSIDE the existing exact scopes.
 a=live.approval('source_freeze_final_sync');require(a.get('conditional_rollback_approved') is True,'conditional_rollback_not_approved')
 if choice.startswith('RESTORE_OLD'):
  if observed['source_fenced']:
   live.source('rollback',scope=a,extra={'rollback_proof':{'dns':observed['dns'],'worker_original_verified':True,'queue_held':True,'forms_held':True,'target_intake_never_released':True}})
  else:require(source.get('state',{}).get('event')=='ROLLED_BACK' and source['state'].get('rollback_verified_epoch'),'source_rollback_unverified_no_duplicate_restore')
 verified_OLD_health(live,p)
 resume=live.approval('safe_queue_observer_resume');require(resume.get('conditional_OLD_queue_resume_approved') is True,'OLD_queue_resume_not_approved')
 live.edge_write(QUEUE,{'queue_name':'opticable-business-events','settings':{'delivery_paused':False}},'safe_queue_observer_resume');return c.transition({'status':'ROLLED_BACK','authority':'OLD','rollback':'OLD healthy, original Worker verified; Forms remain explicitly held for owner reopen'},'rollback_verified')

def main():
 a=argparse.ArgumentParser();a.add_argument('mode',choices=('execute','verify','rollback','seal-final'));a.add_argument('stage',nargs='?');args=a.parse_args();require(os.geteuid()==0 and os.uname().nodename=='vps-f8e9b20e','NEW_root_only');p=load_profile('/etc/optibrain/migration/profile.json')
 if args.mode=='rollback':print(json.dumps(conditional_rollback(p)));return
 if args.mode=='seal-final':
  live=Live(p);s,d,a=live.final_paths();print(json.dumps(offhost(d/(a.name+'.age'),'final-'+s['generation'])));return
 require(args.stage in STAGE_SCOPE,'unknown_stage');live=Live(p);adapter=Adapters(p,live,live.root,'/etc/optibrain/migration/owner-approvals.json');inputs=os.environ['OPTIBRAIN_MIGRATION_INPUT_SHA256'];print(json.dumps(getattr(adapter,args.mode)(args.stage,inputs)))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'status':'BLOCKED','error':str(e),'retry':'RECONCILE_ONLY'}));raise SystemExit(1)
