"""Bounded existing-App GitHub port for one private website proposal.

Only short-lived, repository/permission-restricted installation tokens are used.
They remain in memory. No generic mutation, force, deletion, merge, dispatch,
configuration or production deployment interface exists.
"""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

import jwt

from .website_preview_execution import PERMISSIONS, ProposalPreviewExecutor
from .website_preview_model import proposal_branch, sha
from .website_preview_providers import ReadResult


REPOSITORY = 'yboucher97/opticable-website'
REPOSITORY_ID = 1179376497
PROPOSAL_ID = '49d2893d1498325eb5ae8f5a7304d1e3d199d03afcb4c6d0383dd7ed6ab32c17'
APP_ID = 5077440
INSTALLATION_ID = 164914980
READ_PERMISSIONS = {key: 'read' for key in PERMISSIONS}


def _trusted_bytes(path, maximum=65536):
    """Existing root-owned 0640 App key is allowed; never alter its permissions."""
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Untrusted credential parent')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o027 or info.st_size > maximum:
            raise PermissionError('Untrusted credential file')
        data = os.read(fd, maximum + 1)
        if len(data) > maximum:
            raise ValueError('Credential file exceeds bound')
        return data
    finally:
        os.close(fd)


@dataclass(frozen=True)
class ExistingPreviewApp:
    app_id: int = APP_ID
    installation_id: int = INSTALLATION_ID
    private_key_path: Path = Path('/etc/optibrain/github-app.pem')

    def validate(self):
        if type(self.app_id) is not int or type(self.installation_id) is not int or self.app_id != APP_ID or self.installation_id != INSTALLATION_ID or self.private_key_path != Path('/etc/optibrain/github-app.pem'):
            raise ValueError('Only the owner-verified existing GitHub App is allowed')
        return self

    @classmethod
    def from_secure_configuration(cls):
        root = Path('/etc/optibrain/website-preview')
        ids = []
        for filename in ('github-app-id', 'github-installation-id'):
            raw = _trusted_bytes(root / filename, 32).decode('ascii').strip()
            if not re.fullmatch('[0-9]{1,12}', raw):
                raise ValueError('Nonsecret numeric GitHub ID required')
            ids.append(int(raw))
        return cls(*ids).validate()


class ProviderFailure(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__('GitHub provider HTTP ' + str(status))


class BudgetExhausted(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('GitHub redirects forbidden')


class BoundedGitHubHTTP:
    """Fixed host/endpoints, 10s timeout, 256KiB response and 30-request cap."""
    def __init__(self, *, max_requests=30):
        if type(max_requests) is not int or not 1 <= max_requests <= 30:
            raise ValueError('GitHub request budget must be 1..30')
        self.max_requests = max_requests
        self.calls = []
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, credential, body=None):
        # Independent transport backstop: no foreign repo or dangerous verb.
        if not isinstance(path, str):
            raise ValueError('Fixed preview GitHub endpoint required')
        clean = path.split('?', 1)[0]
        repo = '/repos/' + REPOSITORY
        reads = clean in {'/app', '/app/installations/' + str(INSTALLATION_ID), '/installation/repositories', repo}
        reads = reads or bool(re.fullmatch(re.escape(repo) + r'/(?:git/ref/heads/[a-zA-Z0-9/-]+|commits/[a-f0-9]{40}|pulls|actions/runs|actions/runs/[0-9]+/jobs)', clean))
        auth = method == 'POST' and clean == '/app/installations/' + str(INSTALLATION_ID) + '/access_tokens'
        draft = method == 'POST' and clean == repo + '/pulls'
        if re.search(r'[\x00-\x20\\#]', path) or not (method == 'GET' and reads or auth or draft):
            raise ValueError('Endpoint outside preview GitHub transport')
        if auth and (not isinstance(body, dict) or set(body) != {'repository_ids', 'permissions'}
                or body['repository_ids'] != [REPOSITORY_ID] or body['permissions'] not in (READ_PERMISSIONS, PERMISSIONS)):
            raise ValueError('Repository-restricted minimum token request required')
        if draft:
            if not isinstance(body, dict) or set(body) != {'title', 'body', 'head', 'base', 'draft'} or body['base'] != 'main' or body['draft'] is not True:
                raise ValueError('Draft-only PR payload required')
            proposal_branch(body['head'], PROPOSAL_ID)
        if len(self.calls) >= self.max_requests:
            raise BudgetExhausted('GitHub request budget exhausted')
        raw = json.dumps(body).encode() if body is not None else None
        if raw is not None and len(raw) > 65536:
            raise ValueError('GitHub request body exceeds bound')
        self.calls.append((method, clean))  # No credentials or raw bodies retained.
        request = Request('https://api.github.com' + path, data=raw, method=method, headers={
            'Authorization': 'Bearer ' + credential, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json',
            'User-Agent': 'OptiBrain-Website-Preview',
        })
        try:
            with self.opener.open(request, timeout=10) as response:
                data = response.read(262145)
                if len(data) > 262144:
                    raise ValueError('GitHub response exceeds bound')
                source_at = parsedate_to_datetime(response.headers['Date']).astimezone(timezone.utc).isoformat()
                return response.status, json.loads(data), source_at
        except HTTPError as error:
            # Do not log response bodies, request headers or provider prose.
            status = error.code
            error.close()
            raise ProviderFailure(status) from None


class GitHubPreviewAdapter:
    required_ci_checks = ('validate',)
    requires_draft_pr = True

    def __init__(self, app, *, transport=None, clock=None, store=None, local_git=None, boundary=None):
        self.app = app.validate()
        self.transport = transport or BoundedGitHubHTTP()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = store; self.local_git = local_git; self.boundary = boundary
        self._tokens = {}  # Ephemeral memory only; never serialized or logged.
        self._identity = None
        self._auth_failed = False
        self._last_source_at = None

    def _repo(self, repository):
        if repository != REPOSITORY:
            raise ValueError('Only the first-preview website repository is allowed')

    def _branch(self, branch, *, reading=False):
        if reading and branch == 'main':
            return branch
        proposal_branch(branch, PROPOSAL_ID)
        if self.boundary is not None and branch != self.boundary.allowed_branch:
            raise ValueError('Ref outside exact proposal allowlist')
        return branch

    def _jwt(self):
        now = int(self.clock().timestamp())
        value = jwt.encode({'iat': now-60, 'exp': now+540, 'iss': str(self.app.app_id)},
            _trusted_bytes(self.app.private_key_path).decode('ascii'), algorithm='RS256')
        return value.decode() if isinstance(value, bytes) else value

    def _call(self, method, path, credential, body=None):
        status, data, source_at = self.transport.request(method, path, credential, body)
        if status < 200 or status >= 300:
            raise ProviderFailure(status)
        self._last_source_at = source_at
        return data

    def _token(self, *, write=False):
        if self._auth_failed:
            raise PermissionError('Earlier GitHub auth failure; no retry')
        now = self.clock()
        mode = 'write' if write else 'read'
        cached = self._tokens.get(mode)
        if cached and now.timestamp() < cached[1] - 60:
            return cached[0]
        permissions = PERMISSIONS if write else READ_PERMISSIONS
        credential = self._jwt()
        if self._identity is None:
            app = self._call('GET', '/app', credential)
            installation = self._call('GET', '/app/installations/' + str(INSTALLATION_ID), credential)
            if app.get('id') != APP_ID or app.get('name') != 'OptiBrain Production' or installation.get('id') != INSTALLATION_ID or installation.get('app_id') != APP_ID or installation.get('account', {}).get('login') != 'yboucher97' or installation.get('suspended_at') is not None:
                raise PermissionError('Owner-verified GitHub App/installation identity mismatch')
            self._identity = {'app_id': APP_ID, 'app_name': app['name'], 'installation_id': INSTALLATION_ID,
                'account': 'yboucher97', 'installation_repository_selection': installation.get('repository_selection')}
        data = self._call('POST', '/app/installations/' + str(INSTALLATION_ID) + '/access_tokens', credential,
            {'repository_ids': [REPOSITORY_ID], 'permissions': dict(permissions)})
        expiry = datetime.fromisoformat(str(data.get('expires_at', '')).replace('Z', '+00:00'))
        if expiry.tzinfo is None or not 60 < (expiry-now).total_seconds() <= 3900 or data.get('permissions') != permissions:
            raise PermissionError('Unexpected installation token lifetime or permissions')
        token = data.get('token')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{20,8192}', token):
            raise PermissionError('Installation token unavailable')
        selected = self._call('GET', '/installation/repositories?per_page=2', token)
        if selected.get('total_count') != 1 or [r.get('full_name') for r in selected.get('repositories', [])] != [REPOSITORY] or selected['repositories'][0].get('id') != REPOSITORY_ID or selected['repositories'][0].get('private') is not True:
            raise PermissionError('Installation token is not restricted to the private website')
        self._tokens[mode] = (token, expiry.timestamp(), dict(permissions))
        return token

    def verify_identity(self, *, for_write=False):
        try:
            self._token(write=for_write)
        except ProviderFailure as error:
            if error.status in (401, 403): self._auth_failed = True
            raise
        except (PermissionError, jwt.PyJWTError):
            self._auth_failed = True
            raise
        cached = self._tokens['write' if for_write else 'read']
        return {**self._identity, 'effective_repositories': [REPOSITORY],
            'effective_permissions': cached[2], 'expires_at': datetime.fromtimestamp(cached[1], timezone.utc).isoformat(),
            'observed_at': self.clock().isoformat(), 'installation_tokens_persisted': False}

    def _get(self, path):
        return self._call('GET', '/repos/' + REPOSITORY + path, self._token())

    def _observe(self, operation):
        now = self.clock(); before = len(self.transport.calls)
        try:
            data = operation()
            state = 'VERIFIED_EMPTY' if data == [] else 'COMPLETE'
            return ReadResult(state, data, self._last_source_at, self.clock().isoformat(), 1, 1, 0).validate()
        except BudgetExhausted:
            return ReadResult('NOT_COLLECTED', reason='REQUEST_BUDGET_EXHAUSTED').validate()
        except ProviderFailure as error:
            if error.status in (401, 403): self._auth_failed = True
            attempted = int(len(self.transport.calls) > before)
            return ReadResult('BLOCKED_AUTH' if error.status in (401,403) else 'FAILED', None, None,
                now.isoformat(), attempted, 0, attempted, 'HTTP_' + str(error.status)).validate()
        except (PermissionError, jwt.PyJWTError):
            self._auth_failed = True
            attempted = int(len(self.transport.calls) > before)
            return ReadResult('BLOCKED_AUTH', None, None, now.isoformat(), attempted, 0, attempted, 'AUTH_BOUNDARY_DENIED').validate()
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            attempted = int(len(self.transport.calls) > before)
            return ReadResult('FAILED', None, None, now.isoformat(), attempted, 0, attempted, 'INVALID_OR_FAILED_PROVIDER_READ').validate()

    def get_repository(self, repository):
        self._repo(repository)
        def read():
            data = self._get('')
            if data.get('id') != REPOSITORY_ID or data.get('full_name') != REPOSITORY or data.get('private') is not True or data.get('default_branch') != 'main':
                raise ValueError('Private website identity mismatch')
            return {'repository': REPOSITORY, 'repository_id': REPOSITORY_ID, 'private': True, 'default_branch': 'main'}
        return self._observe(read)

    def get_branch(self, repository, branch):
        self._repo(repository); self._branch(branch, reading=True)
        def read():
            # Prove access first; a 404 alone cannot mean a ref is absent.
            metadata = self._get('')
            if metadata.get('id') != REPOSITORY_ID or metadata.get('private') is not True:
                raise ValueError('Repository visibility/identity mismatch')
            try:
                data = self._get('/git/ref/heads/' + quote(branch, safe='/'))
            except ProviderFailure as error:
                if error.status != 404: raise
                return []
            if data.get('ref') != 'refs/heads/' + branch or data.get('object', {}).get('type') != 'commit':
                raise ValueError('Remote ref identity mismatch')
            return {'repository': REPOSITORY, 'branch': branch, 'sha': sha(data['object']['sha'])}
        return self._observe(read)

    def get_commit(self, repository, commit):
        self._repo(repository); sha(commit)
        def read():
            data = self._get('/commits/' + commit)
            if data.get('sha') != commit: raise ValueError('Commit identity mismatch')
            return {'repository': REPOSITORY, 'sha': commit}
        return self._observe(read)

    def get_pr(self, repository, branch):
        self._repo(repository); self._branch(branch)
        def read():
            data = self._get('/pulls?' + urlencode({'state':'all', 'head':'yboucher97:'+branch, 'per_page':2}))
            if not isinstance(data, list) or len(data) > 1:
                raise ValueError('Ambiguous proposal PR inventory')
            if not data: return []
            p = data[0]
            if p['head']['repo']['full_name'] != REPOSITORY or p['base']['repo']['full_name'] != REPOSITORY or p['head']['ref'] != branch:
                raise ValueError('PR repository/ref mismatch')
            if type(p.get('number')) is not int or p['number']<1 or type(p.get('draft')) is not bool or p.get('state') not in {'open','closed'}:
                raise ValueError('PR state/identity malformed')
            return {'repository': REPOSITORY, 'branch': branch, 'head_sha': sha(p['head']['sha']),
                'base_ref': p['base']['ref'], 'draft': p['draft'], 'number': p['number'],
                'state': p['state'], 'auto_merge': p.get('auto_merge'), 'url': p['html_url']}
        return self._observe(read)

    def get_workflow_status(self, repository, commit):
        self._repo(repository); sha(commit)
        def read():
            data = self._get('/actions/runs?' + urlencode({'head_sha':commit, 'event':'pull_request', 'per_page':10}))
            runs = data.get('workflow_runs')
            if not isinstance(runs, list) or data.get('total_count') != len(runs) or len(runs) > 10:
                raise ValueError('Incomplete exact-head workflow inventory')
            candidates = [r for r in runs if r.get('head_sha') == commit and r.get('event') == 'pull_request'
                and r.get('path', '').split('@')[0] == '.github/workflows/measurement-validation.yml']
            if not candidates: return []
            run = max(candidates, key=lambda r: r['id'])
            if run.get('repository', {}).get('full_name') != REPOSITORY:
                raise ValueError('Workflow repository differs')
            self._branch(run['head_branch'])
            jobs = self._get('/actions/runs/' + str(run['id']) + '/jobs?per_page=20&filter=latest')
            if jobs.get('total_count') != len(jobs.get('jobs', [])) or len(jobs['jobs']) > 20:
                raise ValueError('Incomplete CI job inventory')
            selected = [j for j in jobs['jobs'] if j.get('name') == 'validate']
            passed = run.get('status') == 'completed' and run.get('conclusion') == 'success' and len(selected) == 1 and selected[0].get('head_sha') == commit and selected[0].get('status') == 'completed' and selected[0].get('conclusion') == 'success'
            return {'repository': REPOSITORY, 'branch': run['head_branch'], 'head_sha': commit,
                'checks': {'validate':'PASS' if passed else 'FAIL' if run.get('status') == 'completed' else 'RUNNING'},
                'run_id': run['id'], 'url': run['html_url'], 'event': 'pull_request'}
        return self._observe(read)

    def _write_binding(self, repository, branch, proposal_id, commit=None):
        self._repo(repository); self._branch(branch)
        if proposal_id != PROPOSAL_ID or self.boundary is None or self.store is None:
            raise PermissionError('Configured exact proposal authority required')
        binding = self.boundary.binding()
        if commit is not None and commit != binding['head_sha']:
            raise ValueError('Proposal SHA outside exact allowlist')
        ProposalPreviewExecutor(self.store, self, self.boundary)._prepared(binding, self.clock())
        if os.geteuid() != 0:
            raise PermissionError('Explicit root-controlled preview execution required')
        return binding

    def _current_base(self, binding):
        read = self.get_branch(REPOSITORY, 'main')
        if read.state != 'COMPLETE' or read.data.get('sha') != binding['base_sha']:
            raise ValueError('Prepared base differs from current remote main')

    def push_proposal_branch(self, repository, branch, commit, proposal_id):
        binding = self._write_binding(repository, branch, proposal_id, commit)
        if self.local_git is None or self.local_git.repository != REPOSITORY:
            raise PermissionError('Reviewed bounded local Git adapter required')
        local = self.local_git.read_worktree_state(proposal_id)
        if local['dirty'] or any(local.get(k) != binding[k] for k in ('branch','base_sha','head_sha','proposal_revision')):
            raise ValueError('Local proposal worktree/SHA differs')
        value = self.store.preview(proposal_id, self.clock()); package = value['package']
        path = Path(local['path'])
        changed = set(self.local_git._git(path, 'diff', '--name-only', '--no-ext-diff', binding['base_sha'], commit).splitlines())
        if changed != {c['path'] for c in package['changes']}:
            raise ValueError('Unrelated source or generated output in proposal commit')
        expected = {}
        for change in package['changes']:
            content = expected.get(change['path'])
            if content is None: content = self.local_git._git(path, 'show', binding['base_sha']+':'+change['path'])
            if content.count(change['before']) != 1: raise ValueError('Exact source precondition mismatch')
            expected[change['path']] = content.replace(change['before'], change['after'], 1)
        for filename, content in expected.items():
            if self.local_git._git(path, 'show', commit+':'+filename) != content:
                raise ValueError('Committed source differs from canonical proposal')
        self._current_base(binding)
        prior = self.get_branch(repository, branch)
        if prior.state == 'COMPLETE' and prior.data.get('sha') == commit:
            return {**binding, 'state':'PUSHED', 'remote_sha':commit, 'provider_writes':0}
        if prior.state != 'VERIFIED_EMPTY':
            raise ValueError('Existing or unknown remote branch; overwrite forbidden')
        self._write_binding(repository, branch, proposal_id, commit)
        token = self._token(write=True)
        env = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'GIT_CONFIG_NOSYSTEM':'1', 'GIT_CONFIG_GLOBAL':'/dev/null',
            'GIT_TERMINAL_PROMPT':'0', 'GIT_CONFIG_COUNT':'1', 'GIT_CONFIG_KEY_0':'http.https://github.com/.extraHeader',
            'GIT_CONFIG_VALUE_0':'Authorization: Basic '+base64.b64encode(('x-access-token:'+token).encode()).decode()}
        argv = ['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','credential.helper=',
            '-c','http.followRedirects=false','-C',str(path),'push','--porcelain','--no-verify','--',
            'https://github.com/'+REPOSITORY+'.git',commit+':refs/heads/'+branch]
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(argv, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=120, shell=False)
            if result.returncode != 0 or output.tell() > 65536:
                raise ValueError('Bounded proposal push failed; no unsafe retry')
        readback = self.get_branch(repository, branch)
        if readback.state != 'COMPLETE' or readback.data.get('sha') != commit:
            raise ValueError('Remote ref readback differs from authorized SHA')
        self._write_binding(repository, branch, proposal_id, commit)
        return {**binding, 'state':'PUSHED', 'remote_sha':commit, 'provider_writes':1}

    def open_draft_pr(self, repository, branch, proposal_id):
        binding = self._write_binding(repository, branch, proposal_id)
        self._current_base(binding)
        readback = self.get_branch(repository, branch)
        if readback.state != 'COMPLETE' or readback.data.get('sha') != binding['head_sha']:
            raise ValueError('Exact remote proposal ref required')
        prior = self.get_pr(repository, branch)
        if prior.state != 'VERIFIED_EMPTY':
            raise ValueError('Existing or unknown PR; duplicate creation forbidden')
        self._write_binding(repository, branch, proposal_id)
        body = {'title':'PREVIEW ONLY — Commercial camera landing page — DO NOT MERGE', 'head':branch,
            'base':'main', 'draft':True, 'body':'Isolated camera preview only. Owner review required; no merge or production deployment.\n\n'
            + '\n'.join(k+': '+str(binding[k]) for k in binding)}
        self._call('POST', '/repos/'+REPOSITORY+'/pulls', self._token(write=True), body)
        pr = self.get_pr(repository, branch)
        if pr.state != 'COMPLETE' or pr.data.get('head_sha') != binding['head_sha'] or pr.data.get('base_ref') != 'main' or pr.data.get('draft') is not True or pr.data.get('auto_merge') is not None or pr.data.get('state') != 'open':
            raise ValueError('Draft PR readback differs')
        self._write_binding(repository, branch, proposal_id)
        return {**binding, 'state':'DRAFT_CREATED', 'number':pr.data['number'], 'provider_writes':1}

    def close(self):
        self._tokens.clear()
