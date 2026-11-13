from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest

from test_operational_recovery import NOW
from workflow.automation.acquisition_store import digest
from workflow.automation.repair_catalog import validate_catalog, check_standing_permission


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
            starts_at=(NOW-timedelta(seconds=1)).isoformat(), expires_at=(NOW+timedelta(hours=1)).isoformat(), root_verified=True)
        evidence = dict.fromkeys(('executor_root_pin_verified','45_flags_off','protected_settings_unchanged',
            'no_inflight_business_effects','no_recovery_hold','fresh_preconditions_verified',
            'exact_configuration_checkpoint_verified','existing_audit_ready'), True)
        self.assertFalse(check_standing_permission(c, grant['playbook_id'], grant,
            expected_digest=h, now=NOW, evidence=evidence)['production_execution_performed'])
        for key, value in [('expires_at', NOW.isoformat()), ('expires_at', (NOW+timedelta(days=8)).isoformat()),
                           ('service', 'caddy.service'), ('root_verified', False)]:
            bad = {**grant, key: value}
            with self.assertRaises(ValueError):check_standing_permission(c, grant['playbook_id'], bad,
                expected_digest=h, now=NOW, evidence=evidence)
        with self.assertRaises(ValueError):check_standing_permission(c, grant['playbook_id'], grant,
            expected_digest=h, now=NOW, evidence={**evidence, 'no_recovery_hold': False})
