"""Prepare a development branch/PR only after paired isolated regression proof.

No credentials, provider writes, push, merge, deployment, timer or public input.
The existing GitHub connector may publish the returned draft request under the
owner's separate development authority. Production/safety code is not eligible.
"""
from datetime import datetime, timezone
import ast
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
GENERATED_TEST_PREFIX = '''import unittest,datetime as dt,importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('v2_target',Path(__file__).resolve().parents[3]/'ops/connectivity_watch/check.py')
_watch=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_watch)
age_hours=_watch.age_hours
'''
PUBLIC_TEST_PREFIX = '''import unittest,datetime as dt,importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('v2_readiness',Path(__file__).resolve().parents[3]/'apps/workflow-api/workflow/automation/readiness.py')
_watch=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_watch)
def classify_public(value,now):
 try:return _watch.public_verification_signal(value,now)
 except (TypeError,AttributeError,ValueError):return {'state':'CRASHED','classification':'CRASHED'}
'''
GENERATION_TARGETS = {
    'future_timestamp':('ops/connectivity_watch/check.py','age_hours',GENERATED_TEST_PREFIX),
    'public_evidence_consistency':('apps/workflow-api/workflow/automation/readiness.py','public_verification_signal',PUBLIC_TEST_PREFIX),
}
REPOSITORY = 'yboucher97/opticable-api-platform'
SAFE_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
RUNNER = r'''
import sys,os,socket,unittest,json
from pathlib import Path
root=Path(sys.argv[1]);pattern=sys.argv[2]
scratch=sys.argv[3] if len(sys.argv)>3 else str(root)
os.environ.clear();os.environ.update(PATH='/usr/bin:/bin',LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',TMPDIR=scratch)
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


def run_regression(repo, pattern, *, hardened=False):
    """Bounded unprivileged child; reviewed tests, Python-level network fence."""
    with tempfile.TemporaryDirectory(prefix='optibrain-generated-test-') as scratch, tempfile.TemporaryFile() as output:
        def limits():
            _limits()
            if hardened:
                from .development_sandbox import restrict_child
                restrict_child(repo, scratch)
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', RUNNER, str(repo), pattern, scratch],
            cwd=scratch, env=SAFE_ENV, stdout=output, stderr=output,
            preexec_fn=limits, start_new_session=True)
        try:code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL);process.wait()
            return dict(passed=False, timeout=True, tests=0, failures=0, errors=1, skipped=0, network_attempts=0)
        output.seek(0, 2);size = output.tell();output.seek(max(0, size - 8192));tail = output.read().decode(errors='replace')
    try:result = json.loads(tail.splitlines()[-1])
    except (ValueError, IndexError):result = dict(passed=False, tests=0, failures=0, errors=1, skipped=0, network_attempts=0)
    result.update(exit_code=code, log_sha256=hashlib.sha256(tail.encode()).hexdigest(),
                  output_bytes=size, no_new_privileges=True,
                  network_isolation='Landlock+seccomp' if hardened else 'Python-level fence; no OS namespace claim')
    result['passed'] = result.get('passed') is True and code == 0
    return result


def prepare_defect(source_repo, scope, patch, regression_code, *, source_sha, github_read, repository=REPOSITORY, now=None,
                   generated=False):
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
    if (not isinstance(base_ref, str) or not re.fullmatch(r'main|recovery/production-[0-9a-f]{7,40}-\d{8}|feature/(?:operational-recovery|connection-watchdog)-\d{8}|release/production-integration-v2-\d{8}', base_ref)
            or identity.get('base_sha') != source_sha):
        raise ValueError('Verified PR base branch must point at the exact source commit')
    if not isinstance(patch, dict) or not 1 <= len(patch) <= 2 or not set(patch) <= ELIGIBLE:
        raise ValueError('Only approved diagnostic helpers are eligible for automatic development')
    if any(not isinstance(v, bytes) or len(v) > 128 * 1024 for v in patch.values()) or sum(map(len, patch.values())) > 256 * 1024:
        raise ValueError('Bounded exact patch bytes required')
    if not isinstance(regression_code, bytes) or not 1 <= len(regression_code) <= 16384:
        raise ValueError('Bounded reviewed regression code required')
    fingerprint_input = [source_sha, {k: hashlib.sha256(v).hexdigest() for k, v in patch.items()}, hashlib.sha256(regression_code).hexdigest()]
    if generated: fingerprint_input.append('generated-v2-Landlock-seccomp')
    fingerprint = digest(fingerprint_input)
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
        baseline = run_regression(before, name, hardened=generated)
        for relative, data in patch.items():
            target = scope.path(str((candidate / relative).relative_to(scope.root)))
            git(candidate, 'cat-file', '-e', source_sha + ':' + relative)
            if not target.is_file():raise ValueError('Known existing diagnostic helper required')
            target.write_bytes(data)
        changed = run_regression(candidate, name, hardened=generated)
        if (baseline['passed'] or baseline.get('failures', 0) < 1 or baseline.get('errors', 0)
                or baseline.get('skipped', 0) or baseline.get('network_attempts', 0)
                or not changed['passed'] or changed.get('skipped', 0) or changed.get('network_attempts', 0)
                or baseline['tests'] != changed['tests']):
            raise ValueError('Paired failing-before/passing-after regression proof required; experiment retained')
        retained = None
        if generated:
            # Existing utility tests are retained as an independent behavior guard.
            existing = source / 'ops/connectivity_watch/test_check.py'
            if existing.is_file():
                for repo in repos:
                    # Copy the unchanged trusted suite into discovery, never edit it.
                    (repo/'apps/workflow-api/tests/test_retained_diagnostic.py').write_bytes(existing.read_bytes())
                    (repo/'apps/workflow-api/tests/check.py').write_bytes((repo/'ops/connectivity_watch/check.py').read_bytes())
                retained_before = run_regression(before, 'test_retained_diagnostic.py', hardened=True)
                retained_after = run_regression(candidate, 'test_retained_diagnostic.py', hardened=True)
                for repo in repos:
                    (repo/'apps/workflow-api/tests/test_retained_diagnostic.py').unlink()
                    (repo/'apps/workflow-api/tests/check.py').unlink()
                if not retained_before['passed'] or not retained_after['passed'] or retained_after['tests'] != retained_before['tests']:
                    raise ValueError('Existing regression coverage must be preserved')
                retained = {'before': retained_before, 'after': retained_after}
            if 'apps/workflow-api/workflow/automation/readiness.py' in patch:
                diagnostic_before=run_regression(before,'test_issue98_readiness.py',hardened=True)
                diagnostic_after=run_regression(candidate,'test_issue98_readiness.py',hardened=True)
                if (not diagnostic_before['passed'] or not diagnostic_after['passed']
                        or diagnostic_before['tests']!=diagnostic_after['tests']):
                    raise ValueError('Existing readiness regressions must be preserved')
                retained={**(retained or {}),'readiness_before':diagnostic_before,'readiness_after':diagnostic_after}
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
            retained_validation=retained,
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


class DiagnosticCodingEnvironment:
    """Zero-cost registered source synthesis, invoked from existing development.

    The current approved coding session authors these reviewed transformations.
    The controller supplies evidence/source and requests a proposal, rather than
    requiring an input patch or regression. Unknown problems fail closed. No model
    key, paid call, scheduler or unrestricted tool-executing agent is introduced.
    """
    version = 'diagnostic-coding-v2.3'

    def propose(self, context):
        rule=context['diagnostic'].get('rule')
        if rule not in GENERATION_TARGETS:
            raise ValueError('No validated generation rule for this diagnosis')
        path,function,prefix=GENERATION_TARGETS[rule]
        if context.get('validated_recipe'):
            recipe = context['validated_recipe']
            return {'path':path,'function':function,
                    'replacement':recipe['replacement'],'regression':recipe['regression'],
                    'usage':{'cost_microusd':0,'tokens':1}}
        if rule=='public_evidence_consistency':
            replacement='''def public_verification_signal(observation, now):
    if not isinstance(observation, dict):
        return signal('Public verification','UNKNOWN','Public evidence is malformed',automatic_policy_change_authorized=False)
    age=age_seconds(observation.get('at'),now)
    if age is None or age>900:
        return signal('Public verification','UNKNOWN','Public-path evidence is absent or stale',automatic_policy_change_authorized=False)
    status=observation.get('http_status');origin=observation.get('origin_healthy')
    valid=type(status) is int and 100<=status<=599
    denied=valid and status in {401,403}
    failed=origin is False
    verified=valid and status==200 and observation.get('semantic_health_verified') is True and (origin is True or origin is None)
    return signal('Public verification','ACTION REQUIRED' if denied or failed else 'OK' if verified else 'UNKNOWN',
        'Independent origin-health evidence reports failure' if failed else
        'This public-path check was denied; provider cause and policy intent remain unproven' if denied else
        'Existing public semantic health evidence verified' if verified else 'Public semantic verification is incomplete',
        at=observation.get('at'),http_status=status if valid else None,origin_healthy=origin,
        classification='ORIGIN_HEALTH_FAILURE' if failed else 'EDGE_CHECK_DENIAL' if denied else 'VERIFIED_PUBLIC_PATH' if verified else 'INCOMPLETE_VERIFICATION',
        origin_outage_proven=failed,automatic_policy_change_authorized=False)
'''
            regression=prefix+'''class PublicEvidenceRegression(unittest.TestCase):
 def test_malformed_status_is_unknown(self):
  self.assertEqual(classify_public({'at':'2026-11-13T00:00:00Z','http_status':[]},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['state'],'UNKNOWN')
 def test_nonobject_is_unknown(self):
  self.assertEqual(classify_public([],dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['state'],'UNKNOWN')
 def test_conflicting_origin_is_not_verified(self):
  self.assertEqual(classify_public({'at':'2026-11-13T00:00:00Z','http_status':200,'origin_healthy':False,'semantic_health_verified':True},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['classification'],'ORIGIN_HEALTH_FAILURE')
 def test_denial_does_not_prove_origin_outage(self):
  self.assertFalse(classify_public({'at':'2026-11-13T00:00:00Z','http_status':403,'origin_healthy':True},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['origin_outage_proven'])
 def test_good_public_health_retained(self):
  self.assertEqual(classify_public({'at':'2026-11-13T00:00:00Z','http_status':200,'origin_healthy':True,'semantic_health_verified':True},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['state'],'OK')
 def test_security_authority_remains_false(self):
  self.assertFalse(classify_public({'at':'2026-11-13T00:00:00Z','http_status':403},dt.datetime(2026,11,13,tzinfo=dt.timezone.utc))['automatic_policy_change_authorized'])
'''
            return {'path':path,'function':function,'replacement':replacement,'regression':regression,
                    'usage':{'cost_microusd':0,'tokens':(len(replacement)+len(regression)+3)//4}}
        replacement = '''def age_hours(value, now):
    try:
        instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.utcoffset() is None or instant > now:
            return None
        return (now - instant).total_seconds() / 3600
    except (ValueError, AttributeError, TypeError):
        return None
'''
        regression = GENERATED_TEST_PREFIX + '''class TimestampRegression(unittest.TestCase):
 def test_future_is_unknown(self):
  self.assertIsNone(age_hours('2026-11-14T00:00:00+00:00',dt.datetime(2026,11,13,tzinfo=dt.timezone.utc)))
 def test_naive_is_unknown(self):
  self.assertIsNone(age_hours('2026-11-12T00:00:00',dt.datetime(2026,11,13,tzinfo=dt.timezone.utc)))
 def test_valid_age_retained(self):
  self.assertEqual(age_hours('2026-11-12T00:00:00+00:00',dt.datetime(2026,11,13,tzinfo=dt.timezone.utc)),24)
'''
        return {'path': 'ops/connectivity_watch/check.py', 'function': 'age_hours',
                'replacement': replacement, 'regression': regression,
                'usage': {'cost_microusd': 0, 'tokens': (len(replacement)+len(regression)+3)//4}}


def validate_generated_change(original, proposal):
    """Only the registered pure diagnostic function can change; guards survive."""
    choice=next((r for r in GENERATION_TARGETS.values() if r[:2]==(proposal.get('path'),proposal.get('function'))),None)
    if not choice:
        raise ValueError('Generated code cannot select unrelated or protected files')
    path,function,prefix=choice
    replacement = proposal.get('replacement', '')
    if not isinstance(replacement, str) or not 1 <= len(replacement.encode()) <= 4096:
        raise ValueError('Bounded generated function required')
    tree = ast.parse(original);new = ast.parse(replacement)
    target = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function), None)
    if (not target or len(new.body) != 1 or not isinstance(new.body[0], ast.FunctionDef)
            or new.body[0].name != target.name or ast.dump(new.body[0].args) != ast.dump(target.args)
            or new.body[0].decorator_list):
        raise ValueError('Exact existing diagnostic signature required')
    forbidden = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.With, ast.Lambda,
                 ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.Delete)
    locals_ = {n.id for n in ast.walk(new) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    names = locals_ | {a.arg for a in target.args.args} | {'dt','ValueError','AttributeError','TypeError'}
    attributes = {'datetime','fromisoformat','replace','utcoffset','total_seconds'}
    if function=='public_verification_signal':
        names|={'signal','age_seconds','isinstance','dict','type','int'};attributes={'get'}
    for n in ast.walk(new):
        if isinstance(n, forbidden) or isinstance(n, ast.Name) and n.id not in names:
            raise ValueError('Generated diagnostics must remain pure and scoped')
        if isinstance(n, ast.Attribute) and n.attr not in attributes:
            raise ValueError('Generated diagnostic access exceeds reviewed grammar')
        if isinstance(n, ast.Assign) and any(not isinstance(t, ast.Name) for t in n.targets):
            raise ValueError('Generated diagnostics cannot alter global objects')
        if function=='public_verification_signal' and isinstance(n,ast.Return):
            if (not isinstance(n.value,ast.Call) or not isinstance(n.value.func,ast.Name) or n.value.func.id!='signal'
                    or not any(k.arg=='automatic_policy_change_authorized' and isinstance(k.value,ast.Constant) and k.value.value is False for k in n.value.keywords)):
                raise ValueError('Generated classification cannot grant security-policy authority')
    regression = proposal.get('regression')
    if not isinstance(regression, str) or not 1 <= len(regression.encode()) <= 4096:
        raise ValueError('Bounded generated regression required')
    if not regression.startswith(prefix):
        raise ValueError('Trusted immutable regression loader required')
    tests = ast.parse(regression[len(prefix):]);assertions = 0
    for n in ast.walk(tests):
        if isinstance(n, ast.Import) and any(a.name not in {'unittest','datetime'} for a in n.names):
            raise ValueError('Generated regression import refused')
        if isinstance(n, ast.ImportFrom) and n.module != 'ops.connectivity_watch.check':
            raise ValueError('Generated regression import refused')
        if isinstance(n, ast.Attribute):
            if n.attr.startswith('assert'): assertions += 1
            elif n.attr not in {'TestCase','datetime','timezone','utc'}:
                raise ValueError('Generated regression access refused')
        if isinstance(n, ast.Name) and n.id.startswith('__'):
            raise ValueError('Generated regression reflection refused')
        if isinstance(n, (ast.Global,ast.Nonlocal,ast.With,ast.Lambda)):
            raise ValueError('Generated regression side effect refused')
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id != ('age_hours' if function=='age_hours' else 'classify_public'):
            raise ValueError('Generated regression call refused')
    if assertions < 3:
        raise ValueError('Positive and negative regression coverage required')
    lines = original.splitlines(keepends=True)
    changed = ''.join(lines[:target.lineno-1]) + replacement.rstrip()+'\n' + ''.join(lines[target.end_lineno:])
    # All imports, dispatch, retry limits, URLs and authorization handling remain
    # byte-for-byte untouched outside the single pure function.
    ast.parse(changed)
    return changed.encode(), regression.encode()


def develop_from_incident(coordinator, incident_id, source_repo, *, source_sha, github_read,
                          coding_environment=None, now=None):
    """Evidence -> generated source/test -> OS-isolated proof -> commit/PR request.

    Two attempts/day globally; one immutable attempt per incident/source/version.
    Failures and successful templates feed existing ActionEvidence learning.
    """
    now = now or datetime.now(timezone.utc)
    scope, audit = coordinator.scope, coordinator.audit
    scope.verify(now)
    environment = coding_environment or DiagnosticCodingEnvironment()
    if type(environment) is not DiagnosticCodingEnvironment:
        raise ValueError('Only the reviewed zero-cost coding environment is enabled')
    aid = 'self-improvement-v2:' + digest([incident_id,source_sha,environment.version])[:32]
    with scope.lock():
        if recovery_holds(audit): return {'state':'RECOVERY_HOLD','executed':False}
        prior = audit.get(aid)
        if prior:
            return {'state':'ALREADY_PREPARED' if prior['status']=='SUCCEEDED' else 'REVIEW_REQUIRED',
                    'executed':False, 'result':prior['after_state']}
        incident = audit.get(incident_id)
        if (not incident or incident['action_type'] != 'OPERATIONAL_INCIDENT_CREATED'
                or incident['after_state'].get('reason_code') != 'ISOLATED_REPRODUCTION_REQUIRED'):
            raise ValueError('Existing verified incident required')
        with audit.connect(readonly=True) as db:
            rows = db.execute("SELECT envelope_json FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='OPERATIONAL_DIAGNOSIS' AND json_extract(envelope_json,'$.proposed_state.diagnosis.incident_key')=? LIMIT 101",(incident['after_state']['incident_key'],)).fetchall()
            attempts = db.execute("SELECT created_at FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='SELF_IMPROVEMENT_V2'").fetchall()
            previous = db.execute("SELECT action_id FROM action_envelopes WHERE json_extract(envelope_json,'$.action_type')='SELF_IMPROVEMENT_V2' ORDER BY created_at DESC LIMIT 100").fetchall()
        observations = [json.loads(r[0])['proposed_state']['observation'] for r in rows]
        observations = [v for v in observations if stamp(v['observed_at']) and 0 <= (now-stamp(v['observed_at'])).total_seconds() <= 86400]
        if len({v['evidence_sha256'] for v in observations}) < 2:
            return {'state':'MORE_EVIDENCE_REQUIRED','executed':False}
        if sum(0 <= (now-stamp(r[0])).total_seconds() < 86400 for r in attempts) >= 2:
            return {'state':'BUDGET_EXHAUSTED','executed':False}
        plan = envelope(aid,'SELF_IMPROVEMENT_V2',{'type':'CODE','identity':incident_id},now,
            mutation=True,authority_class='EXPLICIT_DEVELOPMENT_SCOPE',
            automatic_rule='Registered diagnostic generation; zero cost; two attempts/day; isolated proof required',
            rollback_capability='REVERSIBLE_WITH_LIMITATIONS',rollback_target='isolated branch only',
            rollback_procedure='Retain evidence and abandon rejected branch; no production change',
            exact_versions={'environment':'isolated-development','source_sha':source_sha},
            before_state={'source_sha':source_sha},proposed_state={'generator':environment.version,'cost_cap_microusd':0})
        audit.plan(plan,now);audit.start(aid,now,authority_check=lambda:scope.verify(now))
    try:
        source = Path(source_repo)
        DevelopmentScope(source)
        if git(source,'rev-parse','HEAD') != source_sha or git(source,'status','--porcelain'):
            raise ValueError('Exact clean baseline required before generation')
        diagnostic=observations[-1].get('diagnostic',{})
        if diagnostic.get('rule') not in GENERATION_TARGETS:raise ValueError('No registered bounded diagnostic rule')
        source_path,function,_=GENERATION_TARGETS[diagnostic['rule']]
        original = subprocess.check_output(['git','-C',str(source),'show',source_sha+':'+source_path],env=SAFE_ENV,timeout=10).decode()
        if len(original.encode()) > 32768: raise ValueError('Source context exceeds budget')
        target = next(n for n in ast.parse(original).body if isinstance(n,ast.FunctionDef) and n.name==function)
        function_hash = hashlib.sha256(ast.get_source_segment(original,target).encode()).hexdigest()
        learned = None;learned_ref = None
        for row in previous:
            state = audit.get(row[0]);saved = state.get('after_state') or {}
            if (state['status']=='SUCCEEDED' and saved.get('recipe',{}).get('source_function_sha256')==function_hash
                    and saved['recipe'].get('rule')==diagnostic['rule']):
                audit.verify_integrity(row[0]);learned=saved['recipe'];learned_ref=row[0];break
        context = {'source':original,'source_sha':source_sha,'diagnostic':observations[-1].get('diagnostic',{}),
                   'observations':observations[-4:], 'validated_recipe':learned}
        proposal = environment.propose(context)
        if proposal.get('usage',{}).get('cost_microusd') != 0 or not 0 < proposal['usage']['tokens'] <= 4000:
            raise ValueError('Generation resource or cost budget exceeded')
        data, test = validate_generated_change(original,proposal)
        result = prepare_defect(source,scope,{source_path:data},test,
            source_sha=source_sha,github_read=github_read,now=now,generated=True)
        if result['candidate_validation']['network_isolation'] != 'Landlock+seccomp':
            raise ValueError('Generated code isolation not verified')
        saved = {k:result[k] for k in ('branch','commit','candidate_tree','candidate_checkout','draft_pr_request')}
        saved.update(generator=environment.version,reused_validated_repair=learned_ref,usage=proposal['usage'],
            recipe={'replacement':proposal['replacement'],'regression':proposal['regression'],
                    'source_function_sha256':function_hash,'rule':context['diagnostic']['rule']})
        audit.finish(aid,now,provider_success=True,verified=True,actual_after=saved)
        audit.event(aid,'RECOVERY','GENERATED_REPAIR_VERIFIED',
            {'symptom':context['diagnostic'],'source_sha':source_sha,'tests':result['candidate_validation'],
             'retained_tests':result['retained_validation'],'outcome':'VERIFIED_DEVELOPMENT_ONLY',
             'cause_evidence':'PAIRED_BASELINE_REGRESSION','business_effects':0,'reuse_eligible':False},now)
        return {'state':'PREPARED','executed':True,**saved}
    except Exception as exc:
        audit.finish(aid,now,provider_success=False,actual_after={'error_type':type(exc).__name__})
        audit.event(aid,'RECOVERY','GENERATED_REPAIR_REJECTED',
            {'error_type':type(exc).__name__,'outcome':'REJECTED','business_effects':0,'owner_review':True},now)
        return {'state':'REVIEW_REQUIRED','executed':False,'error_type':type(exc).__name__}
