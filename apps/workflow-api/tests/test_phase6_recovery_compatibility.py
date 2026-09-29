"""Pinned baseline and fixture-only persistent recovery; no live state/providers."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]

class RecoveryCompatibilityTests(unittest.TestCase):
    def test_baseline_read_and_corrected_forward_recovery_preserve_v2_state(self):
        spec = importlib.util.spec_from_file_location('fixture_recovery', ROOT / 'ops/phase6/recovery_compatibility.py')
        recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recovery)
        result = recovery.exercise()
        self.assertEqual(result['result'], 'PASS')
        self.assertFalse(result['direct_baseline_rollback_safe'])
        self.assertEqual(result['forward_recovery'], 'PASS')
        self.assertFalse(result['live_state_used'])
        for counter in ('provider_writes', 'customer_sends', 'books_mutations', 'crm_mutations', 'lead_conversions'):
            with self.subTest(counter=counter):
                self.assertEqual(result[counter], 0)
        self.assertTrue(result['phases'][2]['baseline_reads_v2'])
        self.assertFalse(result['phases'][2]['baseline_dispatch_safe'])
        self.assertTrue(result['phases'][3]['approval_states_preserved'])
        self.assertTrue(result['phases'][3]['queued_mutations_blocked'])
        self.assertTrue(result['phases'][3]['dedupe_preserved'])
