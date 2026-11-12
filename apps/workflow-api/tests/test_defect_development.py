from datetime import timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_operational_recovery import NOW, grant
from workflow.automation.operational_recovery import DevelopmentScope
from workflow.automation.defect_development import prepare_defect, git, run_regression

CODE = 'ops/connectivity_watch/check.py'
BAD = b'def dispatches_retry():\n return False\n'
FIXED = b'def dispatches_retry():\n return True\n'
REGRESSION = b'''import unittest,importlib.util
from pathlib import Path
root=Path(__file__).resolve().parents[3]
s=importlib.util.spec_from_file_location('fixture_watch',root/'ops/connectivity_watch/check.py')
watch=importlib.util.module_from_spec(s);s.loader.exec_module(watch)
class Regression(unittest.TestCase):
 def test_execution_path_dispatches_retry(self):self.assertTrue(watch.dispatches_retry())
'''


class DefectDevelopmentTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root = Path(t.name);grant(self.root);self.scope = DevelopmentScope(self.root)
        self.source = self.root / 'source';self.source.mkdir()
        git(self.source, 'init', '-q');git(self.source, 'config', 'user.name', 'fixture')
        git(self.source, 'config', 'user.email', 'fixture@localhost')
        p = self.source / CODE;p.parent.mkdir(parents=True);p.write_bytes(BAD)
        git(self.source, 'add', CODE);git(self.source, 'commit', '-qm', 'before diagnostic defect fix')
        self.sha = git(self.source, 'rev-parse', 'HEAD')

    def prepare(self, patch=None, test=REGRESSION):
        return prepare_defect(self.source, self.scope, patch if patch is not None else {CODE: FIXED},
                              test, source_sha=self.sha, github_read=self.github, now=NOW)

    def github(self, repository, sha):
        return dict(repository=repository, sha=sha, tree_sha=git(self.source, 'rev-parse', 'HEAD^{tree}'), authenticated_read=True)

    def test_real_paired_regression_creates_branch_commit_and_draft_request(self):
        result = self.prepare()
        self.assertEqual(result['state'], 'PREPARED')
        self.assertEqual(result['baseline']['failures'], 1)
        self.assertTrue(result['candidate_validation']['passed'])
        self.assertTrue(result['candidate_validation']['no_new_privileges'])
        self.assertTrue(result['branch'].startswith('repair/verified-defect-'))
        self.assertEqual(git(Path(result['candidate_checkout']), 'rev-parse', 'HEAD'), result['commit'])
        self.assertTrue(result['draft_pr_request']['draft'])
        self.assertFalse(result['pushed']);self.assertFalse(result['deployed'])
        self.assertEqual((self.source / CODE).read_bytes(), BAD)
        self.assertEqual(git(self.source, 'rev-parse', 'HEAD'), self.sha)

    def test_same_prepared_defect_is_idempotent(self):
        first = self.prepare();again = self.prepare()
        self.assertEqual(first['commit'], again['commit']);self.assertEqual(again['state'], 'ALREADY_PREPARED')

    def test_changed_prepared_branch_requires_review(self):
        result = self.prepare();(Path(result['candidate_checkout']) / CODE).write_bytes(BAD)
        with self.assertRaises(ValueError):self.prepare()

    def test_nonfix_does_not_create_a_proposed_branch(self):
        with self.assertRaises(ValueError):self.prepare({CODE: BAD})
        self.assertEqual(git(self.source, 'branch', '--list', 'repair/*'), '')

    def test_passing_baseline_is_not_a_verified_defect(self):
        test = REGRESSION.replace(b'self.assertTrue(watch.dispatches_retry())', b'self.assertTrue(True)')
        with self.assertRaises(ValueError):self.prepare(test=test)

    def test_import_error_is_not_accepted_as_reproduction(self):
        with self.assertRaises(ValueError):self.prepare(test=b'import missing_fixture_dependency\n')

    def test_skipped_or_networking_tests_cannot_authorize_a_branch(self):
        test = b'''import unittest,socket
class Bad(unittest.TestCase):
 def test_network(self):socket.create_connection(('example.invalid',443))
'''
        with self.assertRaises(ValueError):self.prepare(test=test)

    def test_safety_self_modification_and_business_paths_not_eligible(self):
        for path in ['apps/workflow-api/workflow/automation/mutation_control.py',
                     'apps/workflow-api/workflow/automation/operational_recovery.py',
                     'apps/workflow-api/workflow/automation/release_recovery.py',
                     'apps/workflow-api/workflow/automation/defect_development.py',
                     'deploy/manual-guarded-release.py', '.github/workflows/deploy.yml',
                     '../../outside.py', 'history.sqlite']:
            with self.assertRaises(ValueError):self.prepare({path: FIXED})

    def test_dirty_or_different_source_is_not_used(self):
        (self.source / CODE).write_bytes(FIXED)
        with self.assertRaises(ValueError):self.prepare()

    def test_source_production_checkout_is_refused(self):
        with self.assertRaises(ValueError):prepare_defect('/opt/opticable-api-platform', self.scope,
            {CODE: FIXED}, REGRESSION, source_sha=self.sha, github_read=self.github, now=NOW)

    def test_expired_scope_cannot_prepare_a_branch(self):
        with self.assertRaises(ValueError):prepare_defect(self.source, self.scope, {CODE: FIXED}, REGRESSION,
                                                        source_sha=self.sha, github_read=self.github, now=NOW + timedelta(days=1))

    def test_unverified_or_wrong_github_base_cannot_prepare_a_branch(self):
        with self.assertRaises(ValueError):prepare_defect(self.source, self.scope, {CODE: FIXED}, REGRESSION,
            source_sha=self.sha, github_read=lambda *args: {'authenticated_read': False}, now=NOW)


if __name__ == '__main__':unittest.main()
