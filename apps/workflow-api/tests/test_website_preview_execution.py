"""Proposal execution boundary tests: fake providers, no network or live writes."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from workflow.automation.website_preview_execution import (
    BINDING_FIELDS, PERMISSIONS, REQUIRED_TESTS, PreviewWriteBoundary, ProposalPreviewExecutor,
)
from workflow.automation.website_preview_model import new_preview
from workflow.automation.website_preview_providers import ReadResult
from workflow.automation.manager_store import ManagerStore
from test_website_preview import NOW, PID, REPO, canonical, package, configured_repo


class Provider:
    def __init__(self, binding):
        self.binding = binding
        self.calls = []; self.writes = []
        self.remote = None; self.pr = None
        self.readback_override = None
        self.main_sha = binding['base_sha']
        self.read_state = 'COMPLETE'

    def result(self, value):
        if self.read_state == 'BLOCKED_AUTH':
            return ReadResult('BLOCKED_AUTH', None, None, NOW.isoformat(), 1, 0, 1)
        return ReadResult('VERIFIED_EMPTY' if value is None else self.read_state,
            [] if value is None else deepcopy(value), NOW.isoformat(), NOW.isoformat(), 1, 1, 0)

    def get_branch(self, repo, branch):
        self.calls.append(('read_branch', repo, branch))
        if branch == 'main':
            return self.result({'repository': repo, 'branch': branch, 'sha': self.main_sha})
        return self.result({'repository': repo, 'branch': branch, 'sha': self.readback_override or self.remote} if self.remote else None)

    def push_proposal_branch(self, repo, branch, head, pid):
        self.calls.append(('push', repo, branch)); self.writes.append(('push', head)); self.remote = head

    def get_pr(self, repo, branch):
        self.calls.append(('read_pr', repo, branch)); return self.result(self.pr)

    def open_draft_pr(self, repo, branch, pid):
        self.calls.append(('draft', repo, branch)); self.writes.append(('draft', 1))
        self.pr = {'repository': repo, 'branch': branch, 'head_sha': self.remote,
            'base_ref': 'main', 'draft': True, 'number': 1, 'auto_merge': None, 'state': 'open'}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = ManagerStore(Path(self.tmp.name) / 'journal.db'); canonical(self.store)
        pkg = package(self.store, 'a'*40, tests=sorted(REQUIRED_TESTS))
        self.value = new_preview(pkg, configured_repo('a'*40), NOW, 'camera-cta-fr')
        head = 'b'*40
        self.value.update(head_sha=head, state='PREVIEW_PENDING', stale_state='CURRENT',
            build_state='PASS', test_state='PASS', build_result={'state':'PASS','head_sha':head},
            tests={k:{'state':'PASS','head_sha':head} for k in REQUIRED_TESTS})
        self.store.save_preview(self.value)
        self.binding = {k:self.value[k] for k in BINDING_FIELDS}
        self.boundary = PreviewWriteBoundary(**{k:v for k,v in self.binding.items() if k!='branch'},
            allowed_branch=self.binding['branch'], selected_repositories=(REPO,), permissions=deepcopy(PERMISSIONS),
            verified_at=NOW.isoformat(), free_plan_limit_accepted=True, non_main_deployment_safe=True,
            production_credentials_available=False, enabled=True)
        self.provider = Provider(self.binding)
        self.executor = ProposalPreviewExecutor(self.store, self.provider, self.boundary)

    def test_free_private_repository_can_push_once_and_create_one_draft_with_readback(self):
        first = self.executor.push_proposal(self.binding, NOW)
        draft = self.executor.create_draft_pr(self.binding, NOW)
        self.assertEqual(first['provider_writes'], 1); self.assertEqual(draft['provider_writes'], 1)
        self.assertFalse(first['force']); self.assertTrue(draft['draft'])
        self.assertEqual(self.provider.writes, [('push','b'*40),('draft',1)])
        self.assertEqual(self.provider.calls[3][0], 'read_branch')
        self.assertEqual(self.executor.push_proposal(self.binding, NOW)['provider_writes'], 0)
        self.assertEqual(self.executor.create_draft_pr(self.binding, NOW)['provider_writes'], 0)
        self.assertEqual(len(self.provider.writes), 2)

    def test_wrong_ref_repository_sha_revision_or_hash_rejected_before_provider_calls(self):
        changes = [{'branch':b} for b in ['main','master','refs/heads/main','optimization/other',self.binding['branch']+'-other', 'optimization/'+PID+'-x;touch']]
        changes += [{'repository':'evil/repo'},{'head_sha':'c'*40},{'base_sha':'c'*40},
            {'proposal_revision':2},{'proposal_hash':'f'*64},{'proposal_id':'f'*64}]
        for change in changes:
            for method in [self.executor.push_proposal,self.executor.create_draft_pr]:
                with self.subTest(change=change, method=method.__name__), self.assertRaises(ValueError):
                    method({**self.binding,**change},NOW)
        self.assertEqual(self.provider.calls, [])

    def test_force_delete_and_merge_are_not_exposed(self):
        for field in ['force','delete','merge','refspec','command']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.executor.push_proposal({**self.binding,field:True},NOW)
        for operation in ['merge','merge_pull_request','delete_branch','dispatch_workflow','deploy_production']:
            self.assertFalse(hasattr(self.executor,operation))
        self.assertEqual(self.provider.calls, [])

    def test_boolean_revision_and_truthy_control_strings_are_rejected(self):
        with self.assertRaises(ValueError):self.executor.push_proposal({**self.binding,'proposal_revision':True},NOW)
        for field in ['main_protected','free_plan_limit_accepted','non_main_deployment_safe','production_credentials_available','enabled']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                ProposalPreviewExecutor(self.store,self.provider,replace(self.boundary,**{field:'false'})).push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.calls, [])

    def test_identity_excess_missing_or_all_repositories_fail_before_calls(self):
        changes = [dict(selected_repositories=(REPO,'evil/repo')), dict(selected_repositories=()),
            dict(permissions={**PERMISSIONS,'secrets':'read'}), dict(permissions={**PERMISSIONS,'administration':'read'}),
            dict(permissions={k:v for k,v in PERMISSIONS.items() if k!='checks'}),
            dict(production_credentials_available=True), dict(enabled=False), dict(non_main_deployment_safe=False),
            dict(free_plan_limit_accepted=False), dict(verified_at=(NOW-timedelta(minutes=16)).isoformat())]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(PermissionError):
                ProposalPreviewExecutor(self.store,self.provider,replace(self.boundary,**change)).push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.calls, [])

    def test_unrelated_existing_remote_ref_is_not_overwritten(self):
        self.provider.remote = 'c'*40
        with self.assertRaises(ValueError):self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.writes, [])

    def test_remote_write_readback_must_match_exact_sha(self):
        self.provider.readback_override = 'c'*40
        with self.assertRaises(ValueError):self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(len(self.provider.writes), 1)

    def test_main_movement_blocks_push_and_draft(self):
        self.provider.main_sha = 'c'*40
        for method in [self.executor.push_proposal,self.executor.create_draft_pr]:
            with self.assertRaises(ValueError):method(self.binding,NOW)
        self.assertEqual(self.provider.writes, [])

    def test_provider_denial_or_partial_cannot_prove_remote_absence(self):
        self.provider.remote = 'b'*40
        for state in ['BLOCKED_AUTH','PARTIAL']:
            self.provider.read_state = state
            with self.subTest(state=state), self.assertRaises(PermissionError):
                self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.writes, [])

    def test_missing_wrong_head_test_evidence_blocks_before_calls(self):
        for bad in [{'state':'FAIL','head_sha':'b'*40},{'state':'PASS','head_sha':'c'*40}]:
            value=deepcopy(self.value); value['tests']['SECRET_SCAN']=bad; self.store.save_preview(value)
            with self.subTest(bad=bad), self.assertRaises(PermissionError):self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.calls, [])

    def test_canonical_revision_change_blocks_before_provider_calls(self):
        canonical(self.store,revision=2)
        with self.assertRaises(ValueError):self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.calls, [])

    def test_protected_source_paths_cannot_enter_execution_package(self):
        for path in ['../sitegen.py','.github/workflows/deploy.yml','wrangler.jsonc','dist/index.html','assets/secret.txt']:
            value=deepcopy(self.value); value['package']['allowed_files']=[path]; value['package']['changes'][0]['path']=path
            self.store.save_preview(value)
            with self.subTest(path=path), self.assertRaises(ValueError):self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.calls, [])

    def test_non_draft_wrong_sha_closed_or_auto_merge_pr_is_rejected(self):
        self.executor.push_proposal(self.binding,NOW); self.executor.create_draft_pr(self.binding,NOW)
        baseline=deepcopy(self.provider.pr)
        for changes in [{'draft':False},{'head_sha':'c'*40},{'base_ref':'master'},{'auto_merge':{}},{'state':'closed'}]:
            self.provider.pr={**baseline,**changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):self.executor.create_draft_pr(self.binding,NOW)
        self.assertEqual(len(self.provider.writes), 2)

    def test_revision_changed_during_remote_read_blocks_write(self):
        original=self.provider.get_branch
        def changed(repo,branch):
            read=original(repo,branch)
            if branch==self.binding['branch']:canonical(self.store,revision=2)
            return read
        self.provider.get_branch=changed
        with self.assertRaises(ValueError):self.executor.push_proposal(self.binding,NOW)
        self.assertEqual(self.provider.writes, [])
