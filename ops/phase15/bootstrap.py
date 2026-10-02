#!/usr/bin/env python3
"""Bounded CHECK/PREPARE/VERIFY for an explicit fresh host/root. Never starts units."""
import argparse
import grp
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

REPO = Path(__file__).resolve().parents[2]
USERS = ('optibrain', 'opticable-workflow-api', 'opticable-password-pdf', 'opticable-omada-site')
APP = ('opticable-workflow-api', 'opticable-password-pdf', 'opticable-omada-site')
TIMERS = ('optibrain-backup','optibrain-phase2a-upload','opticable-phase9-intake-receipts',
          'opticable-phase10-service-events','opticable-phase12-test-runner')
RETIRED = tuple(f'optibrain-agent-{n}.{k}' for n in ('dispatch','status','usage') for k in ('service','timer'))
SAFETY = {
    'OPTICABLE_AUTOMATION_ENABLED':'false', 'OPTIBRAIN_CRM_DRIFT_ENABLED':'false',
    'OPTIBRAIN_BUSINESS_AUTO_WRITES':'0', 'OPTIBRAIN_AUTO_TEST_TASK':'0',
    'OPTIBRAIN_AUTO_TEST_PROJECT':'0', 'OPTIBRAIN_AUTO_TEST_INTERNAL':'0',
    'OPTIBRAIN_PHASE9_FORM_ENRICHMENT':'off', 'OPTIBRAIN_PHASE9_FORM_GO_LIVE':'off',
    'OPTIBRAIN_CRM_LEAD_WRITES':'off','OPTIBRAIN_CRM_CANARY':'off',
    'OPTIBRAIN_LEAD_CREATE_CANARY':'off','OPTIBRAIN_OUTBOUND_SENDS':'off',
    'OPTIBRAIN_SALES_DRAFTS':'off', 'OPTICABLE_CONNECT_STANDBY_ENABLED':'false',
    'OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION':'false',
}
REQUIRED = ('python3','git','sqlite3','age','caddy','curl','openssl','systemd-analyze','ip','tar','node','npm')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def target_path(root, name):
    require(name.startswith('/') and '..' not in Path(name).parts, 'Noncanonical target path')
    path = root / name.lstrip('/')
    for parent in reversed((path, *path.parents)):
        if parent == root.parent or root not in (parent,*parent.parents):
            continue
        require(not parent.is_symlink(), 'Symlink in target path')
    return path


def write(root, name, content, mode=0o600):
    path = target_path(root,name)
    path.parent.mkdir(parents=True,exist_ok=True)
    require(not path.exists(), 'Refusing to overwrite existing configuration')
    fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'w') as stream:
        stream.write(content)
    path.chmod(mode)


def ids(root):
    passwd = {r.split(':')[0]:int(r.split(':')[2]) for r in (root/'etc/passwd').read_text().splitlines()}
    groups = {r.split(':')[0]:int(r.split(':')[2]) for r in (root/'etc/group').read_text().splitlines()}
    return passwd, groups


def check(root):
    missing = []
    for command in REQUIRED:
        if not any((root/p/command).is_file() for p in ('usr/local/bin','usr/bin','usr/sbin','bin','sbin')):
            missing.append(command)
    os_release = (root/'etc/os-release').read_text() if (root/'etc/os-release').exists() else ''
    return dict(mode='CHECK',root=str(root),supported_os='ID=ubuntu' in os_release and 'VERSION_ID="24.04"' in os_release,
                missing_commands=missing,repo_requirements=(REPO/'apps/workflow-api/requirements.txt').is_file(),
                writes_performed=0,units_started=0)


def prepare(root):
    require(os.geteuid()==0,'Root prepare required')
    require(check(root)['supported_os'],'Supported fresh Ubuntu 24.04 required')
    require((root/'etc/optibrain-rebuild-target').is_file(),'Explicit fresh-host marker required')
    require(not (root/'var/lib/optibrain/releases/current.json').exists(),'Existing production release; prepare forbidden')
    require(not (root/'etc/optibrain').exists(),'Existing control configuration; prepare forbidden')
    require(not (root/'var/lib/opticable-workflow-api/output/automation').exists(),'Existing journals; prepare forbidden')
    pw, groups = ids(root)
    for name in USERS:
        if name not in pw:
            args = ['useradd'] + ([] if root==Path('/') else ['--root',str(root)])
            args += ['--user-group','--create-home','--home-dir',('/home/optibrain' if name=='optibrain' else '/var/lib/'+name),
                     '--shell',('/bin/bash' if name=='optibrain' else '/usr/sbin/nologin')]
            if name!='optibrain': args += ['--system']
            subprocess.run(args+[name],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if 'siteandpassword' not in groups:
        subprocess.run(['groupadd']+([] if root==Path('/') else ['--root',str(root)])+['--system','siteandpassword'],check=True)
    pw, groups = ids(root)
    directories = {'/etc/optibrain':(0,0,0o755),'/etc/opticable-password-pdf':(0,0,0o755),
        '/var/lib/optibrain':(0,0,0o700),'/var/backups/optibrain':(0,0,0o700),
        '/var/lib/opticable-api-platform/shared':(pw['opticable-workflow-api'],groups['opticable-workflow-api'],0o750),
        '/opt/optibrain-releases':(0,0,0o755),'/run/optibrain-readiness':(0,0,0o755),
        '/var/log/optibrain':(0,0,0o700)}
    for name in APP:
        directories['/var/lib/'+name]=(pw[name],groups[name],0o750)
    directories['/var/lib/opticable-workflow-api/output/automation']=(pw[APP[0]],groups[APP[0]],0o750)
    for name,(uid,gid,mode) in directories.items():
        p=target_path(root,name);p.mkdir(parents=True,exist_ok=True);os.chown(p,uid,gid);p.chmod(mode)
    write(root,'/etc/optibrain/rebuild-safety.env',''.join(k+'='+v+'\n' for k,v in SAFETY.items()))
    policy=dict(schema=1,test_writes_enabled=False,allowed_actions=['crm.task.create'],real_canary_allowed=False)
    write(root,'/etc/optibrain/mutation-control.json',json.dumps(policy,indent=2)+'\n',0o640)
    os.chown(root/'etc/optibrain/mutation-control.json',0,groups[APP[0]])
    for name in APP:
        write(root,'/etc/'+name+'.env','')
    write(root,'/etc/optibrain/phase12-runner.env','OPTIBRAIN_BUSINESS_AUTO_WRITES=0\nOPTIBRAIN_AUTO_TEST_TASK=0\n')
    write(root,'/etc/optibrain/phase9-receipt-export.env','')
    write(root,'/etc/optibrain/phase9-form-enrichment.env','OPTIBRAIN_PHASE9_FORM_ENRICHMENT=off\n')
    for src in sorted((REPO/'ops/phase15/systemd').glob('*')):
        if src.is_file():write(root,'/etc/systemd/system/'+src.name,src.read_text(),0o644)
    for name in APP+TIMERS[2:]:
        write(root,'/etc/systemd/system/'+name+'.service.d/99-rebuild-safety.conf',
              '[Service]\nEnvironmentFile=/etc/optibrain/rebuild-safety.env\n',0o644)
    for name in [n+'.timer' for n in TIMERS]+['opticable-phase12-test-runner.service']+list(RETIRED):
        p=target_path(root,'/etc/systemd/system/'+name)
        if p.is_file():
            saved=p.with_suffix(p.suffix+'.rebuild-disabled');p.rename(saved)
        p.symlink_to('/dev/null')
    helpers = {'/usr/local/sbin/opticable-api-deploy-root':'deploy/manual-guarded-release.py',
        '/usr/local/sbin/optibrain-admin':'ops/admin/optibrain-admin.py',
        '/usr/local/sbin/optibrain-admin-update':'ops/admin/optibrain-admin-update.py',
        '/usr/local/lib/optibrain-backup/optibrain-backup.sh':'ops/backup/optibrain-backup.sh',
        '/usr/local/lib/optibrain-backup/optibrain-phase2a-upload.sh':'ops/backup/optibrain-phase2a-upload.sh',
        '/usr/local/lib/optibrain-backup/optibrain-phase2a-upload.py':'ops/backup/optibrain-phase2a-upload.py',
        '/usr/local/lib/optibrain-backup/optibrain-restore-drill.py':'ops/backup/optibrain-restore-drill.py',
        '/usr/local/lib/optibrain/phase12-run-test-lab.py':'ops/phase12/run_test_lab.py',
        '/usr/local/lib/optibrain/phase14-runtime-snapshot.py':'ops/phase14/runtime_snapshot.py',
        '/usr/local/lib/optibrain/phase14-retention.py':'ops/phase14/retention.py',
        '/usr/local/lib/optibrain/queue-metrics.py':'ops/phase15/queue_metrics.py'}
    for dest,src in helpers.items():
        mode=0o750 if dest.startswith('/usr/local/sbin/optibrain-admin') or dest.endswith(('optibrain-backup.sh','optibrain-phase2a-upload.sh','optibrain-restore-drill.py')) else 0o755
        write(root,dest,(REPO/src).read_text(),mode)
    for name,source in [('admin-helper.sha256','ops/admin/optibrain-admin.sha256'),
                        ('master-runbook.sha256','ops/admin/master-runbook.sha256')]:
        write(root,'/etc/optibrain/'+name,(REPO/source).read_text(),0o440 if name=='admin-helper.sha256' else 0o600)
    # Vendor Node tarballs use /usr/local; the live unit contract uses /usr/bin.
    # Only a fresh target without Node at that unit path may receive the link.
    node=target_path(root,'/usr/bin/node')
    if not node.exists() and (root/'usr/local/bin/node').is_file():node.symlink_to('/usr/local/bin/node')
    vendor=target_path(root,'/etc/caddy/Caddyfile')
    if vendor.exists():
        require(vendor.read_text().startswith('# The Caddyfile is an easy way'), 'Non-vendor Caddy configuration on fresh target')
        require(not vendor.with_name('Caddyfile.vendor-default').exists(),'Vendor config already preserved')
        vendor.rename(vendor.with_name('Caddyfile.vendor-default'))
    write(root,'/etc/caddy/Caddyfile','import /etc/caddy/conf.d/*.caddy\n',0o644)
    write(root,'/etc/caddy/conf.d/opticable-api-platform.caddy',
          (REPO/'ops/phase15/caddy/opticable-api-platform.caddy').read_text(),0o644)
    write(root,'/etc/systemd/journald.conf.d/30-optibrain-retention.conf',
          (REPO/'ops/phase13-p1/30-optibrain-retention.conf').read_text(),0o644)
    return dict(mode='PREPARE',root=str(root),users=list(USERS),units_started=0,writers_enabled=False)


def verify(root):
    policy=json.loads((root/'etc/optibrain/mutation-control.json').read_text())
    pw,groups=ids(root)
    p=root/'etc/optibrain/mutation-control.json';info=p.lstat()
    flags=dict(r.split('=',1) for r in (root/'etc/optibrain/rebuild-safety.env').read_text().splitlines())
    masks=[n+'.timer' for n in TIMERS]+['opticable-phase12-test-runner.service']+list(RETIRED)
    require(all((root/'etc/systemd/system'/n).is_symlink() and os.readlink(root/'etc/systemd/system'/n)=='/dev/null'
                for n in masks),'Recovery timers or retired units unmasked')
    require(policy['test_writes_enabled'] is False and policy['real_canary_allowed'] is False,'Writers enabled')
    require(info.st_uid==0 and not info.st_mode&0o022 and stat.S_ISREG(info.st_mode),'Untrusted safety policy')
    require(all(flags.get(k)==v for k,v in SAFETY.items()),'Recovery flags changed')
    require(all(n in pw and n in groups for n in USERS),'Service identity missing')
    require(not (root/'etc/optibrain/authorize-persistent-codex-development').exists(),'Development authority present')
    return dict(mode='VERIFY',root=str(root),safety_defaults='PASS',masks=len(masks),users=len(USERS),units_started=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--target-root',type=Path,required=True)
    parser.add_argument('--mode',choices=('check','prepare','verify'),default='check')
    args=parser.parse_args()
    try:
        root=args.target_root
        require(root.is_absolute() and root.is_dir() and root==root.resolve(),'Explicit existing canonical target root required')
        for p in (root,*root.parents):
            require(not p.is_symlink(),'Untrusted target root')
        print(json.dumps({'check':check,'prepare':prepare,'verify':verify}[args.mode](root),sort_keys=True))
    except Exception as exc:
        raise SystemExit('Bootstrap refused: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
