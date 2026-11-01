#!/usr/bin/env python3
"""OLD-only signed command bridge; fixed verbs, no shell or arbitrary paths.
Installation is inert: only approved freeze creates the persistent writer fence.
"""
import base64,fcntl,hashlib,json,os,re,shlex,shutil,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/var/lib/optibrain-migration-source')
CODE=Path('/usr/local/lib/optibrain-migration')
CONFIG=Path('/etc/optibrain-migration-source.json')
RAM=Path('/dev/shm/optibrain-intake-handoff-20261028')
NAMES=('optibrain-backup','optibrain-phase2a-upload','opticable-phase9-intake-receipts','opticable-phase10-service-events','opticable-phase12-test-runner','opticable-lifecycle-internal','opticable-customer-communications')
APPS=('opticable-workflow-api.service','opticable-password-pdf.service','opticable-omada-site.service')
UNITS=tuple(n+'.'+k for n in NAMES for k in ('timer','service'))+APPS
VERBS={'read-control','providers','preflight','status','heartbeat','freeze','capture','read-archive','read-receipt','rollback'}

def need(v,s):
 if not v:raise RuntimeError(s)
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024**2),b''):h.update(b)
 return h.hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 fd,t=tempfile.mkstemp(prefix='.state-',dir=p.parent)
 with os.fdopen(fd,'wb') as f:os.fchmod(f.fileno(),0o600);f.write(canonical(v)+b'\n');f.flush();os.fsync(f.fileno())
 os.replace(t,p);fd=os.open(p.parent,os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def private(p):
 p=Path(p);s=p.lstat();need(p.is_file() and not p.is_symlink() and s.st_uid==0 and s.st_mode&0o777==0o600,'private_file_required')
 return json.loads(p.read_text())
def command(argv,timeout=30):return subprocess.check_output(argv,text=True,stderr=subprocess.PIPE,timeout=timeout).strip()
def states():return {u:command(['systemctl','show',u,'-p','ActiveState','--value']) for u in UNITS}
def journal(event,**changes):
 with (ROOT/'state.lock').open('a') as state_lock:
  fcntl.flock(state_lock,fcntl.LOCK_EX)
  s=private(ROOT/'state.json') if (ROOT/'state.json').exists() else {}
  before=hashlib.sha256(canonical(s)).hexdigest();s.update(changes,event=event,at=datetime.now(timezone.utc).isoformat())
  log=ROOT/'journal.jsonl';row={'event':event,'at':s['at'],'before_sha256':before,'after_sha256':hashlib.sha256(canonical(s)).hexdigest(),'previous_journal_sha256':sha(log) if log.exists() else None}
  with log.open('ab') as f:os.fchmod(f.fileno(),0o600);f.write(canonical(row)+b'\n');f.flush();os.fsync(f.fileno())
  save(ROOT/'state.json',s);return s

def verify_request(wire,cfg,now=None):
 need(sha(__file__)==cfg['scopes']['source_freeze_final_sync']['source_executor_sha256'],'source_executor_revision_changed');need(set(wire)=={'payload','signature'},'signed_envelope_required');p=wire['payload'];epoch=time.time() if now is None else now
 need(p.get('verb') in VERBS and p.get('execution_id')==cfg['execution_id'],'verb_or_execution_denied')
 need(p.get('source')==cfg['source'] and p.get('target')==cfg['target'] and p.get('package_sha256')==cfg['package_sha256'],'identity_or_package_changed')
 need(isinstance(p.get('issued_epoch'),(int,float)) and isinstance(p.get('expires_epoch'),(int,float)) and p['issued_epoch']-5<=epoch<p['expires_epoch']<=p['issued_epoch']+120,'request_expired')
 with tempfile.TemporaryDirectory(prefix='source-verify-',dir='/run') as t:
  f=Path(t);(f/'message').write_bytes(canonical(p));(f/'sig').write_bytes(base64.b64decode(wire['signature'],validate=True))
  r=subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',cfg['public_key'],'-rawin','-in',str(f/'message'),'-sigfile',str(f/'sig')],capture_output=True,timeout=10)
  need(r.returncode==0,'signature_denied')
 if p['verb'] in {'freeze','capture','rollback'}:
  a=p.get('scope_approval',{});scope=cfg['scopes']['source_freeze_final_sync']
  need(a.get('approved') is True and a.get('binding_sha256')==hashlib.sha256(canonical(scope)).hexdigest(),'source_scope_not_approved')
  need(a.get('owner_authorization_reference') and re.fullmatch('[0-9a-f]{64}',a.get('owner_authorization_sha256','')),'actual_owner_reference_required')
  need(a['issued_epoch']<=epoch<a['expires_epoch']<=a['issued_epoch']+3600,'source_scope_expired')
 return p

def install_fence(cfg):
 """Conditions are persistent on disk; absent marker leaves running OLD unchanged."""
 need(not (ROOT/'FROZEN').exists(),'cannot_install_over_active_fence')
 for u in UNITS:
  p=Path('/etc/systemd/system')/(u+'.d')/'00-optibrain-migration-fence.conf';p.parent.mkdir(parents=True,exist_ok=True)
  text='[Unit]\nConditionPathExists=!'+str(ROOT/'FROZEN')+'\n'
  need(not p.exists() or p.read_text()==text,'existing_fence_conflict');p.write_text(text);p.chmod(0o644)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 save(ROOT/'fence-installed.json',{'units':list(UNITS),'marker':str(ROOT/'FROZEN'),'marker_present':False,'code_sha256':sha(__file__),'installed_epoch':time.time()})

def assert_fence():
 for u in UNITS:
  p=Path('/etc/systemd/system')/(u+'.d')/'00-optibrain-migration-fence.conf'
  need(p.is_file() and p.read_text()=='[Unit]\nConditionPathExists=!'+str(ROOT/'FROZEN')+'\n','persistent_fence_missing')
  unit_path=shlex.split(command(['busctl','call','org.freedesktop.systemd1','/org/freedesktop/systemd1','org.freedesktop.systemd1.Manager','LoadUnit','s',u]))[1]
  effective=command(['busctl','get-property','org.freedesktop.systemd1',unit_path,'org.freedesktop.systemd1.Unit','Conditions'])
  need('\"ConditionPathExists\" false true \"'+str(ROOT/'FROZEN')+'\"' in effective,'effective_fence_missing')
 return True

def hydrate(cfg):
 RAM.mkdir(mode=0o700,exist_ok=True)
 for name,h in cfg['artifact_sha256'].items():
  src=CODE/'artifacts'/name;need(sha(src)==h,'source_artifact_changed')
  dest=RAM/name
  if dest.exists():need(sha(dest)==h,'RAM_artifact_changed')
  else:shutil.copyfile(src,dest);dest.chmod(0o600)

def source_job(verb):
 cfg=private(CONFIG);request=private(ROOT/(verb+'-request.json'));p=verify_request(request,cfg)
 # A job starts promptly; its durable owner approval remains bounded to the hour.
 with (ROOT/'job.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);assert_fence();hydrate(cfg)
  s=private(ROOT/'state.json') if (ROOT/'state.json').exists() else {}
  if verb=='freeze':
   need(not s.get('new_data_observed'),'NEW_data_forbids_OLD_restore')
   need(p.get('readiness',{}).get('queue_held') and p['readiness'].get('forms_held') and p['readiness'].get('workflows_drained') and p['readiness'].get('owner_access_verified') and p['readiness'].get('providers_verified'),'freeze_prerequisite_missing')
   command(['/usr/bin/python3','-B',str(RAM/'preflight-final-source.py'),str(RAM/'final-identity-pins.json')],90)
   if not (ROOT/'FROZEN').exists():
    before=states();journal('FREEZE_INTENT',before_units=before,approval=p['scope_approval'],execution_id=p['execution_id'],authority='OLD',freeze_started_epoch=time.time())
    save(ROOT/'FROZEN',{'execution_id':p['execution_id'],'approval_sha256':hashlib.sha256(canonical(p['scope_approval'])).hexdigest()})
   else:need(s.get('before_units') and s.get('approval')==p['scope_approval'],'existing_fence_not_this_approval')
   subprocess.run(['systemctl','stop',*[n+'.timer' for n in NAMES]],check=True,timeout=30)
   deadline=time.monotonic()+120
   while any(states()[n+'.service'] not in ('inactive','failed') for n in NAMES):
    need(time.monotonic()<deadline,'existing_writer_did_not_drain');time.sleep(1)
   with sqlite3.connect('file:/var/lib/opticable-workflow-api/output/automation/automation.db?mode=ro',uri=True) as db:
    need(db.execute("SELECT count(*) FROM automation_runs WHERE status IN ('queued','running','retrying')").fetchone()[0]==0,'active_runs_not_drained')
    need(db.execute('SELECT count(*) FROM automation_sync_checkpoints WHERE lease_token IS NOT NULL').fetchone()[0]==0,'lease_not_drained')
   with sqlite3.connect('file:/var/lib/opticable-workflow-api/output/automation/phase9-form-receipts.db?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row;rows=[dict(r) for r in db.execute("SELECT * FROM form_enrichment_journal WHERE state='ATTEMPTED' ORDER BY id")]
   known=private(RAM/'known-Forms-ambiguity.json');need(len(rows)==known['rows'] and hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==known['sha256'],'new_uncertain_Forms_effect')
   subprocess.run(['systemctl','stop',*APPS],check=True,timeout=90)
   need(all(v in ('inactive','failed') for v in states().values()),'writer_still_active')
   journal('SOURCE_FROZEN',frozen_at=datetime.now(timezone.utc).isoformat(),frozen=True,source_sha=cfg['production_sha'])
  else:
   need(s.get('frozen') and (ROOT/'FROZEN').exists() and all(v in ('inactive','failed') for v in states().values()),'source_not_frozen')
   mem=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
   need(mem>=3*1024**3 and shutil.disk_usage('/dev/shm').free>=1536*1024**2,'RAM_capture_capacity_insufficient')
   capture=Path('/dev/shm/optibrain-final-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));capture.mkdir(mode=0o700)
   subprocess.run(['mount','-t','tmpfs','-o','size=2G,mode=0700','tmpfs',str(capture)],check=True)
   (capture/'runtime').mkdir(mode=0o700);journal('CAPTURE_INTENT',capture_root=str(capture))
   with (capture/'capture.log').open('wb') as log:
    subprocess.run(['/usr/bin/bash',str(RAM/'final-capture-ram.sh'),'--config','/dev/null','--output-dir',str(capture),'--preserve-existing'],check=True,timeout=600,stdout=log,stderr=log,env={**os.environ,'TMPDIR':str(capture/'runtime'),'OPTIBRAIN_OWNER_APPROVED_FINAL_CAPTURE':'vps-214ba8cd-to-vps-f8e9b20e','PYTHONDONTWRITEBYTECODE':'1'})
   archives=list(capture.glob('optibrain-backup-*.tar.gz'));need(len(archives)==1,'capture_archive_missing');archive=archives[0];generation=archive.name[17:-7]
   freeze={'frozen_at':s['frozen_at'],'old_host':cfg['source']['host'],'new_host':cfg['target']['host'],'writers_off':True,'observers_off':True,'intake_off':True,'external_intake_held':True,'source_sha':cfg['production_sha'],'recovery_generation':generation,'before_freeze_units':{u:{'ActiveState':v} for u,v in s['before_units'].items()},'approval_sha256':hashlib.sha256(canonical(p['scope_approval'])).hexdigest()}
   save(capture/'source-freeze.json',freeze)
   journal('CAPTURED',archive=str(archive),archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,freeze_receipt=str(capture/'source-freeze.json'),freeze_receipt_sha256=sha(capture/'source-freeze.json'),generation=generation)

def rollback(p):
 s=private(ROOT/'state.json');need((ROOT/'FROZEN').exists(),'no_active_fence')
 proof=p.get('rollback_proof',{})
 need(proof.get('dns')=='148.113.249.7' and proof.get('worker_original_verified') and proof.get('queue_held') and proof.get('forms_held') and proof.get('target_intake_never_released') and not s.get('new_data_observed'),'unsafe_rollback_preserve_fence')
 journal('ROLLBACK_INTENT',rollback_proof=proof)
 # Preserve the old fence marker as evidence; remove its blocking pathname only.
 os.replace(ROOT/'FROZEN',ROOT/('FROZEN.rolled-back-'+str(int(time.time()))))
 for u,v in s['before_units'].items():
  if v=='active':subprocess.run(['systemctl','start',u],check=True,timeout=90)
 actual=states();need(all(actual[u]=='active' for u,v in s['before_units'].items() if v=='active'),'OLD_restore_unverified')
 return journal('ROLLED_BACK',frozen=False,authority='OLD',rollback_verified_epoch=time.time())

def owner_alert(incident):
 sys.path.insert(0,str(CODE/'control/ops/rebuild'))
 from durable_migration import Control
 from owner_notifications import notify
 cfg=private(CONFIG);c=Control(ROOT/'alerts.db',cfg['execution_id']+'-old-supervisor')
 if not c.state():c.transition({'current_stage':'SOURCE_FROZEN','authority':'OLD','status':'REQUIRES_OWNER'},'OLD_independent_supervision')
 # Same pre-authorized owner-only mailbox and canonical notifier; no second TEST.
 return notify(c,{'execution_id':cfg['execution_id'],'source':cfg['source'],'target':cfg['target']},CODE/'owner-notification-policy.json','CRITICAL',incident,delays=(0,))

def verified_stream(path,offset,prefix,output):
 need(isinstance(offset,int) and 0<=offset<=path.stat().st_size,'stream_offset_invalid')
 with path.open('rb') as f:
  if offset:
   h=hashlib.sha256();remaining=offset
   while remaining:
    block=f.read(min(1024**2,remaining));need(block,'source_prefix_short');h.update(block);remaining-=len(block)
   need(h.hexdigest()==prefix,'partial_transfer_prefix_mismatch')
  shutil.copyfileobj(f,output,1024**2)

def main():
 need(os.geteuid()==0 and os.uname().nodename=='vps-214ba8cd','OLD_root_only');ROOT.mkdir(mode=0o700,exist_ok=True)
 if sys.argv[1:]==['notify-failure']:return owner_alert('OLD-fence-supervisor-failed')
 if sys.argv[1:]==['install-fence']:return install_fence(private(CONFIG))
 if sys.argv[1:]==['supervise']:
  s=private(ROOT/'state.json') if (ROOT/'state.json').exists() else {}
  if (ROOT/'FROZEN').exists():
   assert_fence();draining=s.get('event')=='FREEZE_INTENT' and time.time()-s.get('freeze_started_epoch',0)<210 and command(['systemctl','show','optibrain-source-freeze.service','-p','ActiveState','--value']) in ('active','activating')
   need(draining or all(v in ('inactive','failed') for v in states().values()),'CRITICAL_fenced_writer_running')
   # No uncertain restart: preserve persistent fence through NEW power/network loss.
   age=time.time()-s.get('freeze_started_epoch',time.time())
   save(ROOT/'supervision.json',{'at_epoch':time.time(),'fenced':True,'hold_review_due':age>=2700,'hold_limit_reached':age>=3600,'new_heartbeat_stale':time.time()-s.get('new_heartbeat_epoch',0)>120,'recovery':'CONTAIN_OLD_NO_AUTOMATIC_RESTART'})
   if not s.get('window_complete') and age>=3600:owner_alert('OLD-hold-limit-reached')
   elif not s.get('window_complete') and age>=2700:owner_alert('OLD-hold-review-due')
   elif time.time()-s.get('new_heartbeat_epoch',s.get('freeze_started_epoch',time.time()))>120:owner_alert('NEW-heartbeat-lost-OLD-remains-fenced')
  return
 if len(sys.argv)==3 and sys.argv[1]=='job' and sys.argv[2] in ('freeze','capture'):return source_job(sys.argv[2])
 need(sys.argv[1:]==['execute'],'fixed_protocol_required');data=sys.stdin.buffer.read(65537);need(len(data)<=65536,'request_too_large');cfg=private(CONFIG);wire=json.loads(data);p=verify_request(wire,cfg);verb=p['verb']
 s=private(ROOT/'state.json') if (ROOT/'state.json').exists() else {}
 if verb=='read-control':
  import io,tarfile
  files={}
  for name in ('state.json','journal.jsonl','supervision.json','freeze-request.json','capture-request.json','FROZEN','fence-installed.json'):
   f=ROOT/name
   if f.exists():need(f.stat().st_size<=10*1024**2,'source_control_export_bound');files[name]=f.read_bytes()
  if (ROOT/'alerts.db').exists():
   with sqlite3.connect((ROOT/'alerts.db').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(':memory:') as dst:
    src.backup(dst);files['alerts.db']=dst.serialize()
  files['control-manifest.json']=canonical({'files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}})
  with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
   for name,data in files.items():
    info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o600;archive.addfile(info,io.BytesIO(data))
  return
 if verb=='providers':
  sys.path.insert(0,'/home/optibrain/worktrees/optibrain-rebuild-migration/ops/rebuild')
  from providers import probe_all
  m=json.loads(Path('/home/optibrain/worktrees/optibrain-rebuild-migration/docs/rebuild/current-host-manifest.json').read_text())
  # Fixed reviewed read-only provider probes; disposable credential copies in RAM.
  os.environ['TMPDIR']='/dev/shm';tempfile.tempdir='/dev/shm'
  result=probe_all(manifest=m);print(json.dumps({'providers':result,'required':m['bootstrap']['required_providers'],'all_required_pass':all(result.get(k,{}).get('status')=='PASS' for k in m['bootstrap']['required_providers'])}));return
 if verb=='preflight':
  hydrate(cfg);print(command(['/usr/bin/python3','-B',str(RAM/'preflight-final-source.py'),str(RAM/'final-identity-pins.json')],90));return
 if verb in ('freeze','capture'):
  pending=ROOT/(verb+'-request.json')
  if pending.exists():
   need(private(pending)['payload']['scope_approval']==p['scope_approval'],'stage_already_attempted_no_replacement')
   if command(['systemctl','show','optibrain-source-'+verb+'.service','-p','ActiveState','--value']) in ('active','activating'):return print(json.dumps({'status':'PASS','job':'ALREADY_RUNNING'}))
   if verb=='freeze' and s.get('frozen'):return print(json.dumps({'status':'PASS','job':'ALREADY_FROZEN'}))
   if verb=='capture' and s.get('archive') and Path(s['archive']).exists():return print(json.dumps({'status':'PASS','job':'ALREADY_CAPTURED'}))
   save(pending,wire)
  else:save(pending,wire)
  subprocess.run(['systemctl','reset-failed','optibrain-source-'+verb+'.service'],capture_output=True)
  subprocess.run(['systemd-run','--quiet','--unit=optibrain-source-'+verb,'--property=RuntimeMaxSec=900','--property=UMask=0077','--','/usr/bin/python3','-B',str(CODE/'source_executor.py'),'job',verb],check=True,timeout=15)
 elif verb=='heartbeat':
  # Heartbeats cannot alter authority, approvals, freeze state or deadlines.
  with (ROOT/'state.lock').open('a') as state_lock:
   fcntl.flock(state_lock,fcntl.LOCK_EX)
   if (ROOT/'state.json').exists():
    latest=private(ROOT/'state.json');save(ROOT/'state.json',{**latest,'new_heartbeat_epoch':time.time(),'new_data_observed':latest.get('new_data_observed',False) or p.get('new_intake_exposed') is True,'window_complete':latest.get('window_complete',False) or p.get('window_complete') is True})
 elif verb=='rollback':s=rollback(p)
 elif verb in ('read-archive','read-receipt'):
  need(s.get('event')=='CAPTURED' or s.get('archive'),'capture_not_verified');path=Path(s['archive' if verb=='read-archive' else 'freeze_receipt'])
  need(path.is_file() and not path.is_symlink() and str(path).startswith('/dev/shm/optibrain-final-'),'RAM_capture_lost_recovery_required')
  expected=s['archive_sha256' if verb=='read-archive' else 'freeze_receipt_sha256'];need(sha(path)==expected,'source_stream_hash_changed')
  verified_stream(path,p.get('offset',0),p.get('prefix_sha256'),sys.stdout.buffer)
  return
 s=private(ROOT/'state.json') if (ROOT/'state.json').exists() else {}
 print(json.dumps({'status':'PASS','host':os.uname().nodename,'persistent_fence_installed':assert_fence(),'fenced':(ROOT/'FROZEN').exists(),'units':states(),'state':s,'journal_sha256':sha(ROOT/'journal.jsonl') if (ROOT/'journal.jsonl').exists() else None,'supervision':private(ROOT/'supervision.json') if (ROOT/'supervision.json').exists() else None}))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'BLOCKED','error':str(e),'no_blind_retry':True}),file=sys.stderr);raise SystemExit(1)
