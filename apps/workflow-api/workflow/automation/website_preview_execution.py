"""Explicit proposal-only execution guard; no merge, deletion or production port.

Operator configuration and authenticated provider receipts establish the boundary.
This module never provisions identities, loads production credentials, starts a
worker, or treats the accepted GitHub Free plan limit as provider enforcement.
Live transports remain disabled until separately configured and released.
"""
from dataclasses import dataclass

from .website_preview_model import (
    preparation_package, proposal_branch, repository_name, sha, test_passes,
    validate_preview_state,
)
from .website_preview_runtime import _fresh


PERMISSIONS = {
    'metadata': 'read', 'contents': 'write', 'pull_requests': 'write',
    'actions': 'read', 'checks': 'read', 'statuses': 'read',
}
REQUIRED_TESTS = frozenset('BUILD ROUTES FR EN FORMS GA4 ATTRIBUTION LINKS SCHEMA ACCESSIBILITY RESPONSIVE SECRET_SCAN'.split())
BINDING_FIELDS = ('proposal_id', 'proposal_revision', 'proposal_hash', 'repository', 'base_sha', 'branch', 'head_sha')


@dataclass(frozen=True)
class PreviewWriteBoundary:
    """Trusted operator receipt, never populated from a proposal or webhook."""
    repository: str
    allowed_branch: str
    proposal_id: str
    proposal_revision: int
    proposal_hash: str
    base_sha: str
    head_sha: str
    selected_repositories: tuple
    permissions: dict
    verified_at: str
    main_protected: bool = False
    free_plan_limit_accepted: bool = False
    non_main_deployment_safe: bool = False
    production_credentials_available: bool = True
    enabled: bool = False

    def validate(self, now):
        from .manager_sources import stamp
        if any(type(getattr(self, field)) is not bool for field in (
                'main_protected', 'free_plan_limit_accepted', 'non_main_deployment_safe',
                'production_credentials_available', 'enabled')):
            raise ValueError('Explicit boolean execution controls required')
        repository_name(self.repository)
        proposal_branch(self.allowed_branch, self.proposal_id)
        sha(self.base_sha); sha(self.head_sha)
        if type(self.proposal_revision) is not int or self.proposal_revision < 1:
            raise ValueError('Exact proposal revision required')
        if not isinstance(self.proposal_hash, str) or len(self.proposal_hash) != 64 or any(c not in '0123456789abcdef' for c in self.proposal_hash):
            raise ValueError('Canonical proposal hash required')
        at = stamp(self.verified_at)
        if not at or not 0 <= (now - at).total_seconds() <= 900:
            raise PermissionError('Fresh authenticated boundary receipt required')
        if self.selected_repositories != (self.repository,) or self.permissions != PERMISSIONS:
            raise PermissionError('Selected repository and minimum effective permissions required')
        if not self.enabled or not self.non_main_deployment_safe or self.production_credentials_available:
            raise PermissionError('Preview-only execution authority unavailable')
        if not self.main_protected and not self.free_plan_limit_accepted:
            raise PermissionError('Main protection or explicit owner-accepted plan limit required')
        return self

    def binding(self):
        return {k: getattr(self, 'allowed_branch' if k == 'branch' else k) for k in BINDING_FIELDS}


class ProposalPreviewExecutor:
    """Two bounded operations on one canonical tuple; all ref checks precede I/O.

    The provider's live transport must independently restrict its write endpoints
    and credentials. A boundary receipt alone cannot make a fake provider live.
    """
    def __init__(self, store, github, boundary, *, clock=None):
        self.store = store
        self.github = github
        self.boundary = boundary
        self.clock = clock

    def _now(self, now):
        # Trusted operator clock, never provider/payload supplied. Authentication
        # and network reads can complete after the invocation's initial time.
        return self.clock() if self.clock else now

    def _prepared(self, binding, now):
        now = self._now(now)
        self.boundary.validate(now)
        if not isinstance(binding, dict) or set(binding) != set(BINDING_FIELDS):
            raise ValueError('Exact proposal execution tuple required')
        if type(binding['proposal_revision']) is not int:
            raise ValueError('Exact integer proposal revision required')
        # Reject main/master, foreign repositories and every unallowlisted ref
        # before any remote read or write, including valid-looking other refs.
        if binding != self.boundary.binding():
            raise ValueError('Execution tuple outside the single proposal allowlist')
        proposal_branch(binding['branch'], binding['proposal_id'])
        sha(binding['head_sha']); sha(binding['base_sha'])
        item = self.store.website_proposal(binding['proposal_id'])
        value = self.store.preview(binding['proposal_id'], now)
        if not value or any(value.get(k) != binding[k] for k in BINDING_FIELDS):
            raise ValueError('Current canonical preparation differs from execution tuple')
        validate_preview_state(value)
        package = value.get('package') or {}
        expected = preparation_package(item, binding['repository'], binding['base_sha'],
            package.get('allowed_files'), package.get('changes'),
            package.get('required_tests'), package.get('evidence_refs'))
        if expected != package or value.get('semantic_hash') != expected['semantic_hash']:
            raise ValueError('Canonical source package mismatch')
        if item['record']['revision'] != binding['proposal_revision'] or item['payload_hash'] != binding['proposal_hash']:
            raise ValueError('Canonical proposal revision changed')
        if not test_passes(value) or not REQUIRED_TESTS <= set(value['required_tests']):
            raise PermissionError('Fresh exact-head required test evidence missing')
        if value.get('stale_state') != 'CURRENT' or value.get('owner_status') != 'PENDING':
            raise PermissionError('Current pending proposal required')
        return value

    def _read(self, operation, now, *args, empty=False):
        from .website_preview_providers import ReadResult
        read = operation(*args)
        now = self._now(now)
        if not isinstance(read, ReadResult) or not _fresh(read, now):
            raise PermissionError('Fresh authenticated provider read required')
        if read.state == 'VERIFIED_EMPTY':
            if empty:
                return None
            raise ValueError('Required provider object absent')
        if read.state != 'COMPLETE' or not isinstance(read.data, dict):
            raise ValueError('Complete provider object required')
        return read.data

    def _main(self, binding, now):
        value = self._read(self.github.get_branch, now, binding['repository'], 'main')
        if value.get('repository') != binding['repository'] or value.get('branch') != 'main' or value.get('sha') != binding['base_sha']:
            raise ValueError('Current main differs from prepared base')

    def _branch(self, binding, now, *, empty=False):
        value = self._read(self.github.get_branch, now, binding['repository'], binding['branch'], empty=empty)
        if value is not None and (value.get('repository') != binding['repository'] or value.get('branch') != binding['branch'] or value.get('sha') != binding['head_sha']):
            raise ValueError('Remote proposal ref differs; overwrite forbidden')
        return value

    def _audited(self, binding, now, operation, before, mutate, readback):
        from .action_evidence import ActionEvidence,envelope,execute_action
        from .acquisition_store import digest
        aid=digest(['website-preview',operation,binding])
        journal=ActionEvidence(self.store.path)
        plan=envelope(aid,operation,{'type':'WEBSITE_PREVIEW','identity':binding['repository']+':'+binding['branch']},now,
            mutation=True,provider='GITHUB',proposal_id=binding['proposal_id'],before_state=before,proposed_state=binding,
            reason='Prepare the exact isolated proposal for owner review',business_rationale='Existing preview-only boundary validates exact source, tests and provider containment',
            authority_class='EXISTING_PREVIEW_ONLY_SCOPE',automatic_rule='Exact canonical tuple, tested preview scope and fresh root-configured boundary',
            exact_versions={**binding,'environment':'preview'},rollback_capability='COMPENSATING_ACTION_ONLY',
            consequence='A proposal branch/draft PR may be externally observed; production is not changed',
            compensating_action='Owner may close draft PR/archive proposal ref after verifying it is unused; preserve audit history')
        def execute():mutate();return {'success':True}
        return execute_action(journal,plan,now,authority_check=lambda:self._prepared(binding,self._now(now)),
            execute=execute,readback=readback,verify=lambda actual,expected:actual is not None,clock=lambda:self._now(now))

    def push_proposal(self, binding, now):
        self._prepared(binding, now)
        self._main(binding, now)
        prior = self._branch(binding, now, empty=True)
        # Recheck canonical journal after remote reads, immediately before I/O.
        self._prepared(binding, now)
        writes = 0
        if prior is None:
            self._audited(binding,now,'PREVIEW_BRANCH_PUSH',{'exists':False},
                lambda:self.github.push_proposal_branch(binding['repository'], binding['branch'], binding['head_sha'], binding['proposal_id']),
                lambda:self._branch(binding,now))
            writes = 1
        self._branch(binding, now)  # Mandatory authenticated readback, even replay.
        self._prepared(binding, now)
        return {**binding, 'state': 'REMOTE_REF_VERIFIED', 'provider_writes': writes,
                'verified_at': self._now(now).isoformat(), 'force': False}

    def _pr(self, binding, now, *, empty=False):
        value = self._read(self.github.get_pr, now, binding['repository'], binding['branch'], empty=empty)
        if value is not None and (value.get('repository') != binding['repository'] or value.get('branch') != binding['branch']
                or value.get('head_sha') != binding['head_sha'] or value.get('base_ref') != 'main'
                or value.get('draft') is not True or type(value.get('number')) is not int or value['number'] < 1
                or value.get('auto_merge') is not None or value.get('state') != 'open'):
            raise ValueError('Exact-head open draft PR without auto-merge required')
        return value

    def create_draft_pr(self, binding, now):
        self._prepared(binding, now)
        self._main(binding, now)
        self._branch(binding, now)
        prior = self._pr(binding, now, empty=True)
        self._prepared(binding, now)
        writes = 0
        if prior is None:
            self._audited(binding,now,'PREVIEW_DRAFT_PR',{'exists':False},
                lambda:self.github.open_draft_pr(binding['repository'], binding['branch'], binding['proposal_id']),
                lambda:self._pr(binding,now))
            writes = 1
        pr = self._pr(binding, now)
        self._branch(binding, now)
        self._prepared(binding, now)
        return {**binding, 'state': 'DRAFT_PR_VERIFIED', 'pr_number': pr['number'],
                'provider_writes': writes, 'draft': True, 'verified_at': self._now(now).isoformat()}
