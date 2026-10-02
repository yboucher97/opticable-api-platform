#!/usr/bin/python3
"""Installed root launcher: verify the immutable release before importing it."""
import hashlib,json,os,re,stat,subprocess,sys
from pathlib import Path

POLICY=Path('/etc/optibrain/lifecycle-runtime.json')

def trusted(path):
    for p in (*path.parents,):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Untrusted runtime parent')
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1 or s.st_mode&0o022:raise ValueError('Untrusted runtime file')
    return path.read_bytes()

def verify(value):
    if not re.fullmatch('[0-9a-f]{40}',value.get('sha','')):raise ValueError('Exact release SHA required')
    root=Path('/opt/optibrain-releases')/value['sha']/'source'
    if str(root)!=value.get('source_root'):raise ValueError('Fixed release directory required')
    for name,expected in value['files'].items():
        if name.startswith('/') or '..' in Path(name).parts:raise ValueError('Invalid pinned source path')
        if hashlib.sha256(trusted(root/name)).hexdigest()!=expected:raise ValueError('Pinned root source changed')
    actual={str(p.relative_to(root)) for p in root.rglob('*.py')}
    if actual!={n for n in value['files'] if n.endswith('.py')}:raise ValueError('Unpinned Python source')
    python=Path('/opt/optibrain-releases')/value['sha']/'venv/bin/python'
    for name in ('pyvenv.cfg','bin','lib'):
        s=(python.parents[1]/name).stat()
        if s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Untrusted release venv')
    if Path(sys.executable).absolute()!=python.absolute():
        trusted(Path(__file__).absolute())
        os.execv(str(python),[str(python),'-I','-B',str(Path(__file__).absolute()),*sys.argv[1:]])
    return root

def main():
    if os.geteuid()!=0:raise ValueError('Root required')
    if sys.argv[1:]==['--stop']:
        path=Path('/etc/optibrain/mutation-control.json')
        trusted(path)
        content={'schema':1,'test_writes_enabled':False,'allowed_actions':['crm.task.create'],'real_canary_allowed':False}
        temp=path.with_suffix('.stop.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
        with os.fdopen(fd,'w') as f:json.dump(content,f);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        subprocess.run(['/usr/bin/systemctl','disable','--now','opticable-lifecycle-internal.timer'],check=True,stdout=subprocess.DEVNULL)
        print('Internal lifecycle scopes OFF; canary FALSE');return
    if sys.argv[1:] not in (['--once'],['--dry-run']):raise ValueError('Use --once, --dry-run or --stop')
    policy=json.loads(trusted(POLICY));root=verify(policy)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(root/'apps/workflow-api'))
    from workflow.automation.real_internal import run
    result=run(dry_run=sys.argv[1]=='--dry-run')
    print(json.dumps({k:result[k] for k in ('state','eligible_leads','effects_this_cycle','provider_reads')},sort_keys=True))

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Internal lifecycle stopped: '+type(exc).__name__)
