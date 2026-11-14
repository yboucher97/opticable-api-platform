"""Secret-free preservation proof; native local health only, no provider writes."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def run(args): return subprocess.check_output(args, text=True, timeout=20).strip()
def digest(p): return sha256(Path(p).read_bytes()).hexdigest()


def capture():
    units = {}
    for name in ('opticable-workflow-api','opticable-password-pdf','opticable-omada-site','caddy'):
        units[name+'.service'] = dict(l.split('=',1) for l in run(['systemctl','show',name,
            '-p','MainPID','-p','ActiveState','-p','SubState','-p','NRestarts']).splitlines())
    envs = {u:dict(l.split('=',1) for l in Path('/proc',v['MainPID'],'environ').read_text().split('\0') if '=' in l) for u,v in units.items()}
    checks = json.loads(Path('/var/lib/optibrain/autonomous-operations/45-runtime-flags.json').read_text())
    flags = [envs[c['unit']].get(c['flag']) == c['expected_disabled_value'] for c in checks]
    baseline = json.loads(Path('/var/lib/optibrain/monitoring-self-healing-20261112/rollout-baseline.json').read_text())
    protected = {p:digest(p) for p in baseline['protected']}
    changed = [p for p,h in protected.items() if h != baseline['protected'][p]]
    env = envs['opticable-workflow-api.service']; key = env[env.get('SITE_WORKFLOW_API_KEY_ENV','SITE_WORKFLOW_API_KEY')]
    health = {}
    for name,url,headers in (
        ('api','http://127.0.0.1:8100/v1/system/health',{'X-API-Key':key}),
        ('pdf',env.get('PASSWORD_PDF_BASE_URL','http://127.0.0.1:8000')+'/health',{'X-API-Key':env.get('PASSWORD_PDF_API_KEY','')}),
        ('omada',env.get('OMADA_SITE_CREATOR_BASE_URL','http://127.0.0.1:3210')+'/api/health',{})):
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=10) as r: health[name] = r.status
    backup = json.loads(Path('/var/lib/optibrain/phase2a/state.json').read_text())
    return {'at':datetime.now(timezone.utc).isoformat(),'host':os.uname().nodename,
        'production_sha':run(['git','-c','safe.directory=/opt/opticable-api-platform','-C','/opt/opticable-api-platform','rev-parse','HEAD']),
        'units':units,'health':health,'flag_checks':len(flags),'all_flags_disabled':all(flags),
        'protected_settings_checked':len(protected),'protected_changes':changed,'protected':protected,
        'existing_owner_credentials_sha256':digest('/var/lib/opticable-workflow-api/output/automation/business-autopilot/owner-review-access.json'),
        'monitoring_sha256':{p:digest(p) for p in ('/usr/local/lib/optibrain/current_readiness.py','/usr/local/lib/optibrain/queue-metrics.py','/usr/local/lib/optibrain/phase14-runtime-snapshot.py')},
        'timers':run(['systemctl','list-timers','--all','--no-pager','--no-legend']),
        'backup_generation':backup.get('generation'),'backup_verification':backup.get('verification_status'),
        'approval_file_present':Path('/etc/optibrain/business-storage-approval.json').exists()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--baseline');a=parser.parse_args()
    value=capture()
    assert value['host']=='vps-f8e9b20e' and value['production_sha']=='ec9a8e85095b57faf21212000652912e08093da4'
    assert value['flag_checks']==45 and value['all_flags_disabled'] and value['protected_settings_checked']==76 and not value['protected_changes']
    assert all(v['ActiveState']=='active' and v['NRestarts']=='0' for v in value['units'].values()) and all(c==200 for c in value['health'].values())
    assert not value['approval_file_present']
    if a.baseline:
        before=json.loads(Path(a.baseline).read_text())
        for key in ('production_sha','units','protected','existing_owner_credentials_sha256','monitoring_sha256'):
            assert before[key]==value[key], 'Protected state changed: '+key
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    print(json.dumps({k:value[k] for k in ('host','production_sha','flag_checks','all_flags_disabled','protected_settings_checked','protected_changes','health','approval_file_present')}))


if __name__=='__main__':main()
