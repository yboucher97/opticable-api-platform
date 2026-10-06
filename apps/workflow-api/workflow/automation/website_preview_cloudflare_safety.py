"""Read-only live Builds discovery and proposal-push containment.

Reuse the owner-provided user token at its canonical path. No token creation,
trigger mutation, Worker upload, route or production deployment port exists.
"""
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .website_preview_execution import BINDING_FIELDS
from .website_preview_github_live import (
    NoRedirect, _trusted_bytes, REPOSITORY, REPOSITORY_ID, PROPOSAL_ID,
)
from .website_preview_model import proposal_branch, sha


ACCOUNT = '81d07d311d1b51e5e04b451d1f254850'
PREVIEW_WORKER = 'opticable-optimization-preview'
USER_TOKEN_PATH = Path('/etc/optibrain/website-preview/cloudflare-builds-user.token')


class CloudflareReadFailure(Exception):
    def __init__(self, status, codes):
        self.status = status; self.codes = codes
        super().__init__('Cloudflare read failed: HTTP ' + str(status))


class ProductionBoundaryFailure(PermissionError):
    def __init__(self, blockers):
        self.blockers = deepcopy(blockers)
        super().__init__('PRODUCTION_BUILDS_TRIGGER_MATCHES_PROPOSAL')


class CloudflareBuildsReadHTTP:
    """Fixed account, GET only, no redirects, retry, credentials in logs/body."""
    def __init__(self, *, token_path=USER_TOKEN_PATH, maximum=40):
        if token_path != USER_TOKEN_PATH or type(maximum) is not int or not 1 <= maximum <= 40:
            raise ValueError('Canonical user credential and bounded discovery required')
        self.token_path = token_path; self.maximum = maximum; self.calls = []
        self.opener = build_opener(NoRedirect()); self.denied = False

    def read(self, path):
        if not isinstance(path,str): raise ValueError('Fixed Cloudflare read endpoint required')
        prefix = '/accounts/' + ACCOUNT
        allowed = path in {'/user/tokens/verify', prefix, prefix + '/workers/scripts'}
        allowed = allowed or isinstance(path, str) and bool(re.fullmatch(
            re.escape(prefix) + r'/builds/workers/[a-f0-9]{32}/triggers', path))
        if not allowed: raise ValueError('Endpoint outside read-only Cloudflare Builds discovery')
        if self.denied: raise PermissionError('Earlier Cloudflare auth denial; no retry')
        if len(self.calls) >= self.maximum: raise ValueError('Cloudflare discovery request budget exhausted')
        token = _trusted_bytes(self.token_path, 256).decode('ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', token): raise PermissionError('Invalid credential encoding')
        request = Request('https://api.cloudflare.com/client/v4' + path, method='GET',
            headers={'Authorization':'Bearer '+token, 'User-Agent':'OptiBrain-Preview-Safety'})
        self.calls.append({'endpoint':path})
        try: response = self.opener.open(request, timeout=10)
        except HTTPError as error: response = error
        with response:
            status = response.code; raw = response.read(262145)
            if len(raw) > 262144: raise ValueError('Cloudflare discovery response exceeds bound')
            data = json.loads(raw)
            source = parsedate_to_datetime(response.headers['Date']).astimezone(timezone.utc).isoformat()
        codes = [e.get('code') for e in data.get('errors', [])]
        self.calls[-1].update(http=status, success=data.get('success'), error_codes=codes)
        if status in (401,403): self.denied = True
        if not 200 <= status < 300 or data.get('success') is not True:
            raise CloudflareReadFailure(status, codes)
        info = data.get('result_info') or {}
        if info.get('total_pages', 1) != 1 or info.get('page', 1) != 1:
            raise ValueError('Incomplete Cloudflare inventory')
        if isinstance(data.get('result'), list) and any(
                info[k] != len(data['result']) for k in ('total_count','count') if k in info):
            raise ValueError('Incomplete Cloudflare inventory')
        return data['result'], source


def _matches(pattern, branch):
    if not isinstance(pattern, str) or not pattern or len(pattern) > 200 or not re.fullmatch(r'[A-Za-z0-9_./*:-]+',pattern):
        raise ValueError('Unknown branch-filter syntax cannot establish safety')
    return bool(re.fullmatch(re.escape(pattern).replace(r'\*', '.*'), branch))


def unsafe_triggers(worker, triggers, branch):
    """Any automatic write outside the isolated target violates this mission."""
    proposal_branch(branch, PROPOSAL_ID)
    if not isinstance(triggers, list) or len(triggers) > 2:
        raise ValueError('Bounded complete trigger inventory required')
    blockers = []
    for trigger in triggers:
        if trigger.get('external_script_id') != worker['tag']:
            raise ValueError('Trigger Worker tag differs')
        connection = trigger.get('repo_connection')
        if not isinstance(connection, dict): raise ValueError('Trigger repository identity unavailable')
        if connection.get('provider_type') != 'github': continue
        if str(connection.get('repo_id')) != str(REPOSITORY_ID): continue
        if connection.get('provider_account_name') != 'yboucher97' or connection.get('repo_name') != 'opticable-website':
            raise ValueError('Trigger repository identity inconsistent')
        if connection.get('deleted_on') is not None or trigger.get('deleted_on') is not None: continue
        includes = trigger.get('branch_includes'); excludes = trigger.get('branch_excludes')
        if not isinstance(includes,list) or not includes or not isinstance(excludes,list) or len(includes)+len(excludes)>200:
            raise ValueError('Explicit bounded branch filters required')
        included = any([_matches(p,branch) for p in includes])
        excluded = any([_matches(p,branch) for p in excludes])
        if included and not excluded:
            # An automatic upload to the isolated target would also undermine
            # the exact-one controlled upload. All matching triggers must stop.
            blockers.append({'worker':worker['id'],'worker_tag':worker['tag'],
                'trigger_uuid':trigger.get('trigger_uuid'),'trigger_name':trigger.get('trigger_name'),
                'branch_includes':deepcopy(includes),'branch_excludes':deepcopy(excludes),
                'deploy_command':trigger.get('deploy_command'),'reason':'AUTOMATIC_WORKER_WRITE_ON_PROPOSAL_PUSH'})
    return blockers


class CloudflarePushSafety:
    def __init__(self, allowed_branch, *, transport=None, clock=None):
        self.allowed_branch = proposal_branch(allowed_branch, PROPOSAL_ID)
        self.transport = transport or CloudflareBuildsReadHTTP()
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self.last_receipt = None

    def _binding(self, binding):
        if not isinstance(binding,dict) or set(binding) != set(BINDING_FIELDS):
            raise ValueError('Exact proposal tuple required')
        if binding['repository'] != REPOSITORY or binding['proposal_id'] != PROPOSAL_ID or binding['branch'] != self.allowed_branch:
            raise ValueError('Repository/ref outside exact Cloudflare proposal allowlist')
        if type(binding['proposal_revision']) is not int or binding['proposal_revision'] < 1:
            raise ValueError('Exact revision required')
        sha(binding['base_sha']); sha(binding['head_sha'])
        if not re.fullmatch('[a-f0-9]{64}',binding['proposal_hash']): raise ValueError('Canonical hash required')

    def require_safe(self, binding):
        self._binding(binding); now = self.clock()
        if self.last_receipt and self.last_receipt['binding'] == binding:
            age = (now-datetime.fromisoformat(self.last_receipt['observed_at'])).total_seconds()
            if 0 <= age <= 30:
                if not self.last_receipt['safe']: raise ProductionBoundaryFailure(self.last_receipt['blockers'])
                return deepcopy(self.last_receipt)
        verification, source = self.transport.read('/user/tokens/verify')
        if verification.get('status') != 'active': raise PermissionError('User token not active')
        account, source = self.transport.read('/accounts/'+ACCOUNT)
        if account.get('id') != ACCOUNT: raise ValueError('Cloudflare account differs')
        workers, source = self.transport.read('/accounts/'+ACCOUNT+'/workers/scripts')
        if not isinstance(workers,list) or not workers or len(workers)>12:
            raise ValueError('Bounded complete Worker inventory required')
        workers=sorted(workers,key=lambda w:(w.get('id')!='opticable-website',w.get('id','')))
        names=set();tags=set();blockers=[];observed=[]
        for worker in workers:
            if not re.fullmatch('[a-f0-9]{32}',worker.get('tag','')) or not isinstance(worker.get('id'),str) or worker['id'] in names or worker['tag'] in tags:
                raise ValueError('Worker inventory identity malformed or duplicated')
            names.add(worker['id']);tags.add(worker['tag'])
            triggers, source = self.transport.read('/accounts/'+ACCOUNT+'/builds/workers/'+worker['tag']+'/triggers')
            blockers.extend(unsafe_triggers(worker,triggers,binding['branch']));observed.append(worker['id'])
            if blockers: break  # Proven unsafe; no further provider calls needed.
        self.last_receipt={'binding':deepcopy(binding),'account':ACCOUNT,'observed_at':now.isoformat(),
            'source_at':source,'safe':not blockers,'blockers':blockers,'workers_checked':observed,
            'inventory_complete':not blockers and len(observed)==len(workers),'provider_mutations':0}
        if blockers: raise ProductionBoundaryFailure(blockers)
        return deepcopy(self.last_receipt)
