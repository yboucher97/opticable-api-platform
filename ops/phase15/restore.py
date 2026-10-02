#!/usr/bin/env python3
"""Checksum-pinned application restore to a prepared recovery target. No starts/network."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import sys

sys.dont_write_bytecode=True

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('recovery_validation',REPO/'ops/backup/optibrain-restore-drill.py')
validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)
spec=importlib.util.spec_from_file_location('fresh_bootstrap',REPO/'ops/phase15/bootstrap.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
STATE_PREFIXES=('/var/lib/opticable-workflow-api','/var/lib/opticable-api-platform/shared',
                '/var/lib/opticable-password-pdf','/var/lib/opticable-omada-site','/var/lib/optibrain')
CONFIG_PREFIXES=('/etc/optibrain','/etc/opticable-password-pdf')
CONFIG_FILES=('/etc/opticable-workflow-api.env','/etc/opticable-password-pdf.env','/etc/opticable-omada-site.env')


def selected(path):
    return path in CONFIG_FILES or any(path==prefix or path.startswith(prefix+'/') for prefix in STATE_PREFIXES+CONFIG_PREFIXES)


def restore(archive,expected,root,workspace):
    bootstrap.require(os.geteuid()==0,'Root recovery required')
    bootstrap.require(root.is_absolute() and root.is_dir() and root==root.resolve(),'Explicit canonical target required')
    bootstrap.require((root/'etc/optibrain-rebuild-target').is_file(),'Fresh recovery target marker required')
    bootstrap.verify(root)
    bootstrap.require(not (root/'var/lib/optibrain/rebuild-restore-receipt.json').exists(),'Already restored; refuse replay')
    # Validate the entire archive, all file hashes and all eight stores BEFORE writes.
    proof=validation.validate(archive,expected,workspace)
    uid,gid=bootstrap.ids(root)
    copied=0
    with tempfile.TemporaryDirectory(prefix='restore-',dir=workspace) as temporary:
        scratch=Path(temporary);validation.extract(archive,scratch)
        generation=next(scratch.glob('generation-*'))
        manifest=json.loads((generation/'manifest.json').read_text())
        mappings=[]
        seen=set()
        for row in manifest['source_metadata']:
            name=row['source_path']
            if not selected(name) or name in seen:
                continue
            seen.add(name)
            if name.endswith(('.db-wal','.db-shm')) or '/ms-playwright/' in name or name.endswith('/ms-playwright'):
                continue  # SQLite online snapshots supersede sidecars; retired browser cache is not runtime state.
            if (name in {'/etc/optibrain/mutation-control.json','/etc/optibrain/rebuild-safety.env',
                         '/etc/optibrain/admin-helper.sha256','/etc/optibrain/master-runbook.sha256'}
                    or name=='/etc/optibrain/authorize-persistent-codex-development'
                    or 'authorization' in Path(name).name):
                continue  # Old execution authority never survives recovery.
            bootstrap.require(row['owner'] in uid and row['group'] in gid,'Undocumented service identity in archive')
            source=generation/validation.relative(row['backup_path'])
            target=bootstrap.target_path(root,name)
            bootstrap.require(source.exists(),'Manifest recovery target absent')
            mode=int(row['mode'],8)
            mappings.append((source,target,row['type'],uid[row['owner']],gid[row['group']],mode))
        # Preflight every mapping and destination first; no traversal/symlink target allowed.
        for source,target,kind,owner,group,mode in mappings:
            bootstrap.require(kind in {'file','directory'},'Unsupported recovery type')
            bootstrap.require(not (kind=='file' and target.exists() and not target.is_file()),'Recovery destination collision')
        # Create directories first, then file copies; restore modes after children exist.
        for source,target,kind,owner,group,mode in mappings:
            if kind=='directory':target.mkdir(parents=True,exist_ok=True)
        for source,target,kind,owner,group,mode in mappings:
            if kind=='file':
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,target);copied+=1
        # The core online snapshot is deliberately stored outside persistent state.
        core=root/'var/lib/opticable-workflow-api/output/automation/automation.db'
        shutil.copyfile(generation/'database/automation.db',core)
        os.chown(core,uid['opticable-workflow-api'],gid['opticable-workflow-api']);core.chmod(0o600)
        for source,target,kind,owner,group,mode in sorted(mappings,key=lambda r:len(r[1].parts),reverse=True):
            os.chown(target,owner,group);target.chmod(mode)
        # Restore safe configuration, then intersect it with recovery-only denial.
        (root/'etc/optibrain/phase12-runner.env').write_text('OPTIBRAIN_BUSINESS_AUTO_WRITES=0\nOPTIBRAIN_AUTO_TEST_TASK=0\n')
        (root/'etc/optibrain/phase9-form-enrichment.env').write_text('OPTIBRAIN_PHASE9_FORM_ENRICHMENT=off\nOPTIBRAIN_PHASE9_FORM_GO_LIVE=off\n')
        for p in ('phase12-runner.env','phase9-form-enrichment.env'):
            os.chown(root/'etc/optibrain'/p,0,0);(root/'etc/optibrain'/p).chmod(0o600)
        reg=root/'etc/optibrain/phase7-canary-registration.json'
        if reg.exists():
            value=json.loads(reg.read_text());value['business_actions_enabled']=False
            for key in ('create_approval_id','create_request_hash','crm_approval_id','outbound_approval_id'):value[key]=None
            reg.write_text(json.dumps(value,indent=2)+'\n');os.chown(reg,0,0);reg.chmod(0o644)
        baseline=root/'etc/optibrain/protected-runtime-versions.json'
        if not baseline.exists():
            old=root/'var/lib/optibrain/phase13/private-evidence/provider-summary.json'
            bootstrap.require(old.is_file(),'Protected version evidence missing')
            shutil.copyfile(old,baseline);os.chown(baseline,0,gid['opticable-workflow-api']);baseline.chmod(0o640)
        dbs=[core]+[root/str(validation.relative(row['backup_path'])).removeprefix('state/')
                    for row in manifest['sqlite_databases'] if row['backup_path'].startswith('state/')]
        checks={}
        for path in dbs:
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                db.execute('PRAGMA query_only=ON');checks[path.name]=db.execute('PRAGMA integrity_check').fetchone()[0]
        bootstrap.require(len(checks)==8 and all(v=='ok' for v in checks.values()),'Restored SQLite check failed')
    bootstrap.verify(root)
    receipt=dict(schema=1,archive_sha256=expected,generation=proof['generation'],restored_files=copied,
                 databases=checks,safety_defaults='PASS',timers='MASKED',writers_enabled=False,provider_calls=0,
                 source_strategy='Exact repository/bundle checkout; old source archive remains recovery evidence',
                 omitted='SSH host identity, live units/enables, browser cache, old execution authorizations')
    p=root/'var/lib/optibrain/rebuild-restore-receipt.json';p.write_text(json.dumps(receipt,indent=2)+'\n');p.chmod(0o600)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--target-root',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args()
    try:
        os.umask(0o077)
        bootstrap.require(args.workspace.is_absolute() and args.workspace.is_dir() and args.workspace==args.workspace.resolve(),
                          'Explicit existing private staging required')
        bootstrap.require(args.workspace.stat().st_uid==0 and not args.workspace.stat().st_mode&0o077,'Untrusted restore workspace')
        print(json.dumps(restore(args.archive,args.sha256,args.target_root,args.workspace),sort_keys=True))
    except Exception as exc:
        raise SystemExit('Recovery refused: '+(str(exc) if isinstance(exc,(ValueError,validation.DrillError)) else type(exc).__name__))
