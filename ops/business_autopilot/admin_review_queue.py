"""Trusted private-dashboard upgrade/rollback. Never changes permissions or data."""
import argparse
import base64
from datetime import datetime,timezone
import fcntl
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import urllib.request

RUNTIME=Path('/usr/local/share/optibrain-business-autopilot-v1')
OUTPUT=Path('/var/lib/opticable-workflow-api/output/automation/business-autopilot')
MODULES=('review.py','private_preview.py','runner.py','manifest.json')


def sha(p):return sha256(Path(p).read_bytes()).hexdigest()


def admin():
    spec=importlib.util.spec_from_file_location('existing_private_admin',Path(__file__).with_name('admin_storage.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def restore(ledger,runtime=RUNTIME):
    ledger=Path(ledger);runtime=Path(runtime);checkpoint=json.loads((ledger/'checkpoint.json').read_text())
    archive=ledger/'pre-queue-runtime.tar.gz'
    if sha(archive)!=checkpoint['archive_sha256']:raise ValueError('Recovery archive identity changed')
    helper=admin()
    with tarfile.open(archive) as tar:
        if set(tar.getnames())!=set(MODULES):raise ValueError('Exact private-runtime recovery members required')
        for name in MODULES:
            member=tar.getmember(name)
            if not member.isfile():raise ValueError('Regular recovery member required')
            raw=tar.extractfile(member).read()
            if sha256(raw).hexdigest()!=checkpoint['before'][name]:raise ValueError('Recovery member hash changed')
            helper.atomic(runtime/name,raw)
    assert all(sha(runtime/name)==h for name,h in checkpoint['before'].items())


def health():
    credentials=json.loads((OUTPUT/'owner-review-access.json').read_text())
    headers={'Authorization':'Basic '+base64.b64encode((credentials['username']+':'+credentials['password']).encode()).decode()}
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8876/review/queue.json',headers=headers),timeout=15) as response:
        data=json.load(response);assert response.status==200
    assert data['registered_items']==91 and sum(p['member_count'] for p in data['packages'])==91
    assert len(data['default_packages'])<=10 and len(data['top_decisions'])<=5
    return {'registered_items':data['registered_items'],'packages':data['package_count'],'default_packages':len(data['default_packages'])}


def self_test():
    assert os.geteuid()==0
    with tempfile.TemporaryDirectory(prefix='queue-rollback-synthetic-') as directory:
        root=Path(directory);runtime=root/'runtime';runtime.mkdir();ledger=root/'evidence';ledger.mkdir()
        for name in MODULES:(runtime/name).write_bytes(('original-'+name).encode())
        before={name:sha(runtime/name) for name in MODULES};archive=ledger/'pre-queue-runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name in MODULES:tar.add(runtime/name,arcname=name,recursive=False)
        (ledger/'checkpoint.json').write_text(json.dumps({'archive_sha256':sha(archive),'before':before}))
        for name in MODULES:(runtime/name).write_bytes(b'new-version')
        marker=root/'newer-business-data';marker.write_bytes(b'preserve')
        restore(ledger,runtime);assert marker.read_bytes()==b'preserve'
    print(json.dumps({'actual_isolated_queue_rollback':'PASS','business_data_preserved':True,'production_rollback':False}))


def main():
    global MODULES
    p=argparse.ArgumentParser();p.add_argument('--source');p.add_argument('--commit');p.add_argument('--ledger');p.add_argument('--rollback',action='store_true');p.add_argument('--self-test',action='store_true');p.add_argument('--business-v13',action='store_true');a=p.parse_args()
    expected_ledger='/var/lib/optibrain/review-queue-20261114'
    if a.business_v13:
        MODULES=('review.py','runner.py','business_work.py','business_sources.py','engine.py','manifest.json')
        expected_ledger='/var/lib/optibrain/business-execution-v13-20261114'
    if a.self_test:return self_test()
    if os.geteuid()!=0 or os.uname().nodename!='vps-f8e9b20e':raise PermissionError('Trusted NEW host administration required')
    helper=admin();ledger=Path(a.ledger)
    if ledger!=Path(expected_ledger):raise ValueError('Exact queue evidence path required')
    if Path('/etc/optibrain/business-storage-approval.json').exists():raise ValueError('Cleanup approval must remain absent')
    with (OUTPUT/'execution.lock').open('r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.rollback:
            installed=json.loads((ledger/'installed.json').read_text())
            if any(sha(p)!=h for p,h in installed['runtime'].items()):raise ValueError('Newer runtime requires reviewed recovery')
            pid=helper.review_pid();helper.stop_review(pid);restore(ledger);new=helper.launch_review();time.sleep(.4)
            helper.save(ledger/'rollback.json',{'at':datetime.now(timezone.utc).isoformat(),'review_pid':new.pid,'database_restored':False,'permissions_changed':False});return
        source=Path(a.source)
        if helper.git(source,'rev-parse','HEAD')!=a.commit or helper.git(source,'status','--porcelain'):raise ValueError('Exact clean tested source required')
        spec=importlib.util.spec_from_file_location('installed_runtime_guard',RUNTIME/'runner.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard);guard.verify_runtime(RUNTIME)
        ledger.mkdir(mode=0o700)
        checkpoint={'at':datetime.now(timezone.utc).isoformat(),'before':{n:sha(RUNTIME/n) for n in MODULES},
            'preserved':{str(p):sha(p) for p in (OUTPUT/'owner-review-access.json',RUNTIME/'storage.py',RUNTIME/'lifecycle.py',Path('/etc/optibrain/business-storage-policy.json'))}}
        archive=ledger/'pre-queue-runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for name in MODULES:tar.add(RUNTIME/name,arcname=name,recursive=False)
        archive.chmod(0o600);checkpoint['archive_sha256']=sha(archive);helper.save(ledger/'checkpoint.json',checkpoint)
        oldpid=helper.review_pid();new=None;stopped=False
        try:
            for name in MODULES[:-1]:
                import subprocess
                raw=subprocess.check_output(['git','-c','safe.directory='+str(source),'-C',str(source),'show',a.commit+':ops/business_autopilot/'+name])
                assert raw==(source/'ops/business_autopilot'/name).read_bytes();helper.atomic(RUNTIME/name,raw)
            manifest={p.name:sha(p) for p in RUNTIME.iterdir() if p.name!='manifest.json'};assert len(manifest)==13
            helper.atomic(RUNTIME/'manifest.json',(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
            for path,h in checkpoint['preserved'].items():assert sha(path)==h
            helper.stop_review(oldpid);stopped=True;new=helper.launch_review();time.sleep(.4)
            if new.poll() is not None:raise RuntimeError('Private owner review failed')
            proof=health()
            helper.save(ledger/'installed.json',{'at':datetime.now(timezone.utc).isoformat(),'source_commit':a.commit,
                'runtime':{str(RUNTIME/n):sha(RUNTIME/n) for n in MODULES},'review_pid':new.pid,'queue':proof,
                'database_restored':False,'permissions_changed':False,'cleanup_enabled':False,'new_scheduler':False})
        except Exception:
            if new and new.poll() is None:helper.stop_review(new.pid)
            restore(ledger)
            if stopped:helper.launch_review()
            raise
    print(json.dumps({'installed':'PASS','queue':proof,'private_review_pid':new.pid,'permissions_changed':False}))


if __name__=='__main__':main()
