#!/usr/bin/env python3
"""Root-installed manual release gate; never execute checkout scripts as root.

A root-reviewed exact-SHA authorization and successful exact-head CI are needed
for a new release. A repeated current release is only an integrity/health check.
No approval or business authority is created by deployment.
"""
import ast,fcntl,hashlib,json,os,re,shutil,stat,subprocess,sys,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path

PROD=Path('/opt/opticable-api-platform')
ROOT=Path('/var/lib/optibrain/phase13-remediation')
AUTH=Path('/etc/optibrain/manual-release-authorization.json')
MANIFEST=Path('/etc/optibrain/phase7-canary-registration.json')
ENV=Path('/etc/opticable-workflow-api.env')
REPO='yboucher97/opticable-api-platform'
SAFE={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0'}
GIT=['/usr/bin/git','-c','safe.directory='+str(PROD),'-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(PROD)]

def require(value,reason):
    if not value:raise RuntimeError(reason)
def run(*args,timeout=120):return subprocess.check_output(args,env=SAFE,stdin=subprocess.DEVNULL,text=True,timeout=timeout).strip()
def read_private(path):
    for parent in list(path.parents)[:-1]:
        s=parent.lstat();require(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,'untrusted_policy_parent')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        s=os.fstat(stream.fileno());require(stat.S_ISREG(s.st_mode) and s.st_uid==0 and s.st_nlink==1 and not s.st_mode&0o077,'untrusted_authorization')
        return json.load(stream)
def atomic(path,content,mode=0o600):
    tmp=path.with_name('.'+path.name+'.release.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'w') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
    os.chmod(tmp,mode);os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def validate_ci(ci,target):
    require(ci.get('head_sha')==target and ci.get('conclusion')=='success'
            and ci.get('name')=='Validate API Platform' and ci.get('repository',{}).get('full_name')==REPO
            and ci.get('head_branch')=='main' and ci.get('event') in {'push','workflow_dispatch'},'exact_ci_missing')
def health(expected_version=None):
    for _ in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=3) as r:
                body=json.load(r)
                if r.status==200 and body.get('status')=='ok' and (expected_version is None or body.get('version')==expected_version):return True
        except Exception:pass
        time.sleep(1)
    return False
def pin_manifest(target,base):
    code=(PROD/'apps/workflow-api/workflow/phase7_registration.py').read_text()
    tree=ast.parse(code)
    sources=next(ast.literal_eval(n.value.args[0]) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_PINNED_SOURCES' for t in n.targets))
    base['candidate_sha']=target;base['business_actions_enabled']=False;base['api_version']=candidate_version()
    for k in ('create_approval_id','create_request_hash','crm_approval_id','outbound_approval_id'):base[k]=None
    base['source_hashes']={p:hashlib.sha256((PROD/'apps/workflow-api'/p).read_bytes()).hexdigest() for p in sources}
    atomic(MANIFEST,json.dumps(base,indent=2)+'\n',0o644)
    text=ENV.read_text();text=re.sub(r'^OPTIBRAIN_PHASE7_RELEASE_SHA=.*$', 'OPTIBRAIN_PHASE7_RELEASE_SHA='+target,text,flags=re.M)
    atomic(ENV,text)

def candidate_version():
    tree=ast.parse((PROD/'apps/workflow-api/workflow/api.py').read_text())
    value=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='API_VERSION' for t in n.targets))
    require(isinstance(value,str) and re.fullmatch(r'\d+\.\d+\.\d+',value),'invalid_api_version')
    return value

def runtime_receipt(target,previous,auth,*,db_root=Path('/var/lib/opticable-workflow-api/output/automation')):
    import sqlite3
    services={name:run('/usr/bin/systemctl','is-active',name+'.service') for name in
              ('opticable-workflow-api','opticable-password-pdf','opticable-omada-site','caddy')}
    require(all(value=='active' for value in services.values()),'service_health_regression')
    timers={name:run('/usr/bin/systemctl','is-active',name+'.timer') for name in
            ('optibrain-backup','optibrain-phase2a-upload','opticable-phase9-intake-receipts',
             'opticable-phase10-service-events','opticable-phase12-test-runner')}
    require(all(value=='active' for value in timers.values()),'timer_health_regression')
    schemas={}
    for name in ('automation.db','phase9-form-receipts.db','phase9-intake.db','phase10-service-events.db','phase12-autonomy.db'):
        path=db_root/name
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','database_integrity_regression')
            schemas[name]=db.execute('PRAGMA user_version').fetchone()[0]
    return {'schema':1,'type':'optibrain.release','state':'deployed','sha':target,'api_version':candidate_version(),
            'baseline':previous,'ci_run_id':auth['ci_run_id'],'tests':auth.get('validation',{}),
            'migration_state':{'active_databases':5,'user_versions':schemas,'strategy':'additive rebuildable caches; no journal migration'},
            'service_health':services,'timer_health':timers,
            'safety_flags':{'automatic_writes':False,'real_canary_allowed':False,'test_writes_enabled':False,'development_worker':False},
            'writers_enabled':False,'rollback':{'sha':previous,'backup_archive':auth['backup_archive'],'backup_sha256':auth['backup_sha256']},
            'technical_provider_calls':{'github':{'reads':1,'writes':0}},'at':datetime.now(timezone.utc).isoformat()}

def verify_closed():
    control=json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
    require(control['test_writes_enabled'] is False and control['real_canary_allowed'] is False,'writers_enabled')
    require(not control.get('lifecycle',{}).get('enabled') and not control.get('lifecycle',{}).get('real_scopes'), 'scoped_lifecycle_writers_enabled')
    for p in [ENV,Path('/etc/optibrain/phase12-runner.env')]:
        vals=dict(x.split('=',1) for x in p.read_text().splitlines() if '=' in x and not x.startswith('#'))
        require(vals.get('OPTIBRAIN_BUSINESS_AUTO_WRITES','0')=='0','automatic_writes_enabled')
    require(not Path('/etc/optibrain/authorize-persistent-codex-development').exists(),'development_worker_authorized')
def main(target):
    require(os.geteuid()==0 and re.fullmatch('[0-9a-f]{40}',target),'root_and_exact_sha_required')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=os.open('/var/lock/opticable-api-platform-deploy.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    verify_closed();previous=run(*GIT,'rev-parse','HEAD')
    manifest=json.loads(MANIFEST.read_text())
    if target==previous:
        require(manifest['candidate_sha']==target,'deployed_manifest_drift')
        for p,h in manifest['source_hashes'].items():require(hashlib.sha256((PROD/'apps/workflow-api'/p).read_bytes()).hexdigest()==h,'deployed_source_drift')
        require(health(),'current_release_unhealthy');print(json.dumps({'state':'verified_current','sha':target}));return
    auth=read_private(AUTH);now=datetime.now(timezone.utc)
    require(auth.get('candidate_sha')==target and auth.get('baseline_sha')==previous and now<datetime.fromisoformat(auth['expires_at']),'release_authorization_mismatch_or_expired')
    require(auth.get('tests_passed') is True and auth.get('failures')==auth.get('errors')==auth.get('skipped')==0,'validation_failed')
    validation=auth.get('validation',{})
    require(validation.get('passed') is True and validation.get('blocked_network_attempts')==0
            and validation.get('failures')==validation.get('errors')==validation.get('skipped')==0
            and validation.get('tests',0)>=811,'complete_release_regression_missing')
    with urllib.request.urlopen('https://api.github.com/repos/'+REPO+'/actions/runs/'+str(int(auth['ci_run_id'])),timeout=20) as r:ci=json.load(r)
    validate_ci(ci,target)
    remote='https://github.com/'+REPO+'.git'
    require(run('/usr/bin/git','ls-remote',remote,'refs/heads/main')==target+'\trefs/heads/main','remote_main_differs')
    run(*GIT,'fetch','--no-tags',remote,'refs/heads/main',timeout=180)
    require(run(*GIT,'rev-parse','FETCH_HEAD')==target,'fetched_sha_differs')
    run(*GIT,'merge-base','--is-ancestor',previous,target)
    require(not run(*GIT,'diff','--name-only') and not run(*GIT,'diff','--cached','--name-only'),'production_changes_present')
    venv=Path('/opt/optibrain-releases')/target/'venv'
    require(venv.is_dir() and (venv/'bin/python').exists(),'validated_environment_absent')
    for p in [venv,*venv.rglob('*')]:
        s=p.lstat();require(s.st_uid==0 and (p.is_symlink() or not s.st_mode&0o022),'untrusted_release_environment')
    archive=Path(auth['backup_archive']);require(archive.parent==Path('/var/backups/optibrain') and archive.is_file(),'rollback_backup_absent')
    require(sha(archive)==auth['backup_sha256'],'rollback_backup_changed')
    live=PROD/'apps/workflow-api/.venv';old_venv=str(live.resolve())
    if not live.is_symlink():
        preserved=PROD/'apps/workflow-api/.venv.phase13-baseline';require(not preserved.exists(),'baseline_environment_already_preserved')
        live.rename(preserved);old_venv=str(preserved)
    old_manifest=MANIFEST.read_text();old_env=ENV.read_text()
    old_receipt=json.loads((ROOT/'deployment.json').read_text())
    try:
        run(*GIT,'reset','--hard',target)
        pin_manifest(target,manifest)
        if live.is_symlink():live.unlink()
        live.symlink_to(venv,target_is_directory=True)
        run('/usr/bin/systemctl','restart','opticable-workflow-api.service')
        require(health(candidate_version()),'candidate_health_failed');verify_closed()
        require(run(*GIT,'rev-parse','HEAD')==target,'deployed_sha_changed')
        receipt=runtime_receipt(target,previous,auth)
        releases=Path('/var/lib/optibrain/releases');releases.mkdir(mode=0o700,exist_ok=True)
        atomic(releases/(target+'.json'),json.dumps(receipt,indent=2)+'\n')
        atomic(releases/'current.json',json.dumps(receipt,indent=2)+'\n')
        atomic(ROOT/'deployment.json',json.dumps(receipt,indent=2)+'\n')
        print(json.dumps({'state':'deployed','sha':target,'baseline':previous,'ci_run_id':auth['ci_run_id']}))
    except Exception:
        run(*GIT,'reset','--hard',previous)
        atomic(MANIFEST,old_manifest,0o644);atomic(ENV,old_env)
        if live.is_symlink():live.unlink()
        live.symlink_to(old_venv,target_is_directory=True)
        run('/usr/bin/systemctl','restart','opticable-workflow-api.service')
        require(health(),'rollback_failed')
        rolled_back={**old_receipt,'schema':1,'type':'optibrain.release','state':'rolled_back','failed_candidate':target,
                     'sha':previous,'writers_enabled':False,'at':datetime.now(timezone.utc).isoformat()}
        releases=Path('/var/lib/optibrain/releases');releases.mkdir(mode=0o700,exist_ok=True)
        atomic(releases/'current.json',json.dumps(rolled_back,indent=2)+'\n')
        atomic(ROOT/'deployment.json',json.dumps(rolled_back,indent=2)+'\n')
        candidate_receipt=releases/(target+'.json')
        if candidate_receipt.exists():
            failed=json.loads(candidate_receipt.read_text());failed.update(state='rolled_back',rollback_at=rolled_back['at'])
            atomic(candidate_receipt,json.dumps(failed,indent=2)+'\n')
        raise RuntimeError('candidate_failed_rolled_back')

if __name__=='__main__':
    try:
        require(len(sys.argv)==2,'one_exact_sha_argument_required');main(sys.argv[1])
    except Exception as exc:
        print('Guarded release refused: '+(str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__),file=sys.stderr);sys.exit(1)
