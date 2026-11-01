#!/usr/bin/env python3
"""Forced-command health + two fixed owner-report files. No maintenance capability, shell or credential output."""
import json,os,shutil,sqlite3,subprocess,time,sys,tempfile,hashlib,re,pwd
from pathlib import Path
from urllib.request import Request,urlopen

def validate_report(data):
    assert 0<len(data)<=65536 and b'\x00' not in data
    value=data.decode('utf-8');assert value.startswith('OPTIBRAIN MIGRATION PROGRESS')
    assert not re.search(r'-----BEGIN .*PRIVATE KEY-----|Bearer\s+[^\s]+',value,re.I)
    return value

def publish_report(data):
    validate_report(data);owner=pwd.getpwnam('optibrain')
    for name in ['optibrain-migration-progress-20261101.txt','optibrain-autonomous-migration-20261101.txt','optibrain-executor-completion-20261101.txt']:
        destination=Path('/home/optibrain')/name;assert not destination.is_symlink()
        fd,temp=tempfile.mkstemp(prefix='.migration-report-',dir=destination.parent)
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600);os.fchown(stream.fileno(),owner.pw_uid,owner.pw_gid)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,destination)
        directory=os.open(destination.parent,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    files=[Path('/home/optibrain')/name for name in ['optibrain-migration-progress-20261101.txt','optibrain-autonomous-migration-20261101.txt','optibrain-executor-completion-20261101.txt']]
    assert all(p.read_bytes()==data and p.stat().st_uid==owner.pw_uid and p.stat().st_mode&0o777==0o600 for p in files)
    print(json.dumps({'status':'PASS','report_sha256':hashlib.sha256(files[0].read_bytes()).hexdigest(),'bytes':len(data),'business_mutations':0,'both_files_read_back':True}))

def main():
    assert os.geteuid()==0 and os.uname().nodename=='vps-214ba8cd'
    assert sys.argv[1:] in [['status'],['publish-report']]
    if sys.argv[1:] == ['publish-report']:return publish_report(sys.stdin.buffer.read(65537))
    env={}
    for line in Path('/etc/opticable-workflow-api.env').read_text().splitlines():
        if line and not line.lstrip().startswith('#') and '=' in line:
            k,v=line.split('=',1);env[k.removeprefix('export ').strip()]=v.strip().strip('"').strip("'")
    key=env[env.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]
    fenced=Path('/var/lib/optibrain-migration-source/FROZEN').exists()
    try:
        with urlopen(Request('http://127.0.0.1:8100/v1/system/health',headers={'X-API-Key':key}),timeout=10) as response:h=json.load(response)
    except Exception:
        if not fenced:raise
        h={'status':'approved_frozen','ok':False}

    transition=False
    state=Path('/var/lib/optibrain-migration-source/state.json')
    if fenced and state.exists():
        phase=json.loads(state.read_text());transition=phase.get('event')=='FREEZE_INTENT' and 0<=time.time()-phase.get('freeze_started_epoch',0)<210
    units=['opticable-workflow-api.service','opticable-password-pdf.service','opticable-omada-site.service','caddy.service']
    states={u:subprocess.check_output(['systemctl','show',u,'-p','ActiveState','--value'],text=True).strip() for u in units}
    p=Path('/var/lib/opticable-workflow-api/output/automation/automation.db')
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        db.execute('pragma query_only=on')
        runs=[list(r) for r in db.execute('select status,count(*) from automation_runs group by status')]
        leases=db.execute('select count(*) from automation_sync_checkpoints where lease_token is not null').fetchone()[0]
    print(json.dumps({'host':os.uname().nodename,'checked_epoch':time.time(),'root_free_bytes':shutil.disk_usage('/').free,
        'production_sha':subprocess.check_output(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','rev-parse','HEAD'],text=True).strip(),
        'API':{'ok':h.get('ok'),'version':h.get('version'),'status':h.get('status')},'services':states,
        'active_sync_leases':leases,'run_states':runs,'authority':'FROZEN' if fenced else 'OLD','fenced':fenced,'freeze_transition':transition,'read_only':True,'maintenance_capability':False}))

if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps({'status':'BLOCKED','error':type(e).__name__}));raise SystemExit(1)
