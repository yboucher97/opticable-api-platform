#!/usr/bin/python3
"""Local-only resource telemetry and isolated verification. Never sends or prunes history."""
import argparse, collections, datetime as dt, fcntl, hashlib, importlib.util, json, os
from pathlib import Path
import shutil, sqlite3, subprocess, tempfile, time, urllib.request, sys
ROOT=Path('/var/lib/optibrain/resource-management')
G=1024**3
DBROOT=Path('/var/lib/opticable-workflow-api/output/automation')
DBS=[DBROOT/n for n in ['automation.db','phase9-form-receipts.db','phase9-intake.db','phase10-service-events.db','phase12-autonomy.db']]+[Path('/var/lib/optibrain-rebuild/actions.db'),Path('/var/lib/optibrain/acquisition-intelligence/lab.sqlite')]
DIRS={'local_recovery':'/var/backups/optibrain','retained_recovery':'/recovery','encrypted_spool':'/var/lib/optibrain/phase2a','application_state':'/var/lib/opticable-workflow-api','root_history':'/var/lib/optibrain','migration_audit':'/var/lib/optibrain-rebuild','diagnostic_logs':'/var/log','verification_scratch':'/var/backups/optibrain/verification-scratch','runtime_scratch':'/var/backups/optibrain/runtime-scratch','isolated_scratch':'/var/lib/optibrain/resource-management/isolated-scratch'}
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def readjson(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return default

def atomic(p,v):
 fd,n=tempfile.mkstemp(prefix='.resource-',dir=p.parent)
 with os.fdopen(fd,'w') as f:json.dump(v,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(n,p)

def append(p,v):
 with p.open('a') as f:f.write(json.dumps(v,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024**2),b''):h.update(b)
 return h.hexdigest()

def forecast(rows):
 # >=24h, last seven days; net filesystem trend is distinct from artifact estimates.
 if len(rows)<2 or rows[-1]['time']-rows[0]['time']<86400:return None
 slopes=[(b['used']-a['used'])/(b['time']-a['time'])*86400 for a,b in zip(rows,rows[1:]) if b['time']>a['time'] and b['time']-a['time']>=300]
 return {'net_bytes_per_day':(rows[-1]['used']-rows[0]['used'])/(rows[-1]['time']-rows[0]['time'])*86400,'peak_interval_bytes_per_day':max(slopes,default=0),'span_days':(rows[-1]['time']-rows[0]['time'])/86400}

def assess(s,prior,trend):
 alerts=[]
 storage=s.get('business_storage',{})
 if storage.get('state')=='ERROR':alerts.append({'key':'business_storage','severity':'WARNING','reason':'disposable classification unavailable; generation remains fail-closed'})
 elif storage.get('optional_paused'):alerts.append({'key':'business_storage','severity':'WARNING','reason':'optional generation paused: '+','.join(storage.get('pause_reasons',[]))})
 for level,bound in [('EMERGENCY',25),('CRITICAL',35),('WARNING',50)]:
  if s['available']<bound*G:alerts.append({'key':'disk','severity':level,'reason':'available below '+str(bound)+' GiB'});break
 if s['inode_free_fraction']<.1:alerts.append({'key':'inodes','severity':'CRITICAL','reason':'less than 10 percent free'})
 for level,bound in [('CRITICAL',3),('WARNING',5)]:
  if s['mem_available']<bound*G and prior and prior['mem_available']<bound*G:
   alerts.append({'key':'memory','severity':level,'reason':'low MemAvailable on consecutive samples'});break
 if trend and trend['net_bytes_per_day']>0:
  days=(s['available']-25*G)/trend['net_bytes_per_day']
  if days<14:alerts.append({'key':'disk_forecast','severity':'CRITICAL','reason':'forecast emergency reserve within 14 days'})
 if prior and s['time']>prior['time']:
  if (s['used']-prior['used'])/(s['time']-prior['time'])*86400>2*G:alerts.append({'key':'abnormal_growth','severity':'WARNING','reason':'net growth exceeds 2 GiB/day equivalent; inspect categories'})
  elapsed=s['time']-prior['time']
  if s['vm']['oom_kill']>prior.get('vm',{}).get('oom_kill',0):alerts.append({'key':'oom','severity':'CRITICAL','reason':'kernel OOM counter increased'})
  if s['vm']['pswpin']-prior.get('vm',{}).get('pswpin',0)>elapsed*256 and s['vm']['pswpout']-prior.get('vm',{}).get('pswpout',0)>elapsed*256:alerts.append({'key':'swap','severity':'WARNING','reason':'sustained bidirectional swap activity'})
 for d in s['databases']:
  if d.get('error'):alerts.append({'key':'db_access:'+d['name'],'severity':'WARNING','reason':'database metadata unavailable'})
  if d['wal_bytes']>max(256*1024**2,d['bytes']*.5):alerts.append({'key':'wal:'+d['name'],'severity':'WARNING','reason':'large WAL; inspect reader/checkpoint starvation; no forced checkpoint'})
 if s['backup_age_hours'] is None or s['backup_age_hours']>30:alerts.append({'key':'backup_stale','severity':'CRITICAL','reason':'verified offsite backup missing or older than 30 hours'})
 for name,state in s.get('services',{}).items():
  if state.get('Result') not in (None,'success'):alerts.append({'key':'service:'+name,'severity':'WARNING','reason':'last service attempt failed; inspect journal'})
 if s.get('restore_age_days') is not None and s['restore_age_days']>8:alerts.append({'key':'restore_stale','severity':'WARNING','reason':'isolated restore verification older than eight days'})
 q=s.get('queues',{})
 if q.get('status')!='measured':alerts.append({'key':'queue_unknown','severity':'WARNING','reason':'queue metrics unavailable; never purge or replay'})
 elif any(v.get('backlog_count',0)>0 for k,v in q.get('queues',{}).items() if k.endswith('-dlq')):alerts.append({'key':'dlq','severity':'WARNING','reason':'dead-letter backlog requires engineering review; no replay or purge'})
 for category in ['verification_scratch','runtime_scratch','isolated_scratch']:
  if (s.get('categories',{}).get(category) or 0)>1024**3:alerts.append({'key':'scratch:'+category,'severity':'WARNING','reason':'scratch exceeds 1 GiB; require proof before cleanup'})
 for d in s.get('database_checks',{}).get('databases',[]):
  if d.get('quick_check')!='ok':alerts.append({'key':'integrity:'+d['name'],'severity':'CRITICAL' if d.get('quick_check')=='FAILED' else 'WARNING','reason':'daily SQLite quick_check not verified ok'})
 if not s['healthy']:alerts.append({'key':'app','severity':'CRITICAL','reason':'local application health check failed'})
 return alerts

def sample():
 t=time.time();u=shutil.disk_usage('/');fs=os.statvfs('/');m={k:int(v.split()[0])*1024 for k,v in (l.split(':',1) for l in Path('/proc/meminfo').read_text().splitlines())};vm=dict((k,int(v)) for k,v in (l.split() for l in Path('/proc/vmstat').read_text().splitlines()) if k in ['pswpin','pswpout','oom_kill'])
 s=dict(at=now(),time=t,used=u.used,available=u.free,total=u.total,inodes=fs.f_files,inodes_free=fs.f_favail,inode_free_fraction=fs.f_favail/max(1,fs.f_files),mem_available=m['MemAvailable'],mem_total=m['MemTotal'],swap_total=m['SwapTotal'],swap_free=m['SwapFree'],vm=vm,load=list(os.getloadavg()),process_count=sum(p.name.isdigit() for p in Path('/proc').iterdir()),pressure={k:Path('/proc/pressure/'+k).read_text() for k in ['memory','cpu','io']},databases=[])
 for p in DBS:
  if not p.exists():continue
  w=Path(str(p)+'-wal');d=dict(name=p.name,path=str(p),bytes=p.stat().st_size,wal_bytes=w.stat().st_size if w.exists() else 0)
  try:
   with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=1) as c:
    c.execute('PRAGMA query_only=ON');d.update(pages=c.execute('PRAGMA page_count').fetchone()[0],free_pages=c.execute('PRAGMA freelist_count').fetchone()[0],page_size=c.execute('PRAGMA page_size').fetchone()[0])
  except sqlite3.Error:d['error']='metadata_unavailable'
  s['databases'].append(d)
 # Backup and scratch size, inode accounting; no reads of business/customer rows.
 s['categories']={}
 for k,p in DIRS.items():
  try:s['categories'][k]=int(subprocess.check_output(['du','-sx','-B1',p],timeout=45).split()[0])
  except (subprocess.SubprocessError,ValueError):s['categories'][k]=None
 s['category_note']='root_history includes encrypted_spool; categories are not additive'
 st=readjson('/var/lib/optibrain/phase2a/state.json',{})
 try:s['backup_age_hours']=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(st['verified_at'])).total_seconds()/3600 if st['verification_status']=='download_hash_verified' else None
 except (KeyError,ValueError):s['backup_age_hours']=None
 s['backup_generation']=st.get('generation');s['offline_restore_verified']=st.get('offline_restore_verified',False)
 try:
  with urllib.request.urlopen('http://127.0.0.1:8100/v1/system/health',timeout=5) as r:s['healthy']=r.status==200
 except Exception:s['healthy']=False
 s['services']={}
 for unit in ['optibrain-backup','optibrain-phase2a-upload','optibrain-resource-verify','optibrain-operations','optibrain-local-retention','optibrain-business-observer','optibrain-credential-refresh','optibrain-operations-capabilities']:
  raw=subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','Result','-p','MemoryPeak','-p','CPUUsageNSec'],text=True,timeout=5)
  s['services'][unit]=dict(l.split('=',1) for l in raw.splitlines() if '=' in l)
 proof=readjson(ROOT/'restore-latest.json',{})
 s['restore_age_days']=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(proof['at'])).total_seconds()/86400 if proof.get('at') else None
 s['database_checks']=readjson(ROOT/'learning-health.json',{})
 s['queues']=readjson('/run/optibrain-readiness/queue-depth.json',{'status':'unavailable'})
 previous=readjson(ROOT/'latest.json');rows=[]
 # Read only current/previous seven dated files; preserve all historical samples.
 for day in range(8):
  p=ROOT/('samples-'+(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=day)).strftime('%Y%m%d')+'.jsonl')
  if p.exists():
   for l in p.read_text().splitlines():
    try:rows.append(json.loads(l))
    except ValueError:continue
 rows=sorted([r for r in rows if r['time']>t-7*86400]+[s],key=lambda r:r['time']);trend=forecast(rows);s['forecast']=trend
 # Same monitoring cadence and alert ledger. Verify the exact root-owned
 # business runtime before importing any lifecycle code with root custody.
 try:
  runtime=Path('/usr/local/share/optibrain-business-autopilot-v1')
  spec=importlib.util.spec_from_file_location('storage_runtime_guard',runtime/'runner.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard);guard.verify_runtime(runtime)
  sys.path.insert(0,str(runtime))
  import lifecycle
  s['business_storage']=lifecycle.monitor()
 except Exception as error:s['business_storage']={'state':'ERROR','error_class':type(error).__name__}
 s['alerts']=assess(s,previous,trend)
 # Audit transitions and 24h reminders locally; no email permission implicit.
 old=readjson(ROOT/'alert-state.json',{});active={}
 for a in s['alerts']:
  last=old.get(a['key'],{});sig=a['severity']+':'+a['reason'];emit=last.get('signature')!=sig or t-last.get('recorded',0)>=86400
  active[a['key']]={'signature':sig,'recorded':t if emit else last['recorded']}
  if emit:append(ROOT/'alerts.jsonl',dict(at=s['at'],event='OPEN_OR_REMINDER',**a))
 for k in old.keys()-active.keys():append(ROOT/'alerts.jsonl',dict(at=s['at'],key=k,event='RECOVERED'))
 atomic(ROOT/'alert-state.json',active);atomic(ROOT/'latest.json',s);append(ROOT/('samples-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')+'.jsonl'),s)
 render(s,'daily')
 if s.get('services',{}).get('optibrain-operations',{}).get('Result') not in (None,'success'):
  # Independent fallback uses the same bounded C ledger, never a second allowance.
  subprocess.run(['/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python','-I','-B','/usr/local/lib/optibrain/operations-notifications.py','HIGH','monitor:optibrain-operations'],check=True,timeout=150)
 return s

def render(s,period):
 remote=readjson(ROOT/'remote-inventory.json',{});verified=readjson(ROOT/'restore-latest.json',{})
 text=['OPTIBRAIN RESOURCE / LEARNING HEALTH — '+s['at'], 'Available disk: %.2f GiB / target 60 GiB'%(s['available']/G),'Available RAM: %.2f GiB'%(s['mem_available']/G),'Health: '+str(s['healthy']),'Verified encrypted backup age (hours): '+str(s['backup_age_hours']),'Isolated restore proof: '+str(verified.get('result','UNKNOWN')),'Offsite decryption: offline owner dependency; never inferred from upload','Net growth forecast: '+json.dumps(s.get('forecast')),'Alerts: '+json.dumps(s['alerts']),'Storage bytes (overlapping root_history/spool): '+json.dumps(s['categories']),'Accessible cloud bytes: '+str(sum(b['bytes'] for b in remote.get('buckets',[]))),'Queue backlog: '+json.dumps(s.get('queues',{})), 'Learning: see learning-health.json; generated repetition is not evidence; AI costs/latency require metering coverage','Email policy: '+('ACTIVE authorized30-day owner-only trial;2/24h,6/7d,30 total; critical reserve; no migration-ledger reset' if readjson('/etc/optibrain/operational-notifications.json',{}).get('enabled') else 'DISABLED'),'No history pruning, database checkpoint or business replay performed.']
 text+=['Business storage / generation: '+json.dumps(s.get('business_storage',{'state':'UNKNOWN'}))]
 if period=='weekly':
  ops=readjson('/var/lib/optibrain/autonomous-operations/operations-status.json',{})
  caps=readjson('/var/lib/optibrain/autonomous-operations/capabilities-current.json',{})
  business=readjson('/var/lib/optibrain/autonomous-operations/business-observer-status.json',{})
  retired=readjson('/var/lib/optibrain/autonomous-operations/retirement-A-complete.json',{})
  ledger=Path('/var/lib/optibrain/autonomous-operations/notifications/ledger.jsonl');notices=[json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
  text+=['Completed improvement: approved expanded recovery retirement bytes='+str(retired.get('allocated_bytes_reclaimed',0)), 'Operational repairs this cycle='+str(sum(r.get('verified',False) for r in ops.get('repairs',[]))), 'Current provider capability states='+json.dumps({k:v['classification'] for k,v in caps.get('results',{}).items()}), 'Native business observation='+str(business.get('classification','UNKNOWN'))+'; writes0; partial source timestamps retained', 'Owner trial intents='+str(sum(r['event']=='INTENT' for r in notices))+'; independently received deliveries='+str(sum(r['event']=='DELIVERED' for r in notices)), 'Recurring issues='+json.dumps(ops.get('alerts',[])), 'Learning quality: unproven; operational/native source-linked outcomes instrumented, no paid AI generation or rule promotion', 'Priorities: practical working headroom68GiB; provider consent/API prerequisites; observe cold-cache convergence under160GET/hour and2000/day (400 fallback); preserve DLQ and every unique audit record']
  text+=['Database bytes/WAL: '+json.dumps(s['databases']),'Weekly actions: compare seven-day growth, backup/restore proof, WAL, feedback/evaluation coverage; preserve unknowns.','Details: /var/lib/optibrain/resource-management; master owner report /home/optibrain/optibrain-resource-learning-optimization-20261112.txt']
 (ROOT/(period+'-summary.txt')).write_text('\n'.join(text)+'\n')
 view=Path('/var/lib/optibrain-resource-view')/(period+'-summary.txt')
 view.write_text('\n'.join(text)+'\n');shutil.chown(view,user='root',group='optibrain');view.chmod(0o640)
 (ROOT/(period+'-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')+'.txt')).write_text('\n'.join(text)+'\n')

def restore():
 if shutil.disk_usage('/').free<25*G:raise RuntimeError('optional restore deferred: emergency reserve')
 mem=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
 if mem<6*G:raise RuntimeError('optional restore deferred: RAM reserve')
 a=sorted(Path('/var/backups/optibrain').glob('optibrain-backup-*.tar.gz'))[-1];expected=a.with_name(a.name+'.sha256').read_text().split()[0]
 p=Path('/usr/local/lib/optibrain-backup/optibrain-restore-drill.py');spec=importlib.util.spec_from_file_location('drill',p);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 workspace=ROOT/'isolated-scratch';workspace.mkdir(mode=0o700,exist_ok=True);start=time.monotonic()
 result=mod.validate(a,expected,workspace);result.update(at=now(),seconds=time.monotonic()-start,offline_decryption='NOT_PERFORMED')
 append(ROOT/'restore-history.jsonl',result);atomic(ROOT/'restore-latest.json',result);return result

def learning():
 result={'at':now(),'promotion':'EXISTING_OWNER_APPROVAL_REQUIRED','archive_retrieval':'R2 recovery archives are not indexed knowledge; no raw history evicted','databases':[]}
 for p in DBS:
  if not p.exists():continue
  with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=2) as c:
   c.execute('PRAGMA query_only=ON');tables=[]
   for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    if any(k in name for k in ['learn','feedback','decision','memory','evaluation','receipt']):
     q='"'+name.replace('"','""')+'"';tables.append({'table':name,'rows':c.execute('SELECT count(*) FROM '+q).fetchone()[0]})
   start=time.monotonic();c.set_progress_handler(lambda:int(time.monotonic()-start>15),10000)
   try:integrity='ok' if c.execute('PRAGMA quick_check').fetchall()==[('ok',)] else 'FAILED'
   except sqlite3.Error:integrity='UNKNOWN_TIMEOUT_OR_BUSY'
   result['databases'].append({'name':p.name,'tables':tables,'quick_check':integrity})
 result['quality']='UNKNOWN until labelled outcomes and evaluations exist; counts are coverage only'
 atomic(ROOT/'learning-health.json',result);append(ROOT/'learning-history.jsonl',result);return result

def main():
 os.umask(0o077);ROOT.mkdir(mode=0o700,exist_ok=True)
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['sample','daily','weekly','restore','learning']);a=p.parse_args()
 with (ROOT/('verification.lock' if a.mode=='restore' else 'monitor.lock')).open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  if a.mode in ['sample','daily','weekly']:
   s=sample()
   if a.mode in ['daily','weekly']:learning();render(s,a.mode)
   print(json.dumps({'at':s['at'],'alerts':s['alerts'],'available':s['available']}))
  else:print(json.dumps(restore() if a.mode=='restore' else learning(),sort_keys=True))
if __name__=='__main__':main()
