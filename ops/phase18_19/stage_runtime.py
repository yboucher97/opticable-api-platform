#!/usr/bin/python3
"""Manual, root-reviewed exact-release staging; never starts an automation timer.

Install a reviewed copy of this helper into a root-owned directory before use.
Root stages the validated venv separately. After the normal guarded deployment:
  stage_runtime.py --prepare EXACT_40_HEX_SHA
  stage_runtime.py --activate EXACT_40_HEX_SHA
Activation prints the two read-only checks for separate root review. Existing
ownership, state, counters, journals, suppression and remote claims are retained.
The distinct --stop internal/customer/both invokes the installed emergency stops.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import grp
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile
import urllib.request

PROD = Path('/opt/opticable-api-platform')
RELEASES = Path('/opt/optibrain-releases')
EVIDENCE = Path('/var/lib/optibrain/phase18-19')
INTERNAL = Path('/var/lib/optibrain/lifecycle')
CUSTOMER = Path('/var/lib/optibrain/customer-communications')
INTERNAL_POLICY = Path('/etc/optibrain/mutation-control.json')
CUSTOMER_POLICY = Path('/etc/optibrain/customer-communication-control.json')
SNAPSHOT = EVIDENCE/'policies-before-deploy.json'
VALIDATION = EVIDENCE/'release-validation.json'
PHASE19 = EVIDENCE/'phase19-operations-replay.json'
RECEIPT = Path('/var/lib/optibrain/releases/current.json')
SAFE = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
GIT = ['/usr/bin/git', '-c', 'safe.directory='+str(PROD), '-c', 'core.fsmonitor=false',
       '-c', 'core.hooksPath=/dev/null', '-C', str(PROD)]
ORIGINAL_SCOPES = frozenset({'crm.lead.intake', 'crm.internal.task', 'crm.lead.convert',
    'crm.account.create', 'crm.contact.create', 'crm.deal.prepare', 'crm.site.prepare',
    'crm.service.create', 'workdrive.folder.create', 'crm.installation.prepare', 'crm.link.create'})
INTERNAL_SCOPES = ORIGINAL_SCOPES | {'crm.service.activate'}
CUSTOMER_SCOPES = frozenset({'customer.quote.reminder', 'customer.appointment.confirmation',
                           'customer.appointment.reminder', 'customer.completion.message'})
INTERNAL_SOURCES = frozenset({'automation/lifecycle_control.py', 'automation/lifecycle.py',
    'automation/remote_effects.py', 'automation/mutation_control.py', 'automation/crm_write_boundary.py',
    'zoho_gateway.py', 'automation/real_internal.py', 'automation/phase9_form_receipts.py'})
CUSTOMER_SOURCES = frozenset({'automation/customer_send_control.py', 'automation/customer_delivery.py',
    'automation/customer_communications.py', 'automation/customer_runtime.py', 'automation/customer_finance_evidence.py',
    'automation/mutation_control.py', 'automation/lifecycle_control.py', 'automation/remote_effects.py', 'zoho_gateway.py'})
LAUNCHERS = {'internal': Path('/usr/local/lib/optibrain/lifecycle_runner.py'),
             'customer': Path('/usr/local/lib/optibrain/customer_runner.py')}
INSTALL = {str(LAUNCHERS['internal']): 'ops/phase16_17/lifecycle_runner.py',
           str(LAUNCHERS['customer']): 'ops/phase18_19/customer_runner.py'}
for _family in ('lifecycle-internal', 'customer-communications'):
    for _kind in ('service', 'timer'):
        _unit = 'opticable-'+_family+'.'+_kind
        INSTALL['/etc/systemd/system/'+_unit] = 'ops/phase15/systemd/'+_unit


def require(condition, reason):
    if not condition: raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, 'Authority timestamp needs an offset')
    return parsed


def trusted(path, maximum=8*1024*1024):
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                'Untrusted staging parent')
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o022 and info.st_size <= maximum, 'Untrusted staging file')
        return stream.read()


def load(path):
    value = json.loads(trusted(path))
    require(isinstance(value, dict), 'Staging evidence must be an object')
    return value


def atomic(path, value, *, mode=0o600, gid=0, immutable=False):
    path = Path(path)
    # A prepared root directory is required; never create arbitrary parents.
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                'Untrusted staging destination')
    raw = value if isinstance(value, bytes) else (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()
    if path.exists() or path.is_symlink():
        old = trusted(path)
        if immutable:
            require(old == raw, 'Immutable staging evidence already differs')
            return
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        os.fchmod(fd, mode); os.fchown(fd, 0, gid)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def command(args, *, binary=False):
    return subprocess.check_output(args, env=SAFE, stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=not binary, timeout=120)


def exact_head(sha):
    require(re.fullmatch(r'[0-9a-f]{40}', sha) is not None, 'Exact release SHA required')
    require(command([*GIT, 'rev-parse', 'HEAD']).strip() == sha, 'Production HEAD differs')
    require(not command([*GIT, 'diff', '--name-only']).strip()
            and not command([*GIT, 'diff', '--cached', '--name-only']).strip(), 'Production tracked source changed')


def closed():
    internal = load(INTERNAL_POLICY); customer = load(CUSTOMER_POLICY)
    require(internal.get('test_writes_enabled') is False and internal.get('real_canary_allowed') is False,
            'Legacy TEST/canary authority must be OFF')
    require(not internal.get('lifecycle', {}).get('enabled')
            and not internal.get('lifecycle', {}).get('real_scopes'), 'Internal authority must be closed')
    require(customer.get('external_enabled') is False and customer.get('test_enabled') is False,
            'Customer authority must be closed')
    require(not Path('/etc/optibrain/authorize-persistent-codex-development').exists(), 'Persistent worker must remain OFF')
    for path in (Path('/etc/opticable-workflow-api.env'), Path('/etc/optibrain/phase12-runner.env')):
        entries = dict(line.split('=', 1) for line in trusted(path).decode().splitlines()
                       if '=' in line and not line.startswith('#'))
        require(entries.get('OPTIBRAIN_BUSINESS_AUTO_WRITES', '0') == '0', 'Broad real writes must be OFF')
        require(entries.get('OPTIBRAIN_OUTBOUND_SENDS', 'off') == 'off', 'Legacy outbound sends must be OFF')


def idle_units():
    values = {}
    for family in ('opticable-lifecycle-internal', 'opticable-customer-communications'):
        for kind in ('timer', 'service'):
            unit = family+'.'+kind
            raw = command(['/usr/bin/systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'SubState',
                           '-p', 'UnitFileState', '-p', 'LoadState'])
            value = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
            require(value.get('ActiveState') == 'inactive' and value.get('SubState') == 'dead',
                    'Scoped unit is not idle')
            if kind == 'timer':
                require(value.get('UnitFileState') in ('disabled', 'masked')
                        or value.get('LoadState') == 'not-found', 'Scoped timer is still enabled')
            values[unit] = value
    return values


def venv_ready(root):
    venv = root/'venv'
    require(venv.is_dir() and not venv.is_symlink() and (venv/'bin/python').exists(),
            'Root must stage the validated target venv first')
    for path in (venv, *venv.rglob('*')):
        info = path.lstat()
        require(info.st_uid == 0 and (path.is_symlink() or not info.st_mode & 0o022), 'Untrusted target venv')
        if path.is_symlink():
            trusted(path.resolve(), 128*1024*1024) if path.resolve().is_file() else require(
                path.resolve().stat().st_uid == 0 and not path.resolve().stat().st_mode & 0o022,
                'Untrusted venv symlink target')


def archive_files(sha):
    raw = command([*GIT, 'archive', '--format=tar', sha], binary=True)
    require(len(raw) <= 256*1024*1024, 'Release archive exceeds staging bound')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for item in archive:
            name = PurePosixPath(item.name)
            require(not name.is_absolute() and '..' not in name.parts and str(name) not in ('', '.'),
                    'Release archive path is unsafe')
            require(item.isfile() or item.isdir(), 'Release archive links/devices are forbidden')
            if item.isfile():
                require(str(name) not in files, 'Duplicate archive path')
                files[str(name)] = archive.extractfile(item).read()
    return raw, files


def source_tree(root, files):
    source = root/'source'
    if source.exists() or source.is_symlink():
        require(source.is_dir() and not source.is_symlink(), 'Existing release source is unsafe')
        actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
        require(actual == set(files), 'Existing immutable source inventory differs')
        for name, raw in files.items():
            require(trusted(source/name, 256*1024*1024) == raw, 'Existing immutable source differs from Git')
        return source
    with tempfile.TemporaryDirectory(prefix='.source-', dir=root) as temporary:
        staging = Path(temporary)/'source'; staging.mkdir(mode=0o700)
        for name, raw in files.items():
            path = staging/name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(raw)
            os.chown(path, 0, 0); path.chmod(0o444)
        directories = [staging, *[p for p in staging.rglob('*') if p.is_dir()]]
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            os.chown(path, 0, 0); path.chmod(0o555)
        staging.rename(source)
    return source


def pinned_files(files):
    return {name: digest(raw) for name, raw in files.items()
            if name.endswith('.py') or re.fullmatch(r'requirements[^/]*\.txt', Path(name).name)}


def manifest_matches(sha):
    prepared = load(EVIDENCE/('runtime-prepared-'+sha+'.json'))
    require(prepared.get('sha') == sha, 'Exact preparation receipt required')
    source = RELEASES/sha/'source'
    for path, expected in prepared['manifest_sha256'].items():
        require(digest(trusted(Path(path))) == expected, 'Runner manifest changed')
    manifest = load(Path('/etc/optibrain/lifecycle-runtime.json'))
    require(manifest['sha'] == sha and manifest['source_root'] == str(source), 'Runner targets another release')
    actual = {str(p.relative_to(source)) for p in source.rglob('*.py')}
    require(actual == {name for name in manifest['files'] if name.endswith('.py')}, 'Unpinned Python source')
    for name, expected in manifest['files'].items():
        require(digest(trusted(source/name, 256*1024*1024)) == expected, 'Prepared runner source changed')
    for path, expected in prepared['installed_sha256'].items():
        require(digest(trusted(Path(path))) == expected, 'Installed reviewed helper/unit changed')
    venv_ready(RELEASES/sha)
    return source, prepared


def prepare(sha):
    exact_head(sha); closed(); units = idle_units()
    root = RELEASES/sha
    trusted(root/'venv/pyvenv.cfg'); venv_ready(root)
    raw, files = archive_files(sha)
    source = source_tree(root, files)
    manifest = {'sha': sha, 'source_root': str(source), 'files': pinned_files(files)}
    backups = EVIDENCE/('runtime-installed-before-'+sha)
    backups.mkdir(mode=0o700, exist_ok=True)
    installed = {}
    for destination, name in INSTALL.items():
        require(name in files, 'Reviewed helper/unit absent from exact release')
        path = Path(destination)
        if path.exists() or path.is_symlink():
            # Mask removal requires a separate deliberate recovery action.
            require(not path.is_symlink(), 'Unmask reviewed recovery unit explicitly before staging')
            atomic(backups/path.name, trusted(path), immutable=True)
        atomic(path, files[name], mode=0o755 if path.suffix == '.py' else 0o644)
        installed[str(path)] = digest(files[name])
    manifests = {}
    for path in (Path('/etc/optibrain/lifecycle-runtime.json'), Path('/etc/optibrain/customer-communications-runtime.json')):
        atomic(path, manifest); manifests[str(path)] = digest(trusted(path))
    command(['/usr/bin/systemctl', 'daemon-reload'])
    closed(); idle_units()
    receipt = {'schema': 1, 'state': 'PREPARED_TIMERS_OFF', 'sha': sha, 'at': datetime.now(timezone.utc).isoformat(),
        'source_root': str(source), 'archive_sha256': digest(raw), 'manifest_sha256': manifests,
        'installed_sha256': installed, 'source_files_pinned': len(manifest['files']), 'units_before': units,
        'timers_started': 0, 'provider_writes': 0, 'state_or_claims_reset': False}
    atomic(EVIDENCE/('runtime-prepared-'+sha+'.json'), receipt, immutable=True)
    return {'state': receipt['state'], 'sha': sha, 'timers_started': 0, 'source_files_pinned': len(manifest['files'])}


def activation_inputs(source, now):
    snapshot = load(SNAPSHOT)
    require(set(snapshot) == {'internal_policy', 'internal_activation', 'customer_policy'}, 'Reviewed before-deploy snapshot required')
    policy = snapshot['internal_policy']; activation = snapshot['internal_activation']; prior = policy['lifecycle']
    require(policy.get('schema') == 2 and policy.get('test_writes_enabled') is False
            and policy.get('real_canary_allowed') is False and policy.get('allowed_actions') == ['crm.task.create'],
            'Before-deploy safety policy differs')
    require(prior.get('enabled') is True and prior.get('test_scopes') == []
            and set(prior.get('real_scopes', [])) == ORIGINAL_SCOPES, 'Original eleven reviewed scopes required')
    require(activation.get('family') == 'REAL_LEAD_INTERNAL_AUTOMATION_V1'
            and activation.get('run') == prior.get('test_run') == 'real-internal-20261002-v1'
            and activation.get('activated_at') == prior.get('activated_at')
            and activation.get('approved_sources') == prior.get('approved_sources')
            and activation.get('scopes') == prior.get('real_scopes')
            and set(prior['approved_sources']) <= {'ai_website', 'opticable_website', 'zoho_form_fr'},
            'Original lineage activation differs')
    require(timestamp(prior['expires_at']) > now and timestamp(prior['activated_at']) < now,
            'Original internal authority expired or cutoff invalid')
    require(set(prior['source_hashes']) == INTERNAL_SOURCES, 'Original internal source inventory differs')
    current_activation = load(INTERNAL/'activation.json')
    require(current_activation == activation, 'Live original activation changed after snapshot')
    phase16 = load(INTERNAL/'phase16-checkpoint.json')
    require(phase16.get('phase16') == 'PASS' and phase16.get('safety_critical_failures') == 0
            and digest(trusted(INTERNAL/'phase16-checkpoint.json')) == prior['phase16_checkpoint_sha256'],
            'Original Phase16 checkpoint differs')
    phase18 = load(CUSTOMER/'phase18-checkpoint.json')
    require(phase18.get('phase18') == 'PASS' and phase18.get('safety_critical_failures') == 0
            and CUSTOMER_SCOPES <= set(phase18.get('passed_families', [])), 'Customer provider TEST gates incomplete')
    phase19 = load(PHASE19)
    require(phase19.get('phase19_test') == 'PASS'
            and phase19.get('scenario_results') == dict.fromkeys('ABCD', 'PASS')
            and phase19.get('replay_get_only') is True and phase19.get('new_verified_provider_effects') == 0
            and all(phase19.get(k) == 0 for k in ('financial_writes', 'customer_sends', 'payment_mutations',
                'duplicate_sites', 'duplicate_services', 'duplicate_folders', 'duplicate_installations', 'duplicate_tasks')),
            'Native Phase19 TEST/replay proof incomplete')
    validation = load(VALIDATION)
    require(validation.get('passed') is True and validation.get('tests', 0) >= 1108
            and all(validation.get(k) == 0 for k in ('failures', 'errors', 'skipped', 'blocked_network_attempts')),
            'Complete release regression did not pass')
    expected = {str(p.relative_to(source)): digest(trusted(p)) for p in (source/'apps/workflow-api/workflow').rglob('*.py')}
    require(validation.get('workflow_source_hashes') == expected, 'Full-gate workflow sources differ from exact release')
    release = load(RECEIPT)
    require(release.get('sha') == source.parent.name and release.get('state') == 'deployed'
            and release.get('api_version') == '1.14.0' and release.get('writers_enabled') is False
            and release.get('tests', {}).get('passed') is True, 'Guarded exact release receipt required')
    # Existing TEST send effects, family holds and counters remain intact.
    state = load(CUSTOMER/'state.json')
    require(state.get('schema') == 1 and isinstance(state.get('effects'), dict)
            and isinstance(state.get('holds'), dict), 'Existing customer send state required')
    for scope in CUSTOMER_SCOPES:
        require(sum(row.get('family') == scope and row.get('mode') == 'REAL_NEW'
                    for row in state['effects'].values()) <= 10, 'Existing real verification budget exceeded')
    return snapshot, phase18, phase19, validation, state


def activate(sha):
    exact_head(sha); closed(); idle_units()
    source, prepared = manifest_matches(sha)
    now = datetime.now(timezone.utc)
    snapshot, phase18, phase19, validation, state = activation_inputs(source, now)
    with urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=5) as response:
        health = json.load(response)
        require(response.status == 200 and health.get('status') == 'ok' and health.get('version') == '1.14.0',
                'Deployed API health/version differs')
    receipt_path = EVIDENCE/('runtime-activation-'+sha+'.json')
    require(not receipt_path.exists(), 'Existing activation must be reviewed, never overwritten')
    suppression = CUSTOMER/'suppression.json'
    if suppression.exists():
        value = load(suppression)
        require(isinstance(value.get('objects'), dict) and isinstance(value.get('recipients'), dict),
                'Existing suppression evidence invalid')
    else:
        atomic(suppression, {'objects': {}, 'recipients': {}}, immutable=True)
    internal = deepcopy(snapshot['internal_policy']); old = internal['lifecycle']
    activation = deepcopy(snapshot['internal_activation'])
    activation.update(release_sha=sha, scopes=sorted(INTERNAL_SCOPES))
    old.update(enabled=True, test_scopes=[], real_scopes=activation['scopes'],
               source_hashes={name: digest(trusted(source/'apps/workflow-api/workflow'/name)) for name in INTERNAL_SOURCES})
    customer = {'schema': 1, 'external_enabled': True, 'test_enabled': False,
        'test_run': snapshot['customer_policy']['test_run'], 'test_scopes': [], 'real_scopes': sorted(CUSTOMER_SCOPES),
        'activated_at': now.isoformat(), 'expires_at': (now+timedelta(days=30)).isoformat(),
        'source_hashes': {name: digest(trusted(source/'apps/workflow-api/workflow'/name)) for name in CUSTOMER_SOURCES},
        'phase18_checkpoint_sha256': digest(trusted(CUSTOMER/'phase18-checkpoint.json')),
        'per_family_limit': 10, 'per_cycle_limit': 4}
    # Stage the intended authority durably before committing enablement. Timers
    # remain stopped; no old action journal or business record is restored.
    receipt = {'schema': 1, 'state': 'ARMED_TIMERS_OFF_PENDING_DRY_RUN_REVIEW', 'sha': sha,
        'at': now.isoformat(), 'internal_family': activation['family'], 'internal_run': activation['run'],
        'original_eligible_cutoff': activation['activated_at'], 'internal_expires_at': old['expires_at'],
        'internal_scopes': activation['scopes'], 'customer_scopes': customer['real_scopes'],
        'customer_expires_at': customer['expires_at'], 'customer_verification_limit': 10, 'per_cycle_limit': 4,
        'evidence_sha256': {str(path): digest(trusted(path)) for path in (SNAPSHOT, VALIDATION, PHASE19,
            INTERNAL/'phase16-checkpoint.json', CUSTOMER/'phase18-checkpoint.json')},
        'customer_state_sha256_before': digest(trusted(CUSTOMER/'state.json')),
        'timers_started': 0, 'provider_writes': 0, 'state_or_claims_reset': False,
        'dry_run_commands': ['/usr/bin/python3 -I -B '+str(path)+' --dry-run' for path in LAUNCHERS.values()]}
    intent_path = EVIDENCE/('runtime-activation-intent-'+sha+'.json')
    atomic(intent_path, {**receipt, 'state': 'AUTHORIZATION_INTENT_TIMERS_OFF'}, immutable=True)
    try:
        atomic(INTERNAL/'activation.json', activation)
        atomic(INTERNAL_POLICY, internal, mode=0o640, gid=grp.getgrnam('opticable-workflow-api').gr_gid)
        atomic(CUSTOMER_POLICY, customer)
        require(digest(trusted(CUSTOMER/'state.json')) == receipt['customer_state_sha256_before'], 'Send state changed during activation')
        idle_units()
        atomic(receipt_path, receipt, immutable=True)
    except Exception:
        # A partial config transaction fails closed without restoring any state.
        denied = deepcopy(internal); denied['lifecycle']['enabled'] = False; denied['lifecycle']['real_scopes'] = []
        atomic(INTERNAL_POLICY, denied, mode=0o640, gid=grp.getgrnam('opticable-workflow-api').gr_gid)
        atomic(CUSTOMER_POLICY, {**customer, 'external_enabled': False, 'test_enabled': False})
        raise
    return {'state': receipt['state'], 'sha': sha, 'timers_started': 0,
            'dry_run_commands': receipt['dry_run_commands'], 'receipt': str(receipt_path)}


def stop(which):
    chosen = list(LAUNCHERS) if which == 'both' else [which]
    for family in chosen:
        trusted(LAUNCHERS[family])
        command(['/usr/bin/python3', '-I', '-B', str(LAUNCHERS[family]), '--stop'])
    return {'state': 'STOPPED', 'families': chosen, 'timers_started': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', metavar='EXACT_SHA')
    mode.add_argument('--activate', metavar='EXACT_SHA')
    mode.add_argument('--stop', choices=('internal', 'customer', 'both'))
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Manual root session required')
    trusted(Path(__file__).absolute())
    lock = os.open('/var/lock/opticable-api-platform-deploy.lock', os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        value = prepare(args.prepare) if args.prepare else activate(args.activate) if args.activate else stop(args.stop)
        print(json.dumps(value, sort_keys=True))
    finally: os.close(lock)


if __name__ == '__main__':
    try: main()
    except Exception as exc: raise SystemExit('Manual runtime staging refused: '+type(exc).__name__)
