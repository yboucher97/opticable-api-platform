"""The release refreshes internal pins while retaining closed customer authority."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

spec = importlib.util.spec_from_file_location('lifecycle_truth_stage',
    Path(__file__).resolve().parents[3] / 'ops/lifecycle_truth/stage_runtime.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

class LifecycleTruthReleasePreservationTests(unittest.TestCase):
    def setUp(self):
        def require(ok, reason):
            if not ok: raise ValueError(reason)
        self.helper = SimpleNamespace(require=require, INTERNAL_SCOPES={'original'},
            INTERNAL_SOURCES={'i.py'}, trusted=lambda p: p.read_bytes(),
            digest=lambda b: __import__('hashlib').sha256(b).hexdigest())
        self.prior = {'internal_policy': {'lifecycle': {'enabled': True,
            'real_scopes': ['original'], 'test_scopes': [], 'source_hashes': {'i.py': 'old'},
            'expires_at': 'original-expiry', 'activated_at': 'original-cutoff'}},
            'customer_policy': {'external_enabled': False, 'test_enabled': False,
                'real_scopes': ['historically-approved'], 'test_scopes': [],
                'source_hashes': {'c.py': 'unchanged'}, 'expires_at': 'original-expiry'},
            'internal_activation': {'release_sha': 'old', 'activated_at': 'original-cutoff',
                'run': 'original-run', 'scopes': ['original']},
            'internal_effects': {'claim': {'state': 'succeeded'}},
            'customer_effects': {'send': {'state': 'succeeded'}}}
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / ('a' * 40) / 'source'
        files = self.source / 'apps/workflow-api/workflow'; files.mkdir(parents=True)
        (files / 'i.py').write_text('reviewed source')

    def test_closed_customer_policy_is_preserved_exactly(self):
        before = deepcopy(self.prior)
        internal, customer, activation = stage.preserved(self.prior, self.source, self.helper)
        self.assertEqual(self.prior, before)
        self.assertEqual(customer, before['customer_policy'])
        old = before['internal_policy']['lifecycle']
        self.assertEqual({k: v for k, v in internal['lifecycle'].items() if k != 'source_hashes'},
                         {k: v for k, v in old.items() if k != 'source_hashes'})
        self.assertEqual(activation, {**before['internal_activation'], 'release_sha': 'a' * 40})

    def test_customer_reopening_is_rejected(self):
        for field in ('external_enabled', 'test_enabled'):
            with self.subTest(field=field):
                prior = deepcopy(self.prior); prior['customer_policy'][field] = True
                with self.assertRaises(ValueError): stage.preserved(prior, self.source, self.helper)

    def test_internal_expansion_and_test_authority_are_rejected(self):
        for field in ('real_scopes', 'test_scopes'):
            with self.subTest(field=field):
                prior = deepcopy(self.prior); prior['internal_policy']['lifecycle'][field].append('new')
                with self.assertRaises(ValueError): stage.preserved(prior, self.source, self.helper)
