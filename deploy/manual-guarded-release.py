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
def health():
    for _ in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=3) as r:
                if r.status==200 and json.load(r).get('status')=='ok':return True
        except Exception:pass
        time.sleep(1)
    return False
def pin_manifest(target,base):
    code=(PROD/'apps/workflow-api/workflow/phase7_registration.py').read_text()
    tree=ast.parse(code)
    sources=next(ast.literal_eval(n.value.args[0]) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_PINNED_SOURCES' for t in n.targets))
    base['candidate_sha']=target;base['business_actions_enabled']=False
    for k in ('create_approval_id','create_request_hash','crm_approval_id','outbound_approval_id'):base[k]=None
    base['source_hashes']={p:hashlib.sha256((PROD/'apps/workflow-api'/p).read_bytes()).hexdigest() for p in sources}
    atomic(MANIFEST,json.dumps(base,indent=2)+'\n',0o644)
    text=ENV.read_text();text=re.sub(r'^OPTIBRAIN_PHASE7_RELEASE_SHA=.*$', 'OPTIBRAIN_PHASE7_RELEASE_SHA='+target,text,flags=re.M)
    atomic(ENV,text)
def verify_closed():
    control=json.loads(Path('/etc/optibrain/mutation-control.json').read_text())
    require(control['test_writes_enabled'] is False and control['real_canary_allowed'] is False,'writers_enabled')
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
    with urllib.request.urlopen('https://api.github.com/repos/'+REPO+'/actions/runs/'+str(int(auth['ci_run_id'])),timeout=20) as r:ci=json.load(r)
    require(ci['head_sha']==target and ci['conclusion']=='success' and ci['name']=='Validate API Platform','exact_ci_missing')
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
    require(hashlib.sha256(archive.read_bytes()).hexdigest()==auth['backup_sha256'],'rollback_backup_changed')
    live=PROD/'apps/workflow-api/.venv';old_venv=str(live.resolve())
    if not live.is_symlink():
        preserved=PROD/'apps/workflow-api/.venv.phase13-baseline';require(not preserved.exists(),'baseline_environment_already_preserved')
        live.rename(preserved);old_venv=str(preserved)
    old_manifest=MANIFEST.read_text();old_env=ENV.read_text()
    try:
        run(*GIT,'reset','--hard',target)
        pin_manifest(target,manifest)
        if live.is_symlink():live.unlink()
        live.symlink_to(venv,target_is_directory=True)
        run('/usr/bin/systemctl','restart','opticable-workflow-api.service')
        require(health(),'candidate_health_failed');verify_closed()
        require(run(*GIT,'rev-parse','HEAD')==target,'deployed_sha_changed')
        atomic(ROOT/'deployment.json',json.dumps({'state':'deployed','sha':target,'baseline':previous,'ci_run_id':auth['ci_run_id'],'writers_enabled':False,'at':now.isoformat()}))
        print(json.dumps({'state':'deployed','sha':target,'baseline':previous,'ci_run_id':auth['ci_run_id']}))
    except Exception:
        run(*GIT,'reset','--hard',previous)
        atomic(MANIFEST,old_manifest,0o644);atomic(ENV,old_env)
        if live.is_symlink():live.unlink()
        live.symlink_to(old_venv,target_is_directory=True)
        run('/usr/bin/systemctl','restart','opticable-workflow-api.service')
        require(health(),'rollback_failed')
        atomic(ROOT/'deployment.json',json.dumps({'state':'rolled_back','failed_candidate':target,'sha':previous,'writers_enabled':False}))
        raise RuntimeError('candidate_failed_rolled_back')

if __name__=='__main__':
    try:
        require(len(sys.argv)==2,'one_exact_sha_argument_required');main(sys.argv[1])
    except Exception as exc:
        print('Guarded release refused: '+(str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__),file=sys.stderr);sys.exit(1)
