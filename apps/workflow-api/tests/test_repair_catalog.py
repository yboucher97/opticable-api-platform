from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest
import tempfile

from test_operational_recovery import NOW, grant as development_grant
from workflow.automation.acquisition_store import digest
from workflow.automation.repair_catalog import validate_catalog, check_standing_permission, exercise_playbook
from workflow.automation.operational_recovery import DevelopmentScope


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((Path(__file__).resolve().parents[3]/'ops/phase14/production_repair_catalog.json').read_text())

    def test_proposal_is_small_machine_readable_and_disabled(self):
        self.assertEqual(len(validate_catalog(self.catalog)['playbooks']), 3)
        self.assertFalse(self.catalog['permissions_enabled'])
        for row in self.catalog['playbooks']:
            self.assertFalse(row['enabled']);self.assertFalse(row['approval']['approved'])
            self.assertIsNone(row['approval']['expires_at'])
            with self.assertRaises(ValueError):check_standing_permission(self.catalog, row['id'], {},
                expected_digest=digest(self.catalog), now=NOW, evidence={})

    def test_catalog_cannot_expand_services_actions_or_budgets(self):
        for key, value in [('services', ['caddy.service']), ('actions', [['/bin/sh']]),
                           ('maximum_attempts', 2), ('maximum_attempts', True),
                           ('execution_timeout_seconds', 999), ('cooldown_seconds', 0)]:
            c = deepcopy(self.catalog);c['playbooks'][0][key] = value
            with self.assertRaises(ValueError):validate_catalog(c)

    def test_flipping_enabled_bits_alone_is_not_authority(self):
        self.catalog['permissions_enabled'] = True;self.catalog['playbooks'][0]['enabled'] = True
        with self.assertRaises(ValueError):check_standing_permission(self.catalog, 'refresh-local-readiness', {},
            expected_digest=digest(self.catalog), now=NOW, evidence={})

    def test_future_grant_expiry_and_exact_binding_are_enforced_without_execution(self):
        c = self.catalog;c['permissions_enabled'] = True;c['playbooks'][0]['enabled'] = True
        h = digest(c)
        grant = dict(approved=True, authority='OWNER_EXACT_STANDING_REPAIR', catalog_sha256=h,
            playbook_id='refresh-local-readiness', service='optibrain-resource-sample.service',
            starts_at=(NOW-timedelta(seconds=1)).isoformat(), expires_at=(NOW+timedelta(hours=1)).isoformat(), root_verified=True, operation_id='fixture-operation-1')
        evidence = dict.fromkeys(('executor_root_pin_verified','45_flags_off','protected_settings_unchanged',
            'no_inflight_business_effects','no_recovery_hold','fresh_preconditions_verified',
            'exact_configuration_checkpoint_verified','existing_audit_ready'), True)
        self.assertFalse(check_standing_permission(c, grant['playbook_id'], grant,
            expected_digest=h, now=NOW, evidence=evidence, operation_id='fixture-operation-1')['production_execution_performed'])
        for key, value in [('expires_at', NOW.isoformat()), ('expires_at', (NOW+timedelta(days=8)).isoformat()),
                           ('service', 'caddy.service'), ('root_verified', False)]:
            bad = {**grant, key: value}
            with self.assertRaises(ValueError):check_standing_permission(c, grant['playbook_id'], bad,
                expected_digest=h, now=NOW, evidence=evidence, operation_id='fixture-operation-1')
        with self.assertRaises(ValueError):check_standing_permission(c, grant['playbook_id'], grant,
            expected_digest=h, now=NOW, evidence={**evidence, 'no_recovery_hold': False}, operation_id='fixture-operation-1')


class ExecutionExercises(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        development_grant(self.root);self.scope=DevelopmentScope(self.root)
        self.catalog=json.loads((Path(__file__).resolve().parents[3]/'ops/phase14/production_repair_catalog.json').read_text())

    def permit(self,kind,service,identity='fixture-operation-1'):
        return dict(authority='OWNER_ISOLATED_EXPERIMENT',playbook_id=kind,service=service,
                    operation_id=identity,expires_at=(NOW+timedelta(minutes=30)).isoformat())

    def run_fixture(self,p,**kw):
        return exercise_playbook(self.scope,self.catalog,p,now=NOW,**kw)

    def test_readiness_fixture_reuses_writer_preserves_source_time_and_recovers_bad_output(self):
        self.scope.write('observations/readiness.json',json.dumps({'source_at':'2026-10-01T00:00:00Z','healthy':True}).encode())
        p=self.permit('refresh-local-readiness','optibrain-resource-sample.service')
        self.assertEqual(self.run_fixture(p)['state'],'VERIFIED')
        self.assertEqual(json.loads((self.root/'derived/status.json').read_text())['source_at'],'2026-10-01T00:00:00Z')
        self.assertEqual(self.run_fixture(p)['state'],'ALREADY_FINAL')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);development_grant(root);scope=DevelopmentScope(root)
            scope.write('observations/readiness.json',b'{"source_at":"old"}')
            scope.write('derived/status.json',b'{"prior_good":true}')
            result=exercise_playbook(scope,self.catalog,p,now=NOW,fault='fail')
            self.assertEqual(result['state'],'FAILED');self.assertTrue(result['result']['prior_snapshot_restored'])
            self.assertEqual((root/'derived/status.json').read_bytes(),b'{"prior_good":true}')

    def test_support_restart_changes_actual_fixture_state_once_and_obeys_cooldown(self):
        for i,service in enumerate(['opticable-password-pdf.service','opticable-omada-site.service']):
            p=self.permit('restart-contained-support',service,'fixture-operation-'+str(i))
            result=self.run_fixture(p);self.assertEqual(result['state'],'VERIFIED')
            self.assertEqual(result['result']['starts'],1)
            self.assertEqual(self.run_fixture(p)['state'],'ALREADY_FINAL')
            another={**p,'operation_id':'another-operation-'+str(i)}
            self.assertEqual(self.run_fixture(another)['state'],'COOLDOWN')
        self.assertFalse(self.catalog['permissions_enabled'])

    def test_stalled_fixture_stops_and_cannot_repeat_ambiguous_effect(self):
        p=self.permit('restart-contained-support','opticable-password-pdf.service')
        self.assertEqual(self.run_fixture(p,fault='stall',timeout=.05)['state'],'FAILED')
        self.assertEqual(self.run_fixture(p)['state'],'ALREADY_FINAL')
        self.assertEqual(self.run_fixture({**p,'operation_id':'another-fixture-operation'})['state'],'RECOVERY_HOLD')

    def test_production_service_or_expired_operation_permit_is_refused(self):
        p=self.permit('restart-contained-support','caddy.service')
        with self.assertRaises(ValueError):self.run_fixture(p)
        p=self.permit('refresh-local-readiness','optibrain-resource-sample.service');p['expires_at']=NOW.isoformat()
        with self.assertRaises(ValueError):self.run_fixture(p)
        self.assertFalse((self.root/'state.sqlite').exists())

    def test_catalog_rollback_uses_existing_supervisor_and_preserves_newer_rows(self):
        from test_release_recovery import ReleaseFixture
        f=ReleaseFixture(self.root);p=self.permit('exact-approved-release-rollback','opticable-workflow-api.service')
        result=self.run_fixture(p,supervisor=f.supervisor())
        self.assertEqual(result['state'],'VERIFIED');self.assertEqual(len(f.business_rows()),2)
        self.assertFalse(result['production_execution_performed'])
