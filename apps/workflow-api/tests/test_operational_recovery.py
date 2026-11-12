from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.action_evidence import ActionEvidence, envelope
from workflow.automation.operational_recovery import (
    DevelopmentScope, RecoveryCoordinator, DerivedStatus, OrphanedLock, RULE, diagnose, observations_from_operations)

NOW = datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)


def grant(root, now=NOW):
    value = dict(root=str(root), rule=RULE, environment='isolated-development', production_allowed=False,
                 issued_at=(now - timedelta(minutes=1)).isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())
    p = root / '.optibrain-development.json';p.write_text(json.dumps(value));p.chmod(0o600)
    return p


def observed(symptom='DERIVED_REPORT_MISSING', operation='fixture-operation'):
    return dict(operation_id=operation, service='fixture', symptom=symptom,
                observed_at=NOW.isoformat(), evidence_ref='fixture:source:1', evidence_sha256='e' * 64)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root = Path(t.name);grant(self.root)
        self.scope = DevelopmentScope(self.root)
        self.coordinator = RecoveryCoordinator(self.scope, now=NOW)

    def repair(self, observation=None, params=None, now=NOW):
        return self.coordinator.repair(observation or observed(), params if params is not None else {'expected': {'healthy': True}}, now=now)

    def events(self, kind=None):
        with self.coordinator.audit.connect(readonly=True) as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT evidence_json FROM action_evidence WHERE kind='universal_event'")]
        return [v for v in rows if kind is None or v.get('event') == kind]

    def test_actual_missing_report_repaired_and_verified(self):
        result = self.repair()
        self.assertEqual(result['state'], 'REPAIRED')
        self.assertEqual(json.loads((self.root / 'derived/status.json').read_text()), {'healthy': True})
        self.assertTrue(result['verified'])
        self.assertTrue(self.coordinator.audit.verify_integrity(result['action_id']))

    def test_existing_operations_adapter_classifies_without_collecting_or_repairing_production(self):
        status = dict(at=NOW.timestamp(), alerts=[dict(incident='dlq-review', service='queue'),
            dict(incident='service:opticable-workflow-api.service', service='opticable-workflow-api.service')], repairs=[])
        values = observations_from_operations(status, evidence_ref='existing:operations-status.json', now=NOW)
        self.assertEqual([v['symptom'] for v in values], ['HISTORICAL_FAILURE', 'PRODUCTION_SERVICE_UNHEALTHY'])
        for value in values:self.assertEqual(self.repair(value, {})['state'], 'DIAGNOSIS_ONLY')
        self.assertEqual(self.coordinator._plans(), [])
        with self.assertRaises(ValueError):observations_from_operations(status, evidence_ref='fixture', now=NOW + timedelta(hours=1))

    def test_idempotent_repeat_creates_no_second_repair(self):
        self.repair();result = self.repair(now=NOW + timedelta(minutes=2))
        self.assertEqual(result['state'], 'ALREADY_HEALTHY')
        self.assertEqual(len(self.coordinator._plans()), 1)

    def test_corrupt_derived_preimage_is_preserved(self):
        p = self.root / 'derived';p.mkdir();(p / 'status.json').write_bytes(b'fixture-corrupt')
        result = self.repair()
        before = self.root / ('evidence/' + result['action_id'] + '.before')
        self.assertEqual(before.read_bytes(), b'fixture-corrupt')

    def test_exact_operation_binding_cannot_change(self):
        self.repair()
        result = self.repair(params={'expected': {'healthy': False}}, now=NOW + timedelta(minutes=2))
        self.assertEqual(result['state'], 'BINDING_CONFLICT')
        self.assertEqual(json.loads((self.root / 'derived/status.json').read_text()), {'healthy': True})

    def test_failed_recovery_creates_one_incident(self):
        with patch.object(DerivedStatus, 'verify', return_value=False):
            self.assertEqual(self.repair()['state'], 'FAILED')
            self.assertEqual(self.repair(now=NOW + timedelta(seconds=1))['state'], 'COOLDOWN')
        self.assertEqual(len(self.events('OPERATIONAL_INCIDENT_CREATED')), 1)

    def test_two_failures_open_circuit_and_never_loop(self):
        with patch.object(DerivedStatus, 'verify', return_value=False):
            self.assertEqual(self.repair()['state'], 'FAILED')
            self.assertEqual(self.repair(now=NOW + timedelta(seconds=61))['state'], 'FAILED')
            self.assertEqual(self.repair(now=NOW + timedelta(seconds=122))['state'], 'CIRCUIT_OPEN')
        self.assertEqual(len(self.coordinator._plans()), 2)
        self.assertEqual(len(self.events('OPERATIONAL_INCIDENT_CREATED')), 1)

    def test_global_three_attempt_limit_covers_different_operations(self):
        with patch.object(DerivedStatus, 'verify', return_value=False):
            for i in range(3):
                self.assertEqual(self.repair(observed(operation='fixture-' + str(i)), now=NOW + timedelta(seconds=i * 61))['state'], 'FAILED')
            self.assertEqual(self.repair(observed(operation='fixture-fourth'), now=NOW + timedelta(minutes=5))['state'], 'CIRCUIT_OPEN')

    def test_exclusive_execution_lock_prevents_second_controller(self):
        with self.scope.lock():
            with self.assertRaises(BlockingIOError):self.repair()
        self.assertEqual(self.coordinator._plans(), [])

    def test_scope_expiry_fails_before_repair(self):
        with self.assertRaises(ValueError):self.repair(now=NOW + timedelta(days=1))
        self.assertFalse((self.root / 'derived').exists())

    def test_missing_grant_cannot_initialize_journal(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            with self.assertRaises(FileNotFoundError):RecoveryCoordinator(DevelopmentScope(root), now=NOW)
            self.assertFalse((root / 'state.sqlite').exists())

    def test_writable_by_others_workspace_cannot_grant_repair(self):
        self.root.chmod(0o777)
        try:
            with self.assertRaises(ValueError):self.repair()
        finally:self.root.chmod(0o700)
        self.assertFalse((self.root / 'derived').exists())

    def test_production_paths_root_and_symlink_scope_are_refused(self):
        for root in ('/opt/opticable-api-platform', '/etc/optibrain', '/var/lib/optibrain', '/'):
            with self.assertRaises(ValueError):DevelopmentScope(root)
        with patch('workflow.automation.operational_recovery.os.geteuid', return_value=0):
            with self.assertRaises(ValueError):DevelopmentScope(self.root)
        link = self.root / 'linked';link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):DevelopmentScope(link)

    def test_symlink_artifact_is_refused_before_effect(self):
        target = self.root / 'business.sqlite';target.write_bytes(b'unique-history')
        (self.root / 'derived').mkdir();(self.root / 'derived/status.json').symlink_to(target)
        with self.assertRaises(ValueError):self.repair()
        self.assertEqual(target.read_bytes(), b'unique-history')

    def test_production_or_security_observation_does_not_grant_repair(self):
        for symptom in ('SCOPE_MISSING', 'AUTH_REJECTED', 'HISTORICAL_FAILURE', 'SOFTWARE_DEFECT', 'UNKNOWN'):
            result = self.repair(observed(symptom, symptom))
            self.assertEqual(result['state'], 'DIAGNOSIS_ONLY');self.assertFalse(result['executed'])
        self.assertEqual(self.coordinator._plans(), [])

    def test_stale_and_future_observation_are_not_repeated_evidence(self):
        for at in (NOW - timedelta(days=2), NOW + timedelta(seconds=1)):
            value = observed();value['observed_at'] = at.isoformat()
            with self.assertRaises(ValueError):self.repair(value)

    def test_learning_has_provenance_outcome_and_no_business_promotion(self):
        result = self.repair();learning = self.events('OPERATIONAL_LEARNING')[0]['value']
        self.assertEqual(learning['action_id'], result['action_id']);self.assertTrue(learning['verified'])
        self.assertFalse(learning['reuse_eligible']);self.assertEqual(learning['business_impact'], 'NOT_MEASURED')
        self.assertIn('tests', learning);self.assertIn('cause_class', learning)
        with self.coordinator.audit.connect(readonly=True) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM manager_receipts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM manager_learning').fetchone()[0], 0)

    def test_newer_business_rows_are_preserved(self):
        with sqlite3.connect(self.root / 'state.sqlite') as db:
            db.execute('CREATE TABLE business_history(id PRIMARY KEY,value)')
            db.execute('INSERT INTO business_history VALUES(1,"unique")')
        self.repair()
        with sqlite3.connect(self.root / 'state.sqlite') as db:
            self.assertEqual(db.execute('SELECT * FROM business_history').fetchall(), [(1, 'unique')])

    def test_orphaned_lock_requires_dead_owner_and_retains_evidence(self):
        (self.root / 'locks').mkdir(exist_ok=True)
        p = self.root / 'locks/read-job.lock';p.write_text(json.dumps({'owner_pid': 99999999}))
        before = p.read_bytes();result = self.repair(observed('ORPHANED_DEV_LOCK'), {})
        self.assertEqual(result['state'], 'REPAIRED');self.assertFalse(p.exists())
        self.assertEqual((self.root / ('evidence/' + result['action_id'] + '.orphaned-lock')).read_bytes(), before)

    def test_alive_owner_and_independent_file_handle_block_lock_repair(self):
        (self.root / 'locks').mkdir(exist_ok=True)
        p = self.root / 'locks/read-job.lock';p.write_text(json.dumps({'owner_pid': os.getpid()}))
        self.assertEqual(self.repair(observed('ORPHANED_DEV_LOCK'), {})['state'], 'FAILED')
        self.assertTrue(p.exists())
        p.write_text(json.dumps({'owner_pid': 99999999}))
        with p.open('r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.repair(observed('ORPHANED_DEV_LOCK', 'second-lock'), {}, now=NOW + timedelta(minutes=2))['state'], 'FAILED')
        self.assertTrue(p.exists())

    def test_interrupted_verified_effect_is_reconciled_without_reexecution(self):
        value = observed();diagnosis = diagnose(value, NOW);key = diagnosis['incident_key']
        from workflow.automation.acquisition_store import digest
        binding = digest(['rebuild-derived-status', {'expected': {'healthy': True}}])
        aid = 'repair:' + key + ':1'
        plan = envelope(aid, 'NONPROD_REPAIR', {'type': 'LOCAL_DERIVED_ARTIFACT', 'identity': 'fixture'}, NOW,
            exact_versions={'environment': 'isolated-development', 'incident_key': key, 'parameter_hash': binding})
        self.coordinator.audit.plan(plan, NOW);self.coordinator.audit.start(aid, NOW, authority_check=lambda: None)
        (self.root / 'derived').mkdir();(self.root / 'derived/status.json').write_text('{"healthy":true}\n')
        with patch.object(DerivedStatus, 'execute', side_effect=AssertionError('must not replay')):
            result = self.repair(now=NOW + timedelta(minutes=2))
        self.assertEqual(result['state'], 'RECONCILED');self.assertFalse(result['executed'])

    def test_interrupted_unknown_effect_stays_held_across_later_cycles(self):
        from workflow.automation.acquisition_store import digest
        key = diagnose(observed(), NOW)['incident_key'];aid = 'repair:' + key + ':1'
        plan = envelope(aid, 'NONPROD_REPAIR', {'type': 'LOCAL_DERIVED_ARTIFACT', 'identity': 'fixture'}, NOW,
            exact_versions={'environment': 'isolated-development', 'incident_key': key,
                            'parameter_hash': digest(['rebuild-derived-status', {'expected': {'healthy': True}}])})
        self.coordinator.audit.plan(plan, NOW);self.coordinator.audit.start(aid, NOW, authority_check=lambda: None)
        with patch.object(DerivedStatus, 'execute', side_effect=AssertionError('must not retry')):
            self.assertEqual(self.repair(now=NOW + timedelta(minutes=2))['state'], 'AMBIGUOUS_NO_RETRY')
            self.assertEqual(self.repair(now=NOW + timedelta(minutes=4))['state'], 'AMBIGUOUS_NO_RETRY')


if __name__ == '__main__':unittest.main()
