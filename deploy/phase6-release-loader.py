#!/usr/bin/python3
"""Separately reviewed static human-root entry point; never import branch code.

Default is plan-only. Installation/execution requires separate approval.
Fixed repository, paths, operation, release identity and baseline; no overrides.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile

BASELINE = '52f11d4fc14d8582c03837e0317f849efe8aa3d7'
BRANCH = 'phase6/sales-autonomy-v1'
REMOTE = 'https://github.com/yboucher97/opticable-api-platform.git'
AUTH = Path('/etc/optibrain/phase6-release-authorization.json')
ROOT = Path('/var/lib/optibrain/phase6')
PROD = Path('/opt/opticable-api-platform')
RECEIPT = Path('/var/lib/optibrain/phase2a/state.json')
RECOVERY = 'recovery/post-phase5-business-autonomy-v1-20260928'
CAMPAIGN = 'ops/phase6/production_campaign.py'
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}


def check(value, reason):
    if not value:
        raise RuntimeError(reason)


def protected(path):
    for parent in list(path.parents)[:-1]:
        info = parent.lstat()
        check(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022, 'unsafe_parent')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        check(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and not info.st_mode & 0o077, 'unsafe_policy')
        return json.load(stream)


def command(args, binary=False):
    return subprocess.check_output(args, env=ENV, stdin=subprocess.DEVNULL, timeout=120, text=not binary)


def validate_authority(auth, candidate):
    required={"candidate","baseline","branch","approved_by","approved_at","expires_at","campaign_sha256","validated_sha","ci_run_id","full_tests","subtests","focused_tests","failures","errors","skipped","release_id"}
    check(isinstance(auth,dict) and set(auth)==required,"authority_fields")
    check(re.fullmatch("[0-9]{8}-[a-z0-9-]{3,48}",auth.get("release_id","")),"release_identity")
    check(re.fullmatch('[a-f0-9]{40}', candidate) and auth.get('candidate') == auth.get('validated_sha') == candidate and candidate != BASELINE, 'candidate_authority')
    check(auth.get('baseline') == BASELINE and auth.get('branch') == BRANCH, 'repository_release_identity')
    check(re.fullmatch('human:[A-Za-z0-9@._-]{3,120}', auth.get('approved_by', '')), 'human_authority')
    now = datetime.now(timezone.utc)
    issued, expiry = (datetime.fromisoformat(auth[key].replace('Z', '+00:00')) for key in ('approved_at', 'expires_at'))
    check(issued.tzinfo is not None and expiry.tzinfo is not None and issued <= now < expiry and 0 < (expiry-issued).total_seconds() <= 7200, 'authority_lifetime')
    check(re.fullmatch('[a-f0-9]{64}', auth.get('campaign_sha256', '')), 'campaign_digest')
    check(all(type(auth.get(key)) is int and auth[key] >= minimum for key, minimum in [('ci_run_id', 1), ('full_tests', 580), ('subtests', 540), ('focused_tests', 156)]), 'validation_counts')
    check(all(type(auth.get(key)) is int and auth[key] == 0 for key in ('failures', 'errors', 'skipped')), 'validation_not_clean')


def validate_archive(data, campaign_digest):
    """Authorized Git archive is data; reject links, executable-path substitution."""
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            check(parts and not Path(member.name).is_absolute() and not any(p in {'.', '..', '.git'} for p in parts) and member.name not in seen, 'unsafe_candidate_path')
            check(member.isdir() or member.isfile(), 'candidate_link_or_special_file')
            seen.add(member.name)
        member = archive.getmember(CAMPAIGN)
        check(member.isfile() and member.size < 1024*1024, 'campaign_path_substitution')
        check(hashlib.sha256(archive.extractfile(member).read()).hexdigest() == campaign_digest, 'reviewed_campaign_changed')
    return True


def execute(candidate):
    check(os.geteuid() == 0, 'human_root_required')
    auth = protected(AUTH)
    validate_authority(auth, candidate)
    receipt = protected(RECEIPT)
    generation = receipt.get('generation', '')
    check(re.fullmatch('[0-9]{8}T[0-9]{6}Z', generation) and receipt.get('verification_status') == 'download_hash_verified', 'backup_not_verified')
    archive = Path('/var/backups/optibrain') / ('optibrain-backup-' + generation + '.tar.gz')
    info = archive.lstat()
    check(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and not info.st_mode & 0o077, 'unsafe_backup')
    with archive.open('rb') as stream:
        check(hashlib.file_digest(stream, 'sha256').hexdigest() == receipt.get('source_sha256'), 'backup_hash_mismatch')
    with tarfile.open(archive) as backup:
        member = backup.getmember('generation-' + generation + '/manifest.json')
        check(member.isfile() and member.size < 32*1024*1024, 'unsafe_backup_manifest')
        check(json.load(backup.extractfile(member)).get('production_git_sha') == BASELINE, 'backup_baseline_mismatch')
    # Production Git configuration is never interpreted as root.
    gitprod = ['/usr/sbin/runuser', '-u', 'optibrain', '--', '/usr/bin/git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', str(PROD)]
    check(command(gitprod + ['rev-parse', 'HEAD']).strip() == BASELINE, 'production_baseline_changed')
    check(command(gitprod + ['status', '--porcelain', '--untracked-files=all']).strip() == '?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh', 'production_dirty')
    check(hashlib.sha256((PROD/'ops/backup/optibrain-cloudflare-auth-diagnostic.sh').read_bytes()).hexdigest() == '7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000', 'protected_diagnostic_changed')
    ci = json.loads(command(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--max-time', '20', 'https://api.github.com/repos/yboucher97/opticable-api-platform/actions/runs/' + str(auth['ci_run_id'])]))
    check(ci.get('head_sha') == candidate and ci.get('head_branch') == BRANCH and ci.get('name') == 'Validate API Platform' and ci.get('conclusion') == 'success' and ci.get('repository', {}).get('full_name') == 'yboucher97/opticable-api-platform', 'ci_authority_mismatch')
    parent = ROOT.lstat()
    check(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and not parent.st_mode & 0o077, 'unsafe_staging_parent')
    with tempfile.TemporaryDirectory(prefix='reviewed-', dir='/var/tmp') as temporary:
        git = ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never', '-C', temporary]
        command(['/usr/bin/git', 'init', '--bare', '--quiet', temporary])
        command(git + ['fetch', '--quiet', '--filter=blob:none', REMOTE, 'refs/heads/main:refs/heads/reviewed-main', 'refs/heads/'+BRANCH+':refs/heads/reviewed-phase6', 'refs/tags/'+RECOVERY+':refs/tags/reviewed-recovery'])
        check(command(git+['rev-parse','refs/heads/reviewed-main']).strip() == BASELINE, 'main_baseline_changed')
        check(command(git+['rev-parse','refs/heads/reviewed-phase6']).strip() == candidate, 'remote_candidate_changed')
        check(command(git+['rev-parse','refs/tags/reviewed-recovery^{}']).strip() == BASELINE, 'recovery_reference_changed')
        command(git+['merge-base','--is-ancestor',BASELINE,candidate])
        # No candidate blobs/material can enter privileged execution before this point.
        material = command(git+['archive','--format=tar',candidate], binary=True)
        validate_archive(material, auth['campaign_sha256'])
        source = Path(temporary)/'reviewed-source'
        source.mkdir(mode=0o755)
        with tarfile.open(fileobj=io.BytesIO(material)) as selected:
            selected.extractall(source, filter='data')
        # Trusted Git configuration only; exact reviewed content, no filters/hooks from a checkout.
        command(['/usr/bin/git','init','--quiet',str(source)])
        sourcegit=['/usr/bin/git','-c','core.hooksPath=/dev/null','-C',str(source)]
        command(sourcegit+['fetch','--quiet',REMOTE,'refs/heads/'+BRANCH])
        check(command(sourcegit+['rev-parse','FETCH_HEAD']).strip() == candidate, 'candidate_changed_after_review')
        command(sourcegit+['symbolic-ref','HEAD','refs/heads/'+BRANCH])
        command(sourcegit+['update-ref','HEAD',candidate])
        command(sourcegit+['reset','--mixed',candidate])
        command(sourcegit+['remote','add','origin',REMOTE])
        os.chmod(temporary,0o755)
        for path in source.rglob('*'):
            check(not path.is_symlink(), 'staged_symlink')
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        check(protected(AUTH)==auth,"authority_changed")
        validate_authority(auth, candidate)
        # Reviewed exact campaign; fresh backup/recovery gates still precede service switch.
        subprocess.run(['/usr/bin/python3','-I',str(source/CAMPAIGN),'--candidate',candidate,'--execute'],env=ENV,stdin=subprocess.DEVNULL,timeout=7200,check=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    check(re.fullmatch('[a-f0-9]{40}',args.candidate),'invalid_sha')
    if args.execute:
        execute(args.candidate)
    else:
        print(json.dumps({'mode':'plan-only','candidate':args.candidate,'production_mutations':0,'candidate_code_executed':False}))
