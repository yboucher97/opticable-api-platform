"""Exercise the actual universal transport boundary with exact root send grants."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation import customer_communications as domain
from workflow.automation import customer_send_control as control
from workflow.automation.lifecycle_control import LifecycleEffect, LifecycleJournal, digest
from workflow.automation.mutation_control import require_business_transport
from workflow.automation.remote_effects import FreshClaim


class CustomerTransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = object()
        self.now = datetime.now(timezone.utc)
        self.journal = LifecycleJournal(self.root / 'journal.db')
        self.objects = {}
        self.addCleanup(patch.stopall)
        patch.object(control.os, 'geteuid', return_value=0).start()
        patch.object(control, 'ROOT', self.root).start()
        patch.object(control, 'CONTROL', self.root / 'control.json').start()
        patch.object(control, 'trusted_json', side_effect=self.read).start()
        code = Path(control.__file__).resolve().parents[1]
        self.policy = {'schema': 1, 'external_enabled': False, 'test_enabled': True,
            'test_run': 'phase18-boundary-fixture', 'test_scopes': sorted(control.SCOPES), 'real_scopes': [],
            'activated_at': self.now.isoformat(), 'expires_at': (self.now + timedelta(hours=1)).isoformat(),
            'source_hashes': {name: hashlib.sha256((code / name).read_bytes()).hexdigest() for name in control.SOURCES},
            'phase18_checkpoint_sha256': None, 'per_family_limit': 10, 'per_cycle_limit': 4}
        self.objects[control.CONTROL] = self.policy
        self.baseline = {'modules': {'Leads': {'protected_versions': {'999': 'version'}}}}
        self.objects[control.BASELINE] = self.baseline
        self.lineage = {'records': {'103': {'ownership': 'REAL_NEW', 'run': 'real-internal-20261002-v1',
                                         'created_at': (self.now - timedelta(minutes=30)).isoformat()}}}
        self.activation = {'activated_at': (self.now - timedelta(hours=1)).isoformat()}
        self.objects[Path('/var/lib/optibrain/lifecycle/ownership.json')] = self.lineage
        self.objects[Path('/var/lib/optibrain/lifecycle/activation.json')] = self.activation

    def read(self, path, *args):
        if Path(path) not in self.objects:
            raise FileNotFoundError('Root authority unavailable')
        return self.objects[Path(path)]

    def fixture(self, mode='TEST_ONLY'):
        recipient = control.SENDER if mode == 'TEST_ONLY' else 'person@customer.ca'
        proof = {'mode': mode, 'lineage_verified': True, 'protected': False,
            'test_run': self.policy['test_run'], 'contact_id': '101', 'account_id': '102',
            'deal_id': '103', 'site_id': '104', 'contact_email': recipient,
            'contact_account_id': '102', 'deal_account_id': '102', 'deal_contact_id': '101',
            'deal_site_id': '104', 'site_account_id': '102', 'contact_version': 'cv1',
            'deal_version': 'dv1', 'site_version': 'sv1', 'observed_at': self.now.isoformat(),
            'language': 'fr', 'language_source': 'crm_preference', 'opt_out': False}
        context = {'contact_id': '101', 'account_id': '102', 'deal_id': '103', 'site_id': '104',
            'recipient_email': recipient, 'observed_at': self.now.isoformat(),
            'suppression_checked_at': self.now.isoformat(), **{key: False for key in domain.STOP_FLAGS},
            'object_id': '501', 'estimate_id': '501', 'estimate_number': 'EST-001',
            'finance_integrated': True, 'native_books_verified': True, 'native_crm_finance_verified': True,
            'finance_account_id': '102', 'finance_deal_id': '103', 'finance_site_id': '104',
            'status': 'sent', 'sent_at': (self.now - timedelta(days=14)).isoformat(),
            'expiry_date': (self.now + timedelta(days=30)).date().isoformat(), 'deal_active': True}
        planned = domain.plan_quote_reminder(context, proof, [], self.now, communications_enabled=True)
        self.assertEqual(planned['state'], 'READY')
        planned['message'] = {'fromAddress': control.SENDER, 'toAddress': planned['recipient'],
            'subject': planned['subject'], 'content': planned['body'], 'mailFormat': 'plaintext'}
        source = {'proof': proof, 'context': context, 'history': [], 'plan': planned,
                  'created_at': self.lineage['records']['103']['created_at'],
                  'lineage_run': 'real-internal-20261002-v1'}
        return source

    def enable_real(self):
        self.policy.update(external_enabled=True, test_enabled=False, test_scopes=[], real_scopes=sorted(control.SCOPES))
        proof = {'phase18': 'PASS', 'safety_critical_failures': 0, 'passed_families': sorted(control.SCOPES)}
        path = self.root / 'phase18-checkpoint.json'
        path.write_text(json.dumps(proof))
        self.objects[path] = proof
        self.policy['phase18_checkpoint_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def effect(self, source):
        plan = source['plan']
        operation = {'service': 'mail', 'method': 'POST',
            'path': '/api/accounts/' + control.MAIL_ACCOUNT + '/messages',
            'body': deepcopy(plan['message']), 'headers': {}, 'query': {}, 'content_type': 'application/json'}
        return LifecycleEffect('customer-boundary:' + plan['mode'] + ':' + plan['idempotency_key'],
                               operation, target_module='CustomerCommunication', target_id=plan['object_id'])

    def grant(self, source=None, *, scope=None, fresh=True, attempted=True, refresh=None):
        source = source or self.fixture()
        effect = self.effect(source)
        key = digest(source)
        self.source_path = self.root / 'sources' / (key + '.json')
        self.auth_path = self.root / 'authorizations' / (effect.action_id + '.json')
        self.objects[self.source_path] = source
        self.objects[self.auth_path] = {'action_id': effect.action_id, 'payload_hash': effect.payload_hash,
            'policy_hash': digest(self.policy), 'mode': source['plan']['mode'], 'scope': scope or source['plan']['family'],
            'source_key': key, 'source_hash': key, 'expires_at': (self.now + timedelta(minutes=2)).isoformat()}
        self.journal.intent(effect)
        if attempted:
            self.journal.append(effect, 'attempted', {})
        claim = FreshClaim(effect.action_id, effect.payload_hash, 'business-effects/v1/fixture/claim.json', fresh)
        context = control.exact_send(self.client, effect, claim, self.journal,
            mode=source['plan']['mode'], scope=scope or source['plan']['family'], authorization_path=self.auth_path,
            refresh=refresh or (lambda: deepcopy(source['plan'])))
        return effect, context

    def invoke(self, effect, *, recheck=False, client=None, operation=None):
        operation = operation or effect.payload
        return require_business_transport(self.client if client is None else client,
            operation['service'], operation['method'], operation['path'], operation['body'],
            operation['headers'], recheck=recheck, query=operation['query'], content_type=operation['content_type'])

    def test_exact_test_send_checks_both_boundary_stages_and_one_validation_only(self):
        effect, grant = self.grant()
        with grant:
            self.invoke(effect)
            self.invoke(effect, recheck=True)
            with self.assertRaises(ValueError):
                self.invoke(effect)
            with self.assertRaises(ValueError):
                self.invoke(effect, recheck=True)
        with self.assertRaises(ValueError):
            self.invoke(effect)

    def test_real_scope_is_independent_of_legacy_and_test_write_kills(self):
        self.enable_real()
        effect, grant = self.grant(self.fixture('REAL_NEW'))
        with grant:
            self.invoke(effect)
            self.invoke(effect, recheck=True)

    def test_wrong_real_recipient_cannot_hide_inside_a_forged_root_ready_plan(self):
        self.enable_real()
        source = self.fixture('REAL_NEW')
        source['plan']['message']['toAddress'] = 'wrong@customer.ca'
        source['plan']['recipient'] = 'wrong@customer.ca'
        effect, grant = self.grant(source)
        with grant, self.assertRaises(ValueError):
            self.invoke(effect)

    def test_forged_ready_cannot_bypass_every_suppression_or_wrong_native_link(self):
        changes = [{key: True} for key in domain.STOP_FLAGS]
        changes += [{'status': 'accepted'}, {'finance_deal_id': '999'}, {'recipient_email': 'wrong@customer.ca'}]
        self.enable_real()
        for change in changes:
            with self.subTest(change=change):
                source = self.fixture('REAL_NEW'); source['context'].update(change)
                effect, grant = self.grant(source)
                with grant, self.assertRaises(ValueError):
                    self.invoke(effect)

    def test_stale_provider_proof_or_unknown_language_cannot_claim_ready(self):
        for changes in ({'observed_at': (self.now - timedelta(minutes=6)).isoformat()},
                        {'language': None}, {'opt_out': None}, {'contact_account_id': '999'}):
            with self.subTest(changes=changes):
                source = self.fixture(); source['proof'].update(changes)
                effect, grant = self.grant(source)
                with grant, self.assertRaises(ValueError):
                    self.invoke(effect)

    def test_protected_record_denied_even_with_fake_root_new_lineage(self):
        self.baseline['modules']['Leads']['protected_versions']['103'] = 'protected-version'
        effect, grant = self.grant()
        with grant, self.assertRaisesRegex(ValueError, 'Protected'):
            self.invoke(effect)

    def test_scope_family_and_ownership_cannot_be_relabelled(self):
        effect, grant = self.grant(scope='customer.appointment.reminder')
        with grant, self.assertRaises(ValueError):
            self.invoke(effect)
        source = self.fixture(); source['plan']['mode'] = 'REAL_NEW'
        self.enable_real()
        effect, grant = self.grant(source)
        with grant, self.assertRaises(ValueError):
            self.invoke(effect)

    def test_external_kill_and_removed_scope_revoke_before_transport(self):
        self.enable_real()
        for field, value in (('external_enabled', False), ('real_scopes', [])):
            with self.subTest(field=field):
                self.enable_real()
                effect, grant = self.grant(self.fixture('REAL_NEW'))
                with grant:
                    self.invoke(effect)
                    self.policy[field] = value
                    with self.assertRaises(ValueError):
                        self.invoke(effect, recheck=True)

    def test_refresh_suppression_or_customer_changed_stops_actual_transport(self):
        for change in ({'state': 'SUPPRESSED'}, {'expected_native_bindings': {'deal_id': 'different'}},
                       {'idempotency_key': 'different-schedule-version'}):
            with self.subTest(change=change):
                source = self.fixture()
                refreshed = {**source['plan'], **change}
                effect, grant = self.grant(source, refresh=lambda: refreshed)
                with grant:
                    self.invoke(effect)
                    with self.assertRaises(ValueError):
                        self.invoke(effect, recheck=True)

    def test_changed_payload_provider_account_or_client_denied(self):
        effect, grant = self.grant()
        with grant:
            variants = []
            changed = deepcopy(effect.payload); changed['body']['content'] += '\nDifferent content'; variants.append(changed)
            changed = deepcopy(effect.payload); changed['path'] = '/api/accounts/123/messages'; variants.append(changed)
            changed = deepcopy(effect.payload); changed['headers'] = {'X-Additional-Recipient': 'customer@invalid.ca'}; variants.append(changed)
            for operation in variants:
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    self.invoke(effect, operation=operation)
            with self.assertRaises(ValueError):
                self.invoke(effect, client=object())

    def test_missing_root_authorization_or_source_and_stale_auth_denied(self):
        for missing in ('authorization', 'source', 'expired'):
            with self.subTest(missing=missing):
                effect, grant = self.grant()
                if missing == 'authorization':
                    del self.objects[self.auth_path]
                elif missing == 'source':
                    del self.objects[self.source_path]
                else:
                    self.objects[self.auth_path]['expires_at'] = (self.now - timedelta(seconds=1)).isoformat()
                with grant, self.assertRaises((ValueError, FileNotFoundError)):
                    self.invoke(effect)

    def test_changed_auth_or_source_digest_denied(self):
        for target in ('authorization', 'source'):
            with self.subTest(target=target):
                effect, grant = self.grant()
                if target == 'authorization':
                    self.objects[self.auth_path]['payload_hash'] = '0' * 64
                else:
                    self.objects[self.source_path]['context']['status'] = 'accepted'
                with grant, self.assertRaises(ValueError):
                    self.invoke(effect)

    def test_old_or_reference_real_deal_cannot_acquire_customer_authority(self):
        self.enable_real()
        for change in ({'created_at': (self.now - timedelta(days=30)).isoformat()},
                       {'ownership': 'REAL_REFERENCE'}, {'run': 'other-run'}):
            with self.subTest(change=change):
                self.lineage['records']['103'] = {'ownership': 'REAL_NEW', 'run': 'real-internal-20261002-v1',
                    'created_at': (self.now - timedelta(minutes=30)).isoformat(), **change}
                effect, grant = self.grant(self.fixture('REAL_NEW'))
                with grant, self.assertRaises(ValueError):
                    self.invoke(effect)

    def test_state_loss_existing_remote_claim_and_missing_attempt_never_grant_send(self):
        with self.assertRaises(ValueError):
            effect, grant = self.grant(fresh=False)
            with grant:
                pass
        # A fresh claim still needs the central durable attempted intent.
        self.journal = LifecycleJournal(self.root / 'another-journal.db')
        effect, grant = self.grant(attempted=False)
        with grant, self.assertRaises(ValueError):
            self.invoke(effect)

    def test_nonroot_and_nested_authority_are_denied(self):
        with patch.object(control.os, 'geteuid', return_value=1001), self.assertRaises(ValueError):
            effect, grant = self.grant()
            with grant:
                pass
        effect, grant = self.grant()
        with grant:
            with self.assertRaises(ValueError):
                other, nested = self.grant()
                with nested:
                    pass

    def test_test_recipient_cc_html_and_unbounded_or_injected_subject_denied(self):
        for index, changes in enumerate(({'toAddress': 'customer@customer.ca'}, {'ccAddress': control.SENDER},
                        {'mailFormat': 'html'}, {'subject': 'Customer subject'},
                        {'subject': '[OPTIBRAIN TEST]\r\nBcc: wrong@customer.ca'})):
            with self.subTest(changes=changes):
                self.journal = LifecycleJournal(self.root / ('malformed-' + str(index) + '.db'))
                source = self.fixture(); source['plan']['message'].update(changes)
                effect, grant = self.grant(source)
                with grant, self.assertRaises(ValueError):
                    self.invoke(effect)

    def test_customer_send_grant_has_no_books_crm_sign_or_workdrive_authority(self):
        effect, grant = self.grant()
        with grant:
            for service, path in (('zohoapis', '/books/v3/invoices'), ('zohoapis', '/books/v3/customerpayments'),
                                  ('zohoapis', '/crm/v8/Deals'), ('zohoapis', '/crm/v8/CustomModule5002'),
                                  ('zohoapis', '/workdrive/api/v1/files'), ('sign', '/requests')):
                with self.subTest(path=path):
                    operation = {**effect.payload, 'service': service, 'path': path, 'body': {'data': []}}
                    with self.assertRaises(ValueError):
                        self.invoke(effect, operation=operation)

    def test_policy_missing_expired_source_changed_or_unproven_family_denied(self):
        variants = ('missing', 'expired', 'source', 'unproven')
        for variant in variants:
            with self.subTest(variant=variant):
                self.enable_real()
                if variant == 'missing':
                    value = self.objects.pop(control.CONTROL)
                elif variant == 'expired':
                    self.policy['expires_at'] = (self.now - timedelta(seconds=1)).isoformat()
                elif variant == 'source':
                    value = deepcopy(self.policy['source_hashes'])
                    self.policy['source_hashes'][next(iter(self.policy['source_hashes']))] = '0' * 64
                else:
                    proof = self.objects[self.root / 'phase18-checkpoint.json']
                    proof['passed_families'] = []
                    path = self.root / 'phase18-checkpoint.json'; path.write_text(json.dumps(proof))
                    self.policy['phase18_checkpoint_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaises((ValueError, FileNotFoundError)):
                    control.policy()
                if variant == 'missing':
                    self.objects[control.CONTROL] = value
                elif variant == 'source':
                    self.policy['source_hashes'] = value
                self.policy['expires_at'] = (self.now + timedelta(hours=1)).isoformat()

    def test_real_test_clock_cannot_fast_forward_customer_send(self):
        self.enable_real()
        source = self.fixture('REAL_NEW')
        source['test_clock'] = (self.now + timedelta(days=10)).isoformat()
        effect, grant = self.grant(source)
        with grant, self.assertRaises(ValueError):
            self.invoke(effect)


if __name__ == '__main__':
    unittest.main()
