#!/bin/bash
# DEPRECATED Phase 14: retained historical implementation; direct execution refused.
printf '%s\n' 'DEPRECATED: use the reviewed /usr/local/sbin/opticable-api-deploy-root or current recovery runbook.' >&2
exit 64
# Static verifier: no candidate-controlled code enters root execution.
set -Eeuo pipefail
[[ ${EUID} -eq 0 && $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || exit 64
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -I - "$1" <<'PY'
"""Installed static reconciliation verifier. Never executes candidate source.

This file is embedded verbatim into the separately reviewed root wrapper; it is
not imported from the production checkout at runtime. CLI admits no overrides.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

BASELINE = '52f11d4fc14d8582c03837e0317f849efe8aa3d7'
BRANCH = 'phase6/sales-autonomy-v1'
REMOTE = 'https://github.com/yboucher97/opticable-api-platform.git'
PROD = Path('/opt/opticable-api-platform')
GUARD = Path('/var/lib/optibrain/phase6/active-release.json')
AUTH = Path('/etc/optibrain/phase6-release-authorization.json')
OFFHOST = Path('/var/lib/optibrain/phase2a/state.json')
SAFE_ENV = {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0'}
REQUIRED = {'baseline-restore','baseline-offhost','candidate-health-smoke','candidate-restore','rollback-proof','candidate-offhost'}


def check(value, message):
    if not value: raise RuntimeError(message)


def sha(path):
    with path.open('rb') as f:
        h=hashlib.sha256()
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def protected(path):
    # Refuse parent substitution as well as a symlink leaf.
    for parent in list(path.parents)[:-1]:
        info=parent.lstat()
        check(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode & 0o022, 'unsafe_policy_parent')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as f:
        info=os.fstat(f.fileno())
        check(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and not info.st_mode & 0o077,'unsafe_policy_file')
        return json.load(f)


def run(args):
    return subprocess.check_output(args,env=SAFE_ENV,stdin=subprocess.DEVNULL,text=True,timeout=120).strip()


def validate_release(target,guard,auth,receipt,now=None):
    from datetime import datetime,timezone
    now=now or datetime.now(timezone.utc)
    check(isinstance(target,str) and re.fullmatch(r'[a-f0-9]{40}',target),'invalid_sha')
    check(auth.get('candidate')==auth.get('validated_sha')==guard.get('candidate')==target and auth.get('baseline')==guard.get('baseline')==BASELINE and auth.get('branch')==BRANCH,'release_identity')
    approved=datetime.fromisoformat(auth['approved_at'].replace('Z','+00:00'));expires=datetime.fromisoformat(auth['expires_at'].replace('Z','+00:00'))
    check(approved.tzinfo is not None and expires.tzinfo is not None and approved<=now<expires and 0<(expires-approved).total_seconds()<=7200,'release_expired')
    check(all(type(auth.get(k)) is int and auth[k]>=n for k,n in (('ci_run_id',1),('full_tests',580),('subtests',540),('focused_tests',156))) and all(auth.get(k)==0 for k in ('failures','errors','skipped')),'validation_evidence')
    check(re.fullmatch(r'human:[A-Za-z0-9@._-]{3,120}',auth.get('approved_by','')),'human_authority')
    check(guard.get('status') in {'promoted','complete'} and REQUIRED<=set(guard.get('completed_gates',[])),'recovery_gates_missing')
    check(guard.get('workflow_hashes_verified') is True and guard.get('external_actions_enabled') is False and guard.get('recovery_strategy')=='forward-only-preserve-v2','unsafe_recovery_state')
    backup=guard.get('candidate_backup',{})
    check(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z',backup.get('generation','')) and re.fullmatch(r'[a-f0-9]{64}',backup.get('sha256','')),'invalid_backup_reference')
    check(receipt.get('generation')==backup['generation'] and receipt.get('source_sha256')==backup['sha256'] and receipt.get('verification_status')=='download_hash_verified','backup_receipt_mismatch')
    check(guard.get('pre_reference_sha')==BASELINE and guard.get('recovery_reference_verified') is True,'recovery_reference_missing')


def reconcile(target):
    check(os.geteuid()==0,'root_required')
    guard,auth,receipt=(protected(p) for p in (GUARD,AUTH,OFFHOST))
    validate_release(target,guard,auth,receipt)
    check(guard.get('authorization_sha256')==sha(AUTH),'authorization_changed')
    ci=json.loads(run(['/usr/bin/curl','--fail','--silent','--show-error','--max-time','20',
        'https://api.github.com/repos/yboucher97/opticable-api-platform/actions/runs/'+str(auth['ci_run_id'])]))
    check(ci.get('head_sha')==target and ci.get('head_branch')==BRANCH and ci.get('name')=='Validate API Platform' and ci.get('conclusion')=='success' and ci.get('repository',{}).get('full_name')=='yboucher97/opticable-api-platform','ci_repository_or_sha')
    archive=Path('/var/backups/optibrain')/('optibrain-backup-'+guard['candidate_backup']['generation']+'.tar.gz')
    info=archive.lstat();check(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and not info.st_mode & 0o077,'unsafe_backup')
    check(sha(archive)==guard['candidate_backup']['sha256'],'backup_changed')
    # Only commit metadata from the hard-coded repository, never script material.
    with tempfile.TemporaryDirectory(prefix='opticable-trusted-main-',dir='/var/tmp') as temp:
        os.chmod(temp,0o700)
        git=['/usr/bin/git','-c','protocol.file.allow=never','-C',temp]
        run(['/usr/bin/git','init','--bare','--quiet',temp])
        run(git+['fetch','--quiet','--filter=blob:none',REMOTE,'refs/heads/main:refs/heads/reviewed-main','refs/heads/'+BRANCH+':refs/heads/reviewed-phase6'])
        check(run(git+['rev-parse','refs/heads/reviewed-main'])==target==run(git+['rev-parse','refs/heads/reviewed-phase6']),'remote_identity_changed')
        run(git+['merge-base','--is-ancestor',BASELINE,target])
    check(run(['/usr/sbin/runuser','-u','optibrain','--','/usr/bin/git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(PROD),'rev-parse','HEAD'])==target,'candidate_not_already_staged')
    status=run(['/usr/sbin/runuser','-u','optibrain','--','/usr/bin/git','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(PROD),'status','--porcelain','--untracked-files=all'])
    check(status=='?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh','production_dirty')
    check(sha(PROD/'ops/backup/optibrain-cloudflare-auth-diagnostic.sh')=='7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000','diagnostic_changed')
    check(run(['/usr/bin/systemctl','is-active','opticable-workflow-api'])=='active','service_unhealthy')
    health=json.loads(run(['/usr/bin/curl','--fail','--silent','--show-error','--max-time','15','http://127.0.0.1:8100/health']))
    check(health.get('status')=='ok' and health.get('version')=='1.11.0','health_version')
    print(json.dumps({'result':'PASS','mode':'health-only-reconciliation','sha':target,'candidate_code_executed':False,'production_mutations':0}))


if __name__=='__main__':
    import sys
    check(len(sys.argv)==2 and re.fullmatch(r'[a-f0-9]{40}',sys.argv[1]),'invalid_command')
    reconcile(sys.argv[1])
PY
