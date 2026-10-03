#!/usr/bin/python3
"""Installed root launcher: separate external-send kill and pinned release."""
import hashlib,json,os,re,stat,subprocess,sys
from pathlib import Path

POLICY=Path('/etc/optibrain/customer-communications-runtime.json')

def trusted(path):
    for p in path.parents:
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Untrusted customer runtime parent')
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1 or s.st_mode&0o022:raise ValueError('Untrusted customer runtime file')
    return path.read_bytes()

def verify(value):
    if not re.fullmatch('[0-9a-f]{40}',value.get('sha','')):raise ValueError('Exact customer release required')
    root=Path('/opt/optibrain-releases')/value['sha']/'source'
    if str(root)!=value.get('source_root'):raise ValueError('Fixed customer release directory required')
    for name,expected in value['files'].items():
        if name.startswith('/') or '..' in Path(name).parts:raise ValueError('Invalid customer pinned path')
        if hashlib.sha256(trusted(root/name)).hexdigest()!=expected:raise ValueError('Pinned customer source changed')
    if {str(p.relative_to(root)) for p in root.rglob('*.py')}!={n for n in value['files'] if n.endswith('.py')}:
        raise ValueError('Unpinned customer Python source')
    python=Path('/opt/optibrain-releases')/value['sha']/'venv/bin/python'
    for name in ['pyvenv.cfg','bin','lib']:
        s=(python.parents[1]/name).stat()
        if s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Untrusted customer venv')
    if Path(sys.executable).absolute()!=python.absolute():
        trusted(Path(__file__).absolute())
        os.execv(str(python),[str(python),'-I','-B',str(Path(__file__).absolute()),*sys.argv[1:]])
    return root

def main():
    if os.geteuid()!=0:raise ValueError('Root customer runner required')
    if sys.argv[1:]==['--stop']:
        p=Path('/etc/optibrain/customer-communication-control.json')
        value=json.loads(trusted(p));value['external_enabled']=False;value['test_enabled']=False
        temp=p.with_suffix('.stop.tmp');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
        os.replace(temp,p)
        subprocess.run(['/usr/bin/systemctl','disable','--now','opticable-customer-communications.timer'],check=True,stdout=subprocess.DEVNULL)
        print('All automatic external customer sends OFF; internal lifecycle unchanged');return
    if sys.argv[1:] not in (['--once'],['--dry-run']):raise ValueError('Use --once/--dry-run/--stop')
    root=verify(json.loads(trusted(POLICY)));sys.dont_write_bytecode=True
    sys.path.insert(0,str(root/'apps/workflow-api'));sys.path.insert(0,str(root/'ops/phase16_17'))
    from inventory import clients
    from workflow.automation.customer_runtime import run
    _,client,_=clients(root)
    result=run(client,dry_run=sys.argv[1]=='--dry-run')
    print(json.dumps({k:result[k] for k in ['state','sends_this_cycle','provider_reads']},sort_keys=True))

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Customer communications stopped: '+type(exc).__name__)
