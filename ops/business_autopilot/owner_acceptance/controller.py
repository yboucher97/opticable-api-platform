"""One foreground owner test, with bounded GETs and independent restoration.

No application, scheduler, daemon, database, service-control or generic action
framework. Network credentials stay in memory/stdin, never argv or audit output.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import fcntl
import importlib.util
import json
import os
import queue
import re
import signal
import stat
import subprocess
import threading
import time


class Failure(RuntimeError):
    def __init__(self, code, *, transient=False, status=None, retry_after=None):
        super().__init__(code)
        self.code, self.transient = code, transient
        self.status, self.retry_after = status, retry_after


class Clock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


def protected(path, owner_uid=0):
    path = Path(path)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != owner_uid or st.st_mode & 0o022 or st.st_nlink != 1:
        raise Failure('PROTECTED_REGULAR_FILE_REQUIRED')
    return path.read_bytes()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class Journal:
    def __init__(self, root, clock=Clock(), owner_uid=0, log_name='execution.jsonl'):
        self.root, self.clock, self.lock = Path(root), clock, threading.RLock()
        self.log_name = log_name
        self.path = self.root / 'ledger.json'
        self.data = json.loads(protected(self.path, owner_uid)) if self.path.exists() else {'mutations': {}}

    def event(self, name, **fields):
        value = {'at': datetime.now(timezone.utc).isoformat(),
                 'monotonic': self.clock.monotonic(), 'state': name, **fields}
        # All callers pass classifications/paths/status/timing, never HTTP
        # headers, provider bodies, cookie values or raw exception messages.
        with self.lock:
            fd = os.open(self.root / self.log_name, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(canonical(value) + b'\n'); out.flush(); os.fsync(out.fileno())
        if name in ('OWNER_TEST_OPEN', 'COOLDOWN_BEGIN', 'TEST_ABORT', 'RESTORE_BEGIN',
                    'BINDING_ON_VERIFIED', 'ORIGINAL_CONFIGURATION_VERIFIED',
                    'RESTORATION_VERIFIED', 'EMERGENCY_RESTORATION_UNVERIFIED'):
            print(json.dumps(value, sort_keys=True), flush=True)

    def flush(self):
        temp = self.path.with_name('ledger.pending-' + str(os.getpid()) + '-' + str(time.monotonic_ns()))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(canonical(self.data) + b'\n'); out.flush(); os.fsync(out.fileno())
        os.replace(temp, self.path)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def intent(self, tag, method, key, *, recovery_retry=False):
        with self.lock:
            previous = self.data['mutations'].get(tag)
            if previous and (previous['method'] != method or previous['key'] != key):
                raise Failure('MUTATION_LEDGER_IDENTITY_MISMATCH')
            if previous and (not recovery_retry or method != 'PUT' or previous.get('ack')
                             or previous['attempts'] >= 2):
                raise Failure('DUPLICATE_OR_AMBIGUOUS_MUTATION')
            self.data['mutations'][tag] = {'method': method, 'key': key,
                'attempts': 1 if previous is None else previous['attempts'] + 1, 'ack': False}
            self.flush()
            self.event('MUTATION_INTENT', tag=tag, method=method, body_name=key,
                       attempt=self.data['mutations'][tag]['attempts'])

    def ack(self, tag, status, *, reconciled=False):
        with self.lock:
            self.data['mutations'][tag].update(ack=True, status=status, reconciled=reconciled)
            self.flush(); self.event('MUTATION_ACK', tag=tag, http_status=status, reconciled=reconciled)


@contextmanager
def exclusive(path, owner_uid=0):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if st.st_uid != owner_uid or not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_nlink != 1:
            raise Failure('UNSAFE_EXECUTION_LOCK')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise Failure('ANOTHER_OWNER_TEST_IS_RUNNING') from None
        yield
    finally: os.close(fd)


class CurlTransport:
    """Existing system curl supplies a genuine per-transfer wall-clock bound."""
    def __init__(self, token, run=subprocess.run):
        if not re.fullmatch(r'[A-Za-z0-9._-]+', token): raise Failure('INVALID_PROVIDER_CREDENTIAL_FORMAT')
        self.token, self.run = token, run

    def request(self, method, path, body, timeout):
        def escape(value): return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
        config = 'header = "Authorization: Bearer ' + self.token + '"\nheader = "Content-Type: application/json"\n'
        if body is not None: config += 'data-binary = "' + escape(canonical(body).decode()) + '"\n'
        args = ['/usr/bin/curl', '--disable', '--config', '-', '--silent', '--show-error',
                '--proto', '=https', '--max-redirs', '0', '--retry', '0',
                '--connect-timeout', str(min(3, timeout)), '--max-time', str(timeout),
                '--max-filesize', '2097152', '--request', method,
                '--url', 'https://api.cloudflare.com/client/v4' + path,
                '--write-out', '\nOPTIBRAIN_META:%{http_code}|%header{retry-after}|%{time_total}']
        env = {k: v for k, v in os.environ.items() if k in
               ('PATH', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY',
                'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy')}
        try: result = self.run(args, input=config, capture_output=True, text=True, timeout=timeout + .5, env=env)
        except subprocess.TimeoutExpired: raise Failure('TRANSFER_PROCESS_TIMEOUT', transient=True) from None
        if result.returncode:
            raise Failure('CURL_EXIT_' + str(result.returncode), transient=result.returncode in (5, 6, 7, 18, 28, 52, 55, 56))
        try:
            raw, footer = result.stdout.rsplit('\nOPTIBRAIN_META:', 1)
            code, retry_after, _ = footer.strip().split('|'); status = int(code)
        except (ValueError, AttributeError): raise Failure('INVALID_TRANSFER_METADATA') from None
        if len(raw.encode()) > 2097152: raise Failure('RESPONSE_TOO_LARGE')
        if status != (202 if method == 'POST' else 200):
            delay = None
            if retry_after:
                if not re.fullmatch(r'\d{1,6}', retry_after): raise Failure('INVALID_RETRY_AFTER', status=status)
                delay = int(retry_after)
            raise Failure('HTTP_' + str(status), transient=status in (408, 429, 500, 502, 503, 504),
                          status=status, retry_after=delay)
        try: value = json.loads(raw)
        except (ValueError, UnicodeError): raise Failure('INVALID_PROVIDER_JSON') from None
        if value.get('success') is not True: raise Failure('PROVIDER_SUCCESS_NOT_ACKNOWLEDGED', status=status)
        return status, value.get('result')


class Provider:
    def __init__(self, package, transport, journal, clock=Clock(), *, writes=False):
        self.p, self.transport, self.journal, self.clock, self.writes = package, transport, journal, clock, writes
        self.deadline, self.cancel = float('inf'), None

    def allowed(self, method, path, key):
        paths = self.p['allowed_paths']
        if method == 'GET' and key is None and path in self.p['allowed_get_paths']: return
        if not self.writes: raise Failure('READ_ONLY_PROVIDER')
        if method == 'PUT' and ((path == paths['app'] and key in ('app_test', 'app_restore')) or
                                (path == paths['policy'] and key in ('policy_short', 'policy_restore'))): return
        if method == 'POST' and path == paths['revoke'] and key is None: return
        raise Failure('PROVIDER_OPERATION_NOT_ALLOWLISTED')

    @contextmanager
    def limit(self, deadline, cancel=None):
        old = self.deadline, self.cancel; self.deadline, self.cancel = deadline, cancel
        try: yield
        finally: self.deadline, self.cancel = old

    def call(self, method, path, key=None, tag=None):
        self.allowed(method, path, key)
        attempts = 2 if method == 'GET' else 1
        body = self.p['exact_bodies'][key] if key else None
        for attempt in range(attempts):
            if self.cancel and self.cancel.is_set(): raise Failure('READ_CANCELLED')
            left = self.deadline - self.clock.monotonic()
            if left <= 1: raise Failure('REQUEST_BUDGET_EXHAUSTED')
            started = self.clock.monotonic()
            try:
                status, result = self.transport.request(method, path, body, min(8, left - .75))
                if self.clock.monotonic() >= self.deadline: raise Failure('REQUEST_BUDGET_EXHAUSTED')
                if self.cancel and self.cancel.is_set(): raise Failure('READ_CANCELLED')
                self.journal.event('REQUEST_SUCCESS', method=method, path=path, http_status=status,
                                   attempt=attempt + 1, seconds=round(self.clock.monotonic() - started, 4))
                return result, status
            except Failure as error:
                self.journal.event('REQUEST_FAILED', method=method, path=path, classification=error.code,
                                   http_status=error.status, attempt=attempt + 1,
                                   seconds=round(self.clock.monotonic() - started, 4))
                if method != 'GET' or not error.transient or attempt + 1 == attempts: raise
                delay = max(1, error.retry_after or 0)
                if self.clock.monotonic() + delay + .5 >= self.deadline:
                    raise Failure('RETRY_AFTER_EXCEEDS_READ_BUDGET') from None
                self.journal.event('GET_RETRY_BACKOFF', path=path, seconds=delay)
                if self.cancel and self.cancel.wait(delay): raise Failure('READ_CANCELLED')
                if not self.cancel: self.clock.sleep(delay)

    def get(self, path): return self.call('GET', path)[0]

    def state(self):
        app = self.get(self.p['allowed_paths']['app'])
        policies = self.get(self.p['allowed_paths']['app'] + '/policies')
        if len(policies) != 1 or policies[0]['id'] != self.p['policy_id']: raise Failure('OWNER_POLICY_SET_CHANGED')
        return app, policies[0]


class ReadWorker:
    """Bounded read-only workers; foreground restoration never joins them.

    Optional local metrics cannot starve required security/configuration reads.
    Neither worker may submit a provider mutation.
    """
    def __init__(self, verify, optional, journal, clock=Clock(), interval=60):
        self.verify, self.optional, self.journal, self.clock, self.interval = verify, optional, journal, clock, interval
        self.cancel, self.results = threading.Event(), queue.Queue()

    def start(self):
        def read():
            while not self.cancel.is_set():
                try:
                    self.verify(self.cancel)
                    if self.cancel.is_set(): return
                    self.results.put(('verified', self.clock.monotonic()))
                except Exception as error:
                    if not self.cancel.is_set(): self.results.put(('failed', getattr(error, 'code', type(error).__name__)))
                    return
                if self.cancel.wait(self.interval): return
        def optional_read():
            while not self.cancel.is_set():
                try: self.optional()
                except Exception as error:
                    if not self.cancel.is_set():
                        self.journal.event('OPTIONAL_MONITOR_FAILED', classification=getattr(error, 'code', type(error).__name__))
                if self.cancel.wait(15): return
        self.thread = threading.Thread(target=read, name='bounded-owner-read', daemon=True)
        self.thread.start()
        self.optional_thread = threading.Thread(target=optional_read, name='optional-local-metrics', daemon=True)
        self.optional_thread.start()

    def stop(self): self.cancel.set()


class Controller:
    def __init__(self, package, model, provider, journal, clock=Clock(), stopped=None):
        self.p, self.m, self.c, self.j, self.clock = package, model, provider, journal, clock
        self.stopped = stopped or threading.Event()
        self.started = self.j.data.get('started_monotonic')

    def equal(self, app, policy, stage):
        try: self.m.assert_state(app, policy, (self.p['semantic_stage_readbacks'][stage]['app'],
                                              self.p['semantic_stage_readbacks'][stage]['policy']))
        except ValueError: raise Failure('CONFIGURATION_DRIFT') from None

    def known(self, app, policy):
        for stage in self.p['semantic_stage_readbacks']:
            try: self.equal(app, policy, stage); return stage
            except Failure: pass
        raise Failure('UNKNOWN_CONFIGURATION_REFUSE_OVERWRITE')

    def state(self, deadline):
        with self.c.limit(deadline): return self.c.state()

    def mutate(self, tag, key, deadline, *, restore=False):
        method = 'POST' if key is None else 'PUT'
        path = self.p['allowed_paths']['revoke' if key is None else 'app' if key.startswith('app_') else 'policy']
        previous = self.j.data['mutations'].get(tag)
        # Only the recovery path may reissue an unacknowledged, idempotent
        # RESTORE PUT, after a fresh GET proved the reviewed state still needs it.
        retry = bool(restore and previous and not previous['ack'] and method == 'PUT')
        self.j.intent(tag, method, key, recovery_retry=retry)
        with self.c.limit(deadline): _, status = self.c.call(method, path, key, tag)
        self.j.ack(tag, status)

    def restore(self):
        self.j.event('RESTORE_BEGIN')
        same_boot = self.j.data.get('boot_id') in (None, Path('/proc/sys/kernel/random/boot_id').read_text().strip())
        hard = self.started + 1500 if self.started is not None and same_boot else None
        # Recovery after host loss must still attempt protection, even when the
        # original bound can no longer be proven. Never report that as on-time.
        if hard is None or hard <= self.clock.monotonic():
            self.j.event('RECOVERY_TIME_BOUND_UNVERIFIABLE_OR_MISSED')
            deadline = self.clock.monotonic() + 110
        else: deadline = min(self.clock.monotonic() + 110, hard - 1)
        try:
            app, policy = self.state(deadline); self.known(app, policy)
            for tag, key, needed in [('restore-app', 'app_restore', app['enable_binding_cookie'] is not True or app['session_duration'] != '1h'),
                                     ('restore-policy', 'policy_restore', policy['session_duration'] != '1h')]:
                previous = self.j.data['mutations'].get(tag)
                if not needed:
                    if previous and not previous['ack']: self.j.ack(tag, None, reconciled=True)
                else:
                    if previous and previous['ack']: raise Failure('RESTORED_STATE_REVERSED_AFTER_ACK')
                    try: self.mutate(tag, key, deadline, restore=True)
                    except Failure:
                        # Do not retransmit a write because its acknowledgement
                        # was lost. GET current state; recover only from known states.
                        app, policy = self.state(deadline); self.known(app, policy)
                        desired = (app['enable_binding_cookie'] is True and app['session_duration'] == '1h') if key == 'app_restore' else policy['session_duration'] == '1h'
                        if not desired: raise
                        self.j.ack(tag, None, reconciled=True)
                app, policy = self.state(deadline); self.known(app, policy)
                if key == 'app_restore':
                    if app['enable_binding_cookie'] is not True or app['session_duration'] != '1h': raise Failure('BINDING_ON_UNVERIFIED')
                    self.j.event('BINDING_ON_VERIFIED')
            self.equal(app, policy, 'original'); self.j.event('ORIGINAL_CONFIGURATION_VERIFIED')
            if self.started is not None:
                previous = self.j.data['mutations'].get('final-revoke')
                if previous and not previous['ack']: raise Failure('FINAL_REVOCATION_ACK_UNKNOWN_NO_REPLAY')
                if not previous: self.mutate('final-revoke', None, deadline)
            app, policy = self.state(deadline); self.equal(app, policy, 'original')
            self.j.data['restored'] = True; self.j.flush()
            self.j.event('RESTORATION_VERIFIED', within_hard_deadline=None if hard is None else self.clock.monotonic() < hard)
        except Exception as error:
            self.j.event('EMERGENCY_RESTORATION_UNVERIFIED', classification=getattr(error, 'code', type(error).__name__))
            raise

    def supervise(self, worker):
        # Required state was independently verified immediately after opening.
        last_verified = self.clock.monotonic()
        target = self.started + 1380 - 1  # one-second dispatch margin, by minute23
        worker.start()
        try:
            while self.clock.monotonic() < target:
                if self.stopped.is_set() or (self.j.root / 'owner-stop.json').exists(): return 'OWNER_OR_OPERATOR_STOP'
                try:
                    while True:
                        kind, value = worker.results.get_nowait()
                        if kind == 'failed': raise Failure('REQUIRED_READ_UNVERIFIED_' + value)
                        last_verified = value; self.j.event('REQUIRED_STATE_VERIFIED')
                except queue.Empty: pass
                if self.clock.monotonic() - last_verified >= 90: raise Failure('REQUIRED_VERIFICATION_STALE')
                self.clock.sleep(min(.2, max(0, target - self.clock.monotonic())))
            return 'RESTORATION_DEADLINE'
        finally: worker.stop()  # no join on an optional/blocked network operation

    def execute(self, guards, worker_factory):
        if self.j.data.get('used'): raise Failure('TEST_ALREADY_CONSUMED')
        app, policy = self.state(self.clock.monotonic() + 40); self.equal(app, policy, 'original'); guards()
        self.j.data.update(used=True, phase='preparing'); self.j.flush()
        outcome = 'NOT_OPENED'
        try:
            self.mutate('shorten-policy', 'policy_short', self.clock.monotonic() + 20)
            self.equal(*self.state(self.clock.monotonic() + 40), 'short_policy_binding_on')
            self.mutate('initial-revoke', None, self.clock.monotonic() + 20)
            until = self.clock.monotonic() + 60; self.j.event('COOLDOWN_BEGIN', minimum_seconds=60)
            while self.clock.monotonic() < until:
                if self.stopped.is_set(): raise Failure('STOPPED_BEFORE_OPEN')
                self.clock.sleep(min(.2, max(0, until - self.clock.monotonic())))
            self.equal(*self.state(self.clock.monotonic() + 40), 'short_policy_binding_on'); guards()
            self.started = self.clock.monotonic()
            self.j.data.update(started_monotonic=self.started,
                started_at_utc=datetime.now(timezone.utc).isoformat(),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(), phase='opening')
            self.j.flush(); self.j.event('BINDING_OFF_INTENT', restore_by_seconds=1380, hard_seconds=1500)
            self.mutate('disable-app', 'app_test', self.started + 40)
            self.equal(*self.state(self.started + 80), 'test_binding_off')
            guards()
            self.j.data['phase'] = 'open'; self.j.flush()
            self.j.event('OWNER_TEST_OPEN', restore_target_monotonic=self.started + 1380, hard_deadline_monotonic=self.started + 1500)
            outcome = self.supervise(worker_factory())
        except Exception as error:
            outcome = getattr(error, 'code', type(error).__name__)
            self.j.event('TEST_ABORT', classification=outcome)
            raise
        finally:
            self.j.data['outcome'] = outcome; self.j.flush()
            self.restore()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def validate_package(package_path, expected):
    root = Path(package_path).parent
    st = root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise Failure('PRIVATE_ROOT_OWNED_CONTROLLER_DIRECTORY_REQUIRED')
    raw = protected(package_path)
    if sha256(raw).hexdigest() != expected: raise Failure('EXACT_PACKAGE_REQUIRED')
    p = json.loads(raw)
    if p['maximum_incremental_cost_cad'] != 0: raise Failure('ZERO_INCREMENTAL_COST_REQUIRED')
    if set(p['controller_files_sha256']) != {'controller.py', 'binding_test_model.py'}:
        raise Failure('UNREVIEWED_CONTROLLER_MEMBERS')
    for name, want in p['controller_files_sha256'].items():
        if sha256(protected(root / name)).hexdigest() != want: raise Failure('CONTROLLER_SOURCE_DRIFT')
    model = load_module('reviewed_owner_test_model', root / 'binding_test_model.py')
    for key, value in p['exact_bodies'].items():
        if model.checksum(value) != p['canonical_json_body_sha256'][key]: raise Failure('BODY_HASH_MISMATCH')
    app = '/accounts/81d07d311d1b51e5e04b451d1f254850/access/apps/' + model.APP
    required = {'app': app, 'policy': app + '/policies/' + model.POLICY, 'revoke': app + '/revoke_tokens'}
    if p['allowed_paths'] != required: raise Failure('UNAPPROVED_MUTATION_ENDPOINT')
    expected_get = {app, app + '/policies',
        '/zones/ea7b4f245feb0a98fb5534e73e761970/settings/google-tag-gateway/config',
        '/zones/ea7b4f245feb0a98fb5534e73e761970/dns_records?name=app.opticable.ca',
        '/accounts/81d07d311d1b51e5e04b451d1f254850/access/apps'}
    if set(p['allowed_get_paths']) != expected_get: raise Failure('UNAPPROVED_READ_ENDPOINT')
    if p['maximum_binding_off_seconds'] != 1500 or p['restore_start_target_seconds'] != 1380:
        raise Failure('UNAPPROVED_TIME_BOUND')
    return p, model


def authorize(receipt, expected, runner_path, *, recovery=False, now=None):
    now = now or datetime.now(timezone.utc)
    if (receipt.get('state') != 'APPROVED' or receipt.get('package_sha256') != expected or
        receipt.get('owner') != 'info@opticable.ca' or receipt.get('ready') is not True or
        receipt.get('maximum_incremental_cost_cad') != 0 or not receipt.get('owner_approval_text_sha256') or
        receipt.get('executor_sha256') != sha256(protected(runner_path)).hexdigest()):
        raise Failure('NEW_EXACT_APPROVAL_AND_READY_REQUIRED')
    try: ready_at = datetime.fromisoformat(receipt['READY_recorded_at'])
    except (ValueError, KeyError, TypeError): raise Failure('NEW_READY_TIMESTAMP_REQUIRED') from None
    if ready_at.tzinfo is None: raise Failure('NEW_READY_TIMESTAMP_REQUIRED')
    age = (now - ready_at).total_seconds()
    if age < 0 or (not recovery and age > 600): raise Failure('NEW_LIVE_READY_EXPIRED')


def main(package_path, expected, runner_path):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true'); mode.add_argument('--recover', action='store_true')
    parser.add_argument('--receipt', type=Path); args = parser.parse_args()
    if os.geteuid() != 0 or os.uname().nodename != 'vps-f8e9b20e': raise Failure('AUTHORITATIVE_NEW_VPS_ROOT_REQUIRED')
    p, model = validate_package(package_path, expected); root = Path(package_path).parent
    if args.execute or args.recover:
        if not args.receipt: raise Failure('NEW_APPROVAL_RECEIPT_REQUIRED')
        authorize(json.loads(protected(args.receipt)), expected, runner_path, recovery=args.recover)
    # Reuse the existing immutable environment checks, never C authorization or
    # C persistence/output paths. The legacy guard is imported only after hashing.
    guard_path = Path(p['legacy_guard_path'])
    if sha256(protected(guard_path)).hexdigest() != p['legacy_guard_sha256']: raise Failure('ENVIRONMENT_GUARD_DRIFT')
    guard = load_module('existing_owner_environment_guard', guard_path)
    api_pid = subprocess.check_output(['systemctl', 'show', 'opticable-workflow-api.service', '-p', 'MainPID', '--value'], text=True).strip()
    env = dict(x.split('=', 1) for x in Path('/proc', api_pid, 'environ').read_text().split('\0') if '=' in x)
    transport = CurlTransport(env['CLOUDFLARE_API_TOKEN'])
    clock = Clock()
    journal = Journal(root, clock, log_name='execution.jsonl' if args.execute or args.recover else 'preflight-events.jsonl')
    provider = Provider(p, transport, journal, clock, writes=args.execute or args.recover)
    class GuardAdapter:
        def call(self, method, path):
            if method != 'GET': raise Failure('GUARD_IS_READ_ONLY')
            return provider.get(path)
    def local_check():
        receipt = Path('/etc/optibrain/command-center-rollout.json')
        if sha256(protected(receipt)).hexdigest() != p['requires_installed_receipt_sha256']:
            raise Failure('INSTALLED_RECEIPT_DRIFT')
        pid = subprocess.check_output(['systemctl', 'show', 'optibrain-command-center.service', '-p', 'MainPID', '--value'], text=True, timeout=3).strip()
        if Path('/proc', pid, 'attr/current').read_text().strip() != 'optibrain-command-center-v1 (enforce)':
            raise Failure('APPARMOR_NOT_ENFORCED')
        for path, want in p['immutable_guard_snapshots']['local_file_sha256'].items():
            if sha256(protected(path)).hexdigest() != want: raise Failure('LOCAL_SECURITY_CONFIGURATION_DRIFT')
    def guards():
        local_check()
        with provider.limit(clock.monotonic() + 60): guard.guards(p, model, GuardAdapter())
        verifier = load_module('immutable_runtime_verifier', Path('/usr/local/share/optibrain-command-center-v1/ops/business_autopilot/serve_command_center.py'))
        if verifier.verify_source('/usr/local/share/optibrain-command-center-v1', p['requires_installed_manifest_sha256']) != 245:
            raise Failure('IMMUTABLE_RUNTIME_MEMBERS_CHANGED')
    def core(label):
        output = root / ('preservation-' + label + '-' + str(time.monotonic_ns()) + '.json')
        subprocess.run(['/opt/opticable-api-platform/apps/workflow-api/.venv/bin/python', '-I', '-B',
            '/usr/local/share/optibrain-command-center-v1/ops/business_autopilot/verify_storage_host.py',
            '--output', str(output), '--baseline', str(root / 'preservation-before.json')],
            check=True, capture_output=True, timeout=30)
        value = json.loads(protected(output))
        if (not value['all_flags_disabled'] or value['flag_checks'] != 45 or
            value['protected_settings_checked'] != 76 or value['protected_changes'] or
            any(value['health'][k] != 200 for k in ('api', 'pdf', 'omada')) or
            value['backup_verification'] != 'download_hash_verified'):
            raise Failure('CORE_OR_PROTECTED_RECORD_VERIFICATION_FAILED')
    controller = Controller(p, model, provider, journal, clock)
    if not args.execute and not args.recover:
        guards(); controller.equal(*controller.state(clock.monotonic() + 40), 'original'); core('preflight')
        print(json.dumps({'state': 'READ_ONLY_PREFLIGHT_PASSED', 'production_mutations': 0,
                          'ready_received': False, 'test_started': False}), flush=True)
        return
    with exclusive(p['execution_lock_path']):
        # Reload after obtaining the lock. A waiting process must never use a
        # pre-lock ledger snapshot that predates another completed execution.
        journal = Journal(root, clock)
        provider.journal = journal
        controller = Controller(p, model, provider, journal, clock)
        if args.recover:
            if not journal.data.get('used'): raise Failure('NO_STARTED_TEST_TO_RECOVER')
            controller.restore()
            controller.equal(*controller.state(clock.monotonic() + 40), 'original'); guards(); core('recovery')
            journal.event('FINAL_ORIGINAL_STATE_INDEPENDENTLY_VERIFIED', owner_acceptance='UNVERIFIED_RECOVERY_ONLY')
            return
        if journal.data.get('used'): raise Failure('TEST_ALREADY_CONSUMED')
        core('before')
        stop = controller.stopped
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda signum, frame: stop.set())
        read_provider = Provider(p, transport, journal, clock, writes=False)
        def required(cancel):
            local_check()
            with read_provider.limit(clock.monotonic() + 40, cancel): app, policy = read_provider.state()
            if cancel.is_set(): raise Failure('READ_CANCELLED')
            controller.equal(app, policy, 'test_binding_off')
        def optional():
            journal.event('TUNNEL_METRICS', counters=guard.metrics())
        error = None
        try: controller.execute(guards, lambda: ReadWorker(required, optional, journal, clock))
        except Exception as caught: error = caught
        # Run independent original-state and environment readbacks even when an
        # earlier monitoring exception propagated after successful restoration.
        if journal.data.get('restored'):
            controller.equal(*controller.state(clock.monotonic() + 40), 'original'); guards(); core('after')
            journal.event('FINAL_ORIGINAL_STATE_INDEPENDENTLY_VERIFIED', owner_acceptance='PENDING_OWNER_REPORT')
        if error is not None: raise error


if __name__ == '__main__':
    raise SystemExit('Use the sealed, approval-hash-pinned runner; this library cannot launch a test directly.')

