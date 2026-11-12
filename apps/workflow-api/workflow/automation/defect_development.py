"""Prepare a development branch/PR only after paired isolated regression proof.

No credentials, provider writes, push, merge, deployment, timer or public input.
The existing GitHub connector may publish the returned draft request under the
owner's separate development authority. Production/safety code is not eligible.
"""
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tempfile

from .acquisition_store import digest
from .operational_recovery import DevelopmentScope

ELIGIBLE = {'apps/workflow-api/workflow/automation/readiness.py', 'ops/connectivity_watch/check.py'}
REPOSITORY = 'yboucher97/opticable-api-platform'
SAFE_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
RUNNER = r'''
import sys,os,socket,unittest,json
from pathlib import Path
root=Path(sys.argv[1]);pattern=sys.argv[2]
os.environ.clear();os.environ.update(PATH='/usr/bin:/bin',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1')
attempts=[]
def blocked(*args,**kwargs):
 attempts.append(1);raise AssertionError('Network forbidden in isolated defect proof')
socket.socket.connect=socket.socket.connect_ex=socket.socket.sendto=blocked
socket.create_connection=socket.getaddrinfo=blocked
sys.path[:0]=[str(root/'apps/workflow-api'),str(root/'apps/workflow-api/tests'),str(root)]
suite=unittest.defaultTestLoader.discover(str(root/'apps/workflow-api/tests'),pattern=pattern)
result=unittest.TextTestRunner(verbosity=1).run(suite)
passed=result.wasSuccessful() and not result.skipped and result.testsRun>0 and not attempts
print(json.dumps(dict(passed=passed,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),network_attempts=len(attempts))))
sys.exit(0 if passed else 1)
'''


def _limits():
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError('No-new-privileges isolation unavailable')
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
        '-c', 'init.templateDir=', '-C', str(repo), *args], env=SAFE_ENV, timeout=30,
        stderr=subprocess.DEVNULL).decode().strip()


def run_regression(repo, pattern):
    """Bounded unprivileged child; reviewed tests, Python-level network fence."""
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', RUNNER, str(repo), pattern],
            cwd=repo, env=SAFE_ENV, stdout=output, stderr=output,
            preexec_fn=_limits, start_new_session=True)
        try:code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL);process.wait()
            return dict(passed=False, timeout=True, tests=0, failures=0, errors=1, skipped=0, network_attempts=0)
        output.seek(0, 2);size = output.tell();output.seek(max(0, size - 8192));tail = output.read().decode(errors='replace')
    try:result = json.loads(tail.splitlines()[-1])
    except (ValueError, IndexError):result = dict(passed=False, tests=0, failures=0, errors=1, skipped=0, network_attempts=0)
    result.update(exit_code=code, log_sha256=hashlib.sha256(tail.encode()).hexdigest(),
                  output_bytes=size, no_new_privileges=True, network_isolation='Python-level fence; no OS namespace claim')
    result['passed'] = result.get('passed') is True and code == 0
    return result


def prepare_defect(source_repo, scope, patch, regression_code, *, source_sha, github_read, repository=REPOSITORY, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(scope, DevelopmentScope):raise ValueError('Explicit development scope required')
    scope.verify(now);source = Path(source_repo).absolute()
    # Do not read a live production checkout, even to branch it automatically.
    DevelopmentScope(source)
    if repository != REPOSITORY or not re.fullmatch('[0-9a-f]{40}', source_sha):
        raise ValueError('Exact owned repository/source required')
    if git(source, 'rev-parse', 'HEAD') != source_sha or git(source, 'status', '--porcelain'):
        raise ValueError('Clean exact source required')
    identity = github_read(repository, source_sha)
    if (not isinstance(identity, dict) or identity.get('authenticated_read') is not True
            or identity.get('repository') != repository or identity.get('sha') != source_sha
            or identity.get('tree_sha') != git(source, 'rev-parse', 'HEAD^{tree}')):
        raise ValueError('Authenticated exact GitHub base commit/tree required')
    if not isinstance(patch, dict) or not 1 <= len(patch) <= 2 or not set(patch) <= ELIGIBLE:
        raise ValueError('Only approved diagnostic helpers are eligible for automatic development')
    if any(not isinstance(v, bytes) or len(v) > 128 * 1024 for v in patch.values()) or sum(map(len, patch.values())) > 256 * 1024:
        raise ValueError('Bounded exact patch bytes required')
    if not isinstance(regression_code, bytes) or not 1 <= len(regression_code) <= 16384:
        raise ValueError('Bounded reviewed regression code required')
    fingerprint = digest([source_sha, {k: hashlib.sha256(v).hexdigest() for k, v in patch.items()}, hashlib.sha256(regression_code).hexdigest()])
    receipt_name = 'evidence/defect-' + fingerprint[:24] + '.json'
    with scope.lock():
        receipt = scope.path(receipt_name)
        if receipt.exists():
            old = json.loads(receipt.read_text());candidate = Path(old['candidate_checkout'])
            if old['input_fingerprint'] != fingerprint or git(candidate, 'rev-parse', 'HEAD') != old['commit'] or git(candidate, 'status', '--porcelain'):
                raise ValueError('Prepared branch changed; independent review required')
            return {**old, 'state': 'ALREADY_PREPARED'}
        repos = []
        for kind in ('before', 'candidate'):
            target = scope.path(kind + '-' + fingerprint[:16])
            if target.exists():raise ValueError('Existing incomplete experiment retained for review')
            git(scope.root, 'clone', '--no-hardlinks', '--no-checkout', str(source), str(target))
            git(target, 'checkout', '--detach', source_sha)
            repos.append(target)
        before, candidate = repos
        name = 'test_verified_defect_' + fingerprint[:16] + '.py'
        relative = 'apps/workflow-api/tests/' + name
        for repo in repos:
            target = scope.path(str((repo / relative).relative_to(scope.root)))
            if target.exists():raise ValueError('Regression file already exists')
            target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(regression_code)
        baseline = run_regression(before, name)
        for relative, data in patch.items():
            target = scope.path(str((candidate / relative).relative_to(scope.root)))
            git(candidate, 'cat-file', '-e', source_sha + ':' + relative)
            if not target.is_file():raise ValueError('Known existing diagnostic helper required')
            target.write_bytes(data)
        changed = run_regression(candidate, name)
        if (baseline['passed'] or baseline.get('failures', 0) < 1 or baseline.get('errors', 0)
                or baseline.get('skipped', 0) or baseline.get('network_attempts', 0)
                or not changed['passed'] or changed.get('skipped', 0) or changed.get('network_attempts', 0)
                or baseline['tests'] != changed['tests']):
            raise ValueError('Paired failing-before/passing-after regression proof required; experiment retained')
        branch = 'repair/verified-defect-' + fingerprint[:16]
        git(candidate, 'checkout', '-b', branch)
        git(candidate, 'add', '--', *patch, 'apps/workflow-api/tests/' + name)
        git(candidate, '-c', 'user.name=OptiBrain development', '-c', 'user.email=fixture@localhost',
            'commit', '-m', 'Fix verified diagnostic defect ' + fingerprint[:16])
        commit = git(candidate, 'rev-parse', 'HEAD')
        request = dict(repository_full_name=repository, head=branch, base='main', draft=True,
            title='Fix verified diagnostic defect ' + fingerprint[:16],
            body='Paired isolated regression fails before and passes after.\n\nNo production deployment, scope expansion, publishing or financial action.\n\nProof: ' + fingerprint)
        result = dict(state='PREPARED', input_fingerprint=fingerprint, source_sha=source_sha,
            verified_base_tree=identity['tree_sha'],
            candidate_checkout=str(candidate), branch=branch, commit=commit,
            candidate_tree=git(candidate, 'rev-parse', 'HEAD^{tree}'), baseline=baseline,
            candidate_validation=changed, regression_sha256=hashlib.sha256(regression_code).hexdigest(),
            patch_sha256={k: hashlib.sha256(v).hexdigest() for k, v in patch.items()},
            draft_pr_request=request, pushed=False, deployed=False,
            limitation='Reviewed tests only; Python network fence is not a hostile-code OS sandbox')
        scope.write(receipt_name, (json.dumps(result, sort_keys=True) + '\n').encode())
        return result
