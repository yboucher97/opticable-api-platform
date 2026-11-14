"""One-time trusted private-runtime installation/rollback; no application deploy.

Root administration only, fixed NEW host paths, exact clean source commit. This
does not create or activate a standing cleanup approval. Rollback preserves all
data and pauses the optional drafting hook pending a corrected guarded runtime.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import tarfile
import time

RUNTIME = Path('/usr/local/share/optibrain-business-autopilot-v1')
MONITOR = Path('/usr/local/lib/optibrain/resource_manager.py')
POLICY = Path('/etc/optibrain/business-storage-policy.json')
OUTPUT = Path('/var/lib/opticable-workflow-api/output/automation/business-autopilot')
HOOK = Path('/etc/systemd/system/optibrain-platform-intelligence.service.d/business-artifacts.conf')
ACCOUNT = 'opticable-workflow-api'
PYTHON = '/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python'


def digest(p): return sha256(Path(p).read_bytes()).hexdigest()
def git(source, *args): return subprocess.check_output(['git','-c','safe.directory='+str(source),'-C',str(source),*args],text=True).strip()
def atomic(path, raw, mode=0o644):
    path=Path(path); tmp=path.with_name('.storage-staged-'+path.name)
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.chown(tmp,0,0);os.chmod(tmp,mode);os.replace(tmp,path)
def save(path, value):
    with Path(path).open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    Path(path).chmod(0o600)


def review_pid():
    found=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            args=(p/'cmdline').read_bytes().split(b'\0')
            if os.fsencode(str(RUNTIME/'private_preview.py')) in args and b'owner-review' in args:found.append(int(p.name))
        except (FileNotFoundError,ProcessLookupError):pass
    if len(found)!=1:raise ValueError('One exact existing private review process required')
    return found[0]


def launch_review():
    account=pwd.getpwnam(ACCOUNT)
    def demote():
        os.setgroups([]);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
        if ctypes.CDLL(None).prctl(38,1,0,0,0)!=0:raise PermissionError('NoNewPrivs required')
    fd=os.open(OUTPUT/'owner-review.log',os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
    try:
        return subprocess.Popen([PYTHON,'-I','-B',str(RUNTIME/'private_preview.py'),'owner-review',
            str(OUTPUT/'website-preview'),str(OUTPUT/'owner-review-access.json'),str(OUTPUT.parent/'phase12-autonomy.db'),str(OUTPUT/'artifacts')],
            cwd=OUTPUT,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','TZ':'America/Toronto'},stdin=subprocess.DEVNULL,
            stdout=fd,stderr=fd,preexec_fn=demote,start_new_session=True)
    finally:os.close(fd)


def stop_review(pid):
    args=Path('/proc',str(pid),'cmdline').read_bytes().split(b'\0')
    if os.fsencode(str(RUNTIME/'private_preview.py')) not in args or b'owner-review' not in args:
        raise ValueError('Private review process identity changed')
    os.kill(pid,signal.SIGTERM)
    for _ in range(40):
        if not Path('/proc',str(pid)).exists():return
        time.sleep(.05)
    raise RuntimeError('Private review did not exit')


def restore(ledger, runtime=RUNTIME, monitor=MONITOR, policy=POLICY):
    ledger=Path(ledger); checkpoint=json.loads((ledger/'checkpoint.json').read_text())
    archive=ledger/'pre-storage-runtime.tar.gz'
    if digest(archive)!=checkpoint['archive_sha256']:raise ValueError('Recovery archive identity changed')
    with tarfile.open(archive) as t:
        expected={'runtime/'+n for n in checkpoint['runtime']}|{'resource_manager.py','business-artifacts.conf'}
        if set(t.getnames())!=expected:raise ValueError('Exact recovery members required')
        for name,h in checkpoint['runtime'].items():
            member=t.getmember('runtime/'+name)
            if not member.isfile() or Path(name).name!=name:raise ValueError('Invalid recovery member')
            raw=t.extractfile(member).read()
            if sha256(raw).hexdigest()!=h:raise ValueError('Recovery member hash mismatch')
            atomic(Path(runtime)/name,raw)
        atomic(monitor,t.extractfile('resource_manager.py').read(),0o755)
        # Keep the bounded policy as inert recovery evidence. No registry,
        # disposable artifact, journal, backup or owner credential is restored.
    for name in ('storage.py','lifecycle.py'):
        p=Path(runtime)/name
        if name not in checkpoint['runtime'] and p.exists():p.unlink()
    assert all(digest(Path(runtime)/name)==h for name,h in checkpoint['runtime'].items())
    assert digest(monitor)==checkpoint['monitor_sha256']
    return checkpoint


def main():
    p=argparse.ArgumentParser();p.add_argument('--ledger',required=True);p.add_argument('--source');p.add_argument('--commit');p.add_argument('--rollback',action='store_true');a=p.parse_args()
    if os.geteuid()!=0 or os.uname().nodename!='vps-f8e9b20e':raise PermissionError('Trusted NEW host administration required')
    ledger=Path(a.ledger)
    if ledger.parent!=Path('/var/lib/optibrain') or not ledger.name.startswith('storage-budget-'):raise ValueError('Exact storage evidence family required')
    if Path('/etc/optibrain/business-storage-approval.json').exists():raise ValueError('Cleanup approval must remain absent during installation/rollback')
    with (OUTPUT/'execution.lock').open('r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.rollback:
            installed=json.loads((ledger/'installed.json').read_text())
            if any(digest(p)!=h for p,h in installed['installed_hashes'].items()):raise ValueError('Newer runtime requires reviewed forward recovery')
            pid=review_pid();stop_review(pid);restore(ledger)
            atomic(HOOK,b'# Storage rollback: native observations continue; optional drafts held.\n[Service]\nExecStartPost=\n')
            subprocess.run(['systemctl','daemon-reload'],check=True)
            process=launch_review();save(ledger/'rollback.json',{'at':datetime.now(timezone.utc).isoformat(),'review_pid':process.pid,'optional_drafting':'HELD','database_restored':False})
            return
        source=Path(a.source)
        if git(source,'rev-parse','HEAD')!=a.commit or git(source,'status','--porcelain'):raise ValueError('Exact clean tested source required')
        if POLICY.exists():raise ValueError('Existing policy requires a separate reviewed update')
        # Syntax and trusted manifest verified before creating a checkpoint.
        import importlib.util
        spec=importlib.util.spec_from_file_location('installed_guard',RUNTIME/'runner.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
        old=guard.verify_runtime(RUNTIME)
        if len(old)!=11:raise ValueError('Exact V1.2 runtime baseline required')
        ledger.mkdir(mode=0o700)
        archive=ledger/'pre-storage-runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as t:
            for file in sorted(RUNTIME.iterdir()):t.add(file,arcname='runtime/'+file.name,recursive=False)
            t.add(MONITOR,arcname='resource_manager.py',recursive=False);t.add(HOOK,arcname='business-artifacts.conf',recursive=False)
        archive.chmod(0o600)
        checkpoint={'at':datetime.now(timezone.utc).isoformat(),'runtime':{p.name:digest(p) for p in RUNTIME.iterdir()},
            'monitor_sha256':digest(MONITOR),'hook_sha256':digest(HOOK),'archive_sha256':digest(archive),
            'owner_credentials_sha256':digest(OUTPUT/'owner-review-access.json'),'source_commit':a.commit}
        save(ledger/'checkpoint.json',checkpoint)
        process=None; stopped=False; oldpid=review_pid()
        try:
            for name in ('runner.py','review.py','storage.py','lifecycle.py'):
                raw=(source/'ops/business_autopilot'/name).read_bytes()
                committed=subprocess.check_output(['git','-c','safe.directory='+str(source),'-C',str(source),'show',a.commit+':ops/business_autopilot/'+name])
                if raw!=committed:raise ValueError('Source file differs from commit')
                atomic(RUNTIME/name,raw)
            atomic(MONITOR,(source/'ops/business_autopilot/resource_manager.py').read_bytes(),0o755)
            manifest={p.name:digest(p) for p in RUNTIME.iterdir() if p.name!='manifest.json'}
            atomic(RUNTIME/'manifest.json',(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
            spec=importlib.util.spec_from_file_location('storage_policy_source',source/'ops/business_autopilot/storage.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            atomic(POLICY,(json.dumps(module.POLICY,sort_keys=True,indent=2)+'\n').encode())
            spec=importlib.util.spec_from_file_location('new_guard',RUNTIME/'runner.py');new=importlib.util.module_from_spec(spec);spec.loader.exec_module(new);new.verify_runtime(RUNTIME)
            assert len(manifest)==13 and digest(HOOK)==checkpoint['hook_sha256']
            assert digest(OUTPUT/'owner-review-access.json')==checkpoint['owner_credentials_sha256']
            stop_review(oldpid);stopped=True;process=launch_review();time.sleep(.4)
            if process.poll() is not None:raise RuntimeError('Private review failed')
            paths=[RUNTIME/n for n in manifest]+[RUNTIME/'manifest.json',MONITOR,POLICY]
            save(ledger/'installed.json',{'at':datetime.now(timezone.utc).isoformat(),'source_commit':a.commit,
                'installed_hashes':{str(p):digest(p) for p in paths},'review_pid':process.pid,
                'new_database':False,'new_scheduler':False,'production_application_deployed':False,
                'cleanup_approval_present':False,'quarantine_enabled':False,'permanent_deletion_enabled':False})
        except Exception:
            if process and process.poll() is None:stop_review(process.pid)
            restore(ledger)
            atomic(HOOK,b'# Storage installation failure: optional drafts held.\n[Service]\nExecStartPost=\n')
            subprocess.run(['systemctl','daemon-reload'],check=True)
            if stopped:launch_review()
            raise
    print(json.dumps({'installed':'PASS','ledger':str(ledger),'runtime_files':13,'quarantine_enabled':False,'permanent_deletion_enabled':False}))


if __name__=='__main__':main()
