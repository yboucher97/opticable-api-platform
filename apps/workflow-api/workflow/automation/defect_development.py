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
from .operational_recovery import DevelopmentScope, recovery_holds
from .action_evidence import envelope, stamp

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
    base_ref = identity.get('base_ref')
    if (not isinstance(base_ref, str) or not re.fullmatch(r'main|recovery/production-[0-9a-f]{7,40}-\d{8}', base_ref)
            or identity.get('base_sha') != source_sha):
        raise ValueError('Verified PR base branch must point at the exact source commit')
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
        request = dict(repository_full_name=repository, head=branch, base=base_ref, draft=True,
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


def prepare_recurring_defect(coordinator, incident_id, source_repo, patch, regression_code,
                             *, source_sha, github_read, now=None):
    """Connect existing incidents to the existing paired-proof branch preparer.

    Two distinct, fresh reproductions are required; repetition is not cause proof.
    The reviewed patch and test still pass the fixed diagnostic allowlist and
    paired regression before a branch/PR request exists. No new agent or scheduler.
    """
    now = now or datetime.now(timezone.utc)
    coordinator.scope.verify(now)
    aid = 'defect-workflow:' + digest([incident_id, source_sha])[:32]
    binding = digest([{k: hashlib.sha256(v).hexdigest() for k, v in patch.items()},
                      hashlib.sha256(regression_code).hexdigest()])
    with coordinator.scope.lock():
        if recovery_holds(coordinator.audit):
            return {'state': 'RECOVERY_HOLD', 'executed': False}
        incident = coordinator.audit.get(incident_id)
        if (not incident or incident['action_type'] != 'OPERATIONAL_INCIDENT_CREATED'
                or incident['after_state'].get('reason_code') != 'ISOLATED_REPRODUCTION_REQUIRED'):
            raise ValueError('Existing software-defect incident required')
        prior = coordinator.audit.get(aid)
        if prior:
            if prior['proposed_state']['input_binding'] != binding:
                return {'state': 'BINDING_CONFLICT', 'executed': False}
            if prior['status'] == 'SUCCEEDED':
                return {'state': 'ALREADY_PREPARED', 'executed': False, **prior['after_state']}
            if prior['status'] == 'FAILED':
                return {'state': 'REVIEW_REQUIRED', 'executed': False}
        else:
            with coordinator.audit.connect(readonly=True) as db:
                rows = db.execute("SELECT envelope_json FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='OPERATIONAL_DIAGNOSIS' AND json_extract(envelope_json,'$.proposed_state.diagnosis.incident_key')=? ORDER BY created_at DESC LIMIT 101",
                    (incident['after_state']['incident_key'],)).fetchall()
            values = [json.loads(r[0])['proposed_state']['observation'] for r in rows]
            values = [v for v in values if v['symptom'] == 'SOFTWARE_DEFECT' and stamp(v['observed_at'])
                      and 0 <= (now-stamp(v['observed_at'])).total_seconds() <= 86400]
            if (len(values) < 2 or len({v['evidence_sha256'] for v in values}) < 2
                    or (max(stamp(v['observed_at']) for v in values)-min(stamp(v['observed_at']) for v in values)).total_seconds() < 60):
                return {'state': 'MORE_EVIDENCE_REQUIRED', 'executed': False}
            plan = envelope(aid, 'NONPROD_VERIFIED_DEFECT_PREPARATION', {'type': 'CODE', 'identity': incident_id}, now,
                mutation=True, authority_class='EXPLICIT_DEVELOPMENT_SCOPE',
                automatic_rule='Recurring software incident plus reviewed paired regression; development only',
                before_state={'source_sha': source_sha}, proposed_state={'input_binding': binding},
                rollback_capability='REVERSIBLE_WITH_LIMITATIONS', rollback_target='isolated branch only',
                rollback_procedure='Retain proof and abandon candidate branch; never alter production',
                exact_versions={'environment': 'isolated-development', 'incident_id': incident_id})
            coordinator.audit.plan(plan, now)
            coordinator.audit.start(aid, now, authority_check=lambda: coordinator.scope.verify(now))
    # The existing preparer owns its own nonblocking lock, and reconciles an
    # already-written exact receipt after an interrupted outer workflow.
    try:
        prepared = prepare_defect(source_repo, coordinator.scope, patch, regression_code,
            source_sha=source_sha, github_read=github_read, now=now)
    except Exception as exc:
        coordinator.audit.finish(aid, now, provider_success=False,
            actual_after={'error_type': type(exc).__name__, 'production_effects': 0})
        coordinator.audit.event(incident_id, 'RECOVERY', 'DEFECT_PREPARATION_FAILED',
            {'workflow': aid, 'error_type': type(exc).__name__, 'escalation_route': 'existing-owner-operations'}, now)
        return {'state': 'REVIEW_REQUIRED', 'executed': False}
    result = {k: prepared[k] for k in ('branch', 'commit', 'candidate_tree', 'draft_pr_request')}
    coordinator.audit.finish(aid, now, provider_success=True, verified=True, actual_after=result)
    coordinator.audit.event(incident_id, 'RECOVERY', 'VERIFIED_DEFECT_PR_PREPARED',
        {'workflow': aid, 'branch': result['branch'], 'commit': result['commit'],
         'cause_evidence': 'PAIRED_FAILING_BEFORE_PASSING_AFTER', 'production_effects': 0}, now)
    return {'state': 'PREPARED', 'executed': True, **result}
