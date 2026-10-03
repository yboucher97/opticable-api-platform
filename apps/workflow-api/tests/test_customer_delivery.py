"""Focused sender tests use only fake providers and off-host object stores."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation import customer_delivery as delivery
from workflow.automation import customer_send_control as control
from workflow.automation import customer_communications as domain
from workflow.automation.lifecycle_control import LifecycleJournal
from workflow.automation.remote_effects import FreshClaim
from workflow.automation.mutation_control import require_business_transport, record_business_response
from tests.test_customer_communications import fixture, appointment


def response(data):
    return {'ok': True, 'status': 200, 'data': {'status': {'code': 200}, 'data': data}}


class Remote:
    def __init__(self):
        self.claims = {}; self.results = {}; self.claim_calls = 0; self.complete_calls = 0
        self.fail_claim = False
    def claim(self, effect):
        self.claim_calls += 1
        fresh = effect.action_id not in self.claims
        self.claims.setdefault(effect.action_id, {'action_id': effect.action_id, 'payload_hash': effect.payload_hash})
        if self.fail_claim: raise TimeoutError('Claim acknowledgment lost')
        return FreshClaim(effect.action_id, effect.payload_hash, 'business-effects/v1/' + effect.action_id + '/claim.json', fresh)
    def get(self, effect, kind):
        return (self.claims if kind == 'claim' else self.results).get(effect.action_id)
    def complete(self, effect, provider_id):
        self.complete_calls += 1
        self.results[effect.action_id] = {'provider_id': provider_id}


class Mail:
    def __init__(self, now):
        self.now = now; self.posts = 0; self.messages = {}; self.queries = []
        self.fail_after_success = False; self.fail_without_effect = False
        self.ambiguous_ack = False; self.hide_search = False; self.duplicate = False
        self.change = {}; self.header_change = {}; self.overlap_search = False
        self.malformed_read = False
    def request(self, service, method, path, *, body=None, query=None, **kwargs):
        if method == 'POST':
            require_business_transport(self, service, method, path, body)
            require_business_transport(self, service, method, path, body, recheck=True)
            self.posts += 1
            if self.fail_without_effect: raise TimeoutError('Provider outcome unknown')
            identity = str(1000 + self.posts)
            self.messages[identity] = {**body, 'messageId': identity, 'folderId': delivery.SENT_FOLDER,
                'receivedTime': str(int(self.now.timestamp() * 1000)), **self.change}
            if self.duplicate:
                self.messages['9999'] = {**self.messages[identity], 'messageId': '9999'}
            if self.fail_after_success: raise TimeoutError('Acknowledgment lost after success')
            result = response({} if self.ambiguous_ack else {'messageId': identity})
            record_business_response(result)
            return result
        if method != 'GET': raise AssertionError('Only Mail GET/one bounded POST may occur')
        if path.endswith('/messages/search'):
            self.queries.append(query)
            if self.malformed_read: return response({})
            rows = [] if self.hide_search else [{'messageId': i, 'folderId': m['folderId'],
                'subject': m['subject'], 'receivedTime': m['receivedTime']} for i, m in self.messages.items()]
            if self.overlap_search and rows: rows += rows
            return response(rows)
        identity = path.split('/')[-2]; message = self.messages[identity]
        if path.endswith('/details'): return response(message)
        if path.endswith('/content'): return response({'messageId': identity, 'content': message['content']})
        if path.endswith('/header'):
            return response({'headerContent': {'From': [message['fromAddress']], 'To': [message['toAddress']],
                'Subject': [message['subject']], 'Date': [format_datetime(self.now)],
                'Message-ID': ['<' + identity + '@mail.zoho.com>'], **self.header_change}})
        raise AssertionError('Unexpected provider path')


class CustomerDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        for directory in ('sources', 'authorizations'): (self.root / directory).mkdir(mode=0o700)
        (self.root / 'state.json').write_text(json.dumps({'schema': 1, 'created_at': '2026-10-03T00:00:00Z', 'effects': {}, 'holds': {}}))
        self.now = datetime.now(timezone.utc); self.mail = Mail(self.now); self.remote = Remote()
        self.journal = LifecycleJournal(self.root / 'journal.db')
        self.policy = {'schema': 1, 'external_enabled': False, 'test_enabled': True, 'test_run': 'phase18-test',
            'test_scopes': list(control.SCOPES), 'real_scopes': [], 'activated_at': self.now.isoformat(),
            'expires_at': (self.now + timedelta(hours=1)).isoformat(), 'source_hashes': {},
            'phase18_checkpoint_sha256': None, 'per_family_limit': 10, 'per_cycle_limit': 4}
        def read(path, *args):
            if path == control.BASELINE: return {'modules': {}}
            return json.loads(Path(path).read_text())
        self.patches = [patch.object(delivery.os, 'geteuid', return_value=0),
            patch.object(delivery, 'trusted_json', side_effect=read),
            patch.object(control, 'trusted_json', side_effect=read),
            patch.object(control, 'ROOT', self.root), patch.object(control, 'policy', side_effect=lambda: self.policy)]
        for item in self.patches: item.start()
        self.fixtures = {}; self.plan = self.proposal()
        self.sender = delivery.RootSender(self.mail, lambda: deepcopy(self.plan), root=self.root,
                                         journal=self.journal, remote=self.remote)
    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()
    def proposal(self, key='quote:200:1', family='customer.quote.reminder'):
        identifier = str(int(delivery.digest(key)[:8], 16))
        if family == 'customer.quote.reminder':
            context, proof = fixture(self.now, 'fr')
            context.update(object_id=identifier, estimate_id=identifier,
                sent_at=(self.now-timedelta(days=20)).isoformat(),
                expiry_date=(self.now+timedelta(days=20)).date().isoformat(),
                finance_integrated=False, source_kind='TEST_STATUS_EQUIVALENT', status_equivalent_fixture=True)
            plan = domain.plan_quote_reminder(context, proof, [], self.now, communications_enabled=True)
        elif family == 'customer.appointment.confirmation':
            context, proof = appointment(self.now, 'fr')
            context.update(object_id=identifier, installation_id=identifier,
                scheduled_at=(self.now+timedelta(days=2)).astimezone(domain.TORONTO).isoformat())
            plan = domain.plan_appointment_confirmation(context, proof, [], self.now, communications_enabled=True)
        else: raise AssertionError('Unexpected focused fixture family')
        self.assertEqual(plan['state'], 'READY')
        self.fixtures[plan['idempotency_key']] = (context, proof)
        return plan
    def source(self, plan=None):
        plan = plan or self.plan; context, proof = self.fixtures[plan['idempotency_key']]
        return {'proof': deepcopy(proof), 'context': deepcopy(context), 'history': self.sender.history(),
            'lineage_run': 'phase18-test', 'created_at': self.now.isoformat()}
    def send(self, **kwargs): return self.sender.send(deepcopy(self.plan), self.source(), now=self.now, **kwargs)

    def test_one_effect_and_replay_never_posts(self):
        first = self.send(); self.assertEqual(first['state'], 'VERIFIED')
        replay = self.send(); self.assertEqual(replay['state'], 'VERIFIED_REPLAY')
        self.assertEqual(self.mail.posts, 1); self.assertEqual(self.remote.claim_calls, 1)
        self.assertEqual(self.remote.complete_calls, 1)
        self.assertEqual(self.sender.history()[0]['status'], 'verified')
    def test_provider_success_lost_ack_reconciles_without_resend(self):
        self.mail.fail_after_success = True
        self.assertEqual(self.send()['state'], 'VERIFIED')
        self.assertEqual(self.send()['state'], 'VERIFIED_REPLAY')
        self.assertEqual(self.mail.posts, 1); self.assertFalse(self.sender.state['holds'])
    def test_explicit_test_ack_loss_uses_independent_search(self):
        self.assertEqual(self.send(lost_ack=True)['state'], 'VERIFIED')
        item = next(iter(self.sender.state['effects'].values()))
        self.assertNotIn('acknowledged_id', item); self.assertEqual(self.mail.posts, 1)
    def test_ambiguous_ack_is_verified_only_from_provider(self):
        self.mail.ambiguous_ack = True
        self.assertEqual(self.send()['state'], 'VERIFIED'); self.assertEqual(self.mail.posts, 1)
    def test_acknowledged_id_survives_search_index_delay(self):
        self.mail.hide_search = True
        self.assertEqual(self.send()['state'], 'VERIFIED'); self.assertEqual(self.mail.posts, 1)
    def test_missing_effect_stays_held_and_never_retries(self):
        self.mail.fail_without_effect = True
        self.assertEqual(self.send()['state'], 'HOLD'); self.assertEqual(self.send()['state'], 'HOLD')
        self.assertEqual(self.mail.posts, 1); self.assertEqual(self.remote.claim_calls, 1)
    def test_delayed_independent_recovery_clears_only_affected_hold(self):
        self.mail.fail_after_success = True; self.mail.hide_search = True
        self.assertEqual(self.send()['state'], 'HOLD'); self.mail.hide_search = False
        self.sender.state['holds']['customer.completion.message'] = {'other': {'reason': 'Independent issue'}}
        self.assertEqual(self.send()['state'], 'VERIFIED')
        self.assertNotIn('customer.quote.reminder', self.sender.state['holds'])
        self.assertIn('customer.completion.message', self.sender.state['holds']); self.assertEqual(self.mail.posts, 1)
    def test_duplicate_sent_effects_hold_family(self):
        self.mail.duplicate = True
        self.assertEqual(self.send()['state'], 'DUPLICATE')
        self.assertEqual(self.send()['state'], 'DUPLICATE'); self.assertEqual(self.mail.posts, 1)
        self.assertEqual(self.remote.complete_calls, 0)
    def test_wrong_recipient_provider_readback_is_not_success(self):
        self.mail.change = {'toAddress': 'other@opticable.ca'}
        self.assertEqual(self.send()['state'], 'HOLD'); self.assertEqual(self.remote.complete_calls, 0)
    def test_changed_body_subject_or_extra_recipients_deny_readback(self):
        for field, value in [('content', 'Other body'), ('subject', 'Other subject'),
                             ('ccAddress', 'other@opticable.ca'), ('bccAddress', 'other@opticable.ca'),
                             ('fromAddress', 'other@opticable.ca')]:
            with self.subTest(field=field):
                self.mail.change = {field: value}; self.plan = self.proposal('different:' + field)
                self.sender.effects_this_cycle = 0
                self.sender.state['holds'].clear()
                self.assertEqual(self.send()['state'], 'HOLD')
        self.assertEqual(self.remote.complete_calls, 0)
    def test_header_recipient_disagreement_is_not_success(self):
        self.mail.header_change = {'To': ['wrong@opticable.ca']}
        self.assertEqual(self.send()['state'], 'HOLD'); self.assertEqual(self.remote.complete_calls, 0)
    def test_wrong_time_cannot_be_mistaken_for_current_effect(self):
        self.mail.change = {'receivedTime': str(int((self.now - timedelta(hours=1)).timestamp() * 1000))}
        self.assertEqual(self.send()['state'], 'HOLD')
    def test_immediate_search_includes_recent_messages_and_starts_at_one(self):
        self.assertEqual(self.send()['state'], 'VERIFIED')
        self.assertGreater(self.mail.queries[0]['receivedTime'], int(self.now.timestamp() * 1000))
        self.assertEqual(self.mail.queries[0]['start'], 1)
    def test_lost_ack_after_utc_midnight_reconciles_previous_toronto_day_without_resend(self):
        # The mailbox applies local dates. An October 3 UTC attempt can still
        # be an October 2 Sent message; UTC-day-only filters lose its evidence.
        self.mail.fail_after_success = True; self.mail.hide_search = True
        self.assertEqual(self.send()['state'], 'HOLD')
        attempted = datetime(2026, 10, 3, 0, 6, tzinfo=timezone.utc)
        mailbox_day = attempted.astimezone(domain.TORONTO).date()
        self.assertNotEqual(mailbox_day, attempted.date())
        action_id, item = next(iter(self.sender.state['effects'].items()))
        item['attempted_at'] = attempted.isoformat(); self.sender.save()
        self.mail.now = attempted; self.mail.hide_search = False
        for message in self.mail.messages.values():
            message['receivedTime'] = str(int(attempted.timestamp() * 1000))
        original_request = self.mail.request
        def mailbox_local_search(service, method, path, **kwargs):
            if path.endswith('/messages/search'):
                terms = dict(part.split(':', 1) for part in kwargs['query']['searchKey'].split('::'))
                first = datetime.strptime(terms['fromDate'], '%d-%b-%Y').date()
                last = datetime.strptime(terms['toDate'], '%d-%b-%Y').date()
                if not first <= mailbox_day < last:
                    self.mail.queries.append(kwargs['query']); return response([])
            return original_request(service, method, path, **kwargs)
        self.mail.request = mailbox_local_search
        result = self.sender.reconcile(action_id, now=attempted + timedelta(seconds=30))
        self.assertEqual(result['state'], 'VERIFIED')
        self.assertEqual(self.send()['state'], 'VERIFIED_REPLAY')
        self.assertEqual(self.mail.posts, 1); self.assertEqual(self.remote.claim_calls, 1)
        self.assertEqual(self.remote.complete_calls, 1)
        self.assertFalse(self.sender.state['holds'])
    def test_before_claim_refresh_suppression_makes_no_attempt(self):
        self.sender.refresh = lambda: {'state': 'SUPPRESSED', 'family': self.plan['family']}
        self.assertEqual(self.send()['state'], 'SUPPRESSED')
        self.assertEqual(self.remote.claim_calls, 0); self.assertEqual(self.mail.posts, 0)
        self.assertFalse(self.sender.state['effects'])
    def test_same_recipient_with_changed_native_association_is_suppressed(self):
        changed = deepcopy(self.plan); changed['expected_native_bindings']['contact_id'] = '999'
        self.sender.refresh = lambda: changed
        self.assertEqual(self.send()['state'], 'SUPPRESSED')
        self.assertEqual(self.remote.claim_calls, 0); self.assertEqual(self.mail.posts, 0)
    def test_transport_refresh_suppression_is_known_not_attempted(self):
        calls = []
        def refresh():
            calls.append(True)
            return deepcopy(self.plan) if len(calls) == 1 else {'state': 'SUPPRESSED', 'family': self.plan['family']}
        self.sender.refresh = refresh
        self.assertEqual(self.send()['state'], 'SUPPRESSED'); self.assertEqual(self.mail.posts, 0)
        self.assertFalse(self.sender.state['holds'])
        self.assertEqual(self.sender.history()[0]['status'], 'suppressed')
    def test_own_inflight_intent_is_excluded_from_fresh_planner_history(self):
        lengths = []
        def refresh():
            lengths.append(len(self.sender.history())); return deepcopy(self.plan)
        self.sender.refresh = refresh
        self.assertEqual(self.send()['state'], 'VERIFIED'); self.assertEqual(lengths, [0, 0])
        self.assertIsNone(self.sender.inflight); self.assertEqual(len(self.sender.history()), 1)
    def test_old_uncertain_history_still_blocks_that_family(self):
        self.mail.fail_without_effect = True; self.assertEqual(self.send()['state'], 'HOLD')
        self.assertEqual(self.sender.history()[0]['status'], 'uncertain')
        self.plan = self.proposal('quote:201:1'); self.assertEqual(self.send()['state'], 'HOLD')
        self.assertEqual(self.mail.posts, 1)
    def test_global_customer_kill_does_not_authorize_transport(self):
        self.policy['test_enabled'] = False
        self.assertEqual(self.send()['state'], 'SUPPRESSED'); self.assertEqual(self.remote.claim_calls, 0)
    def test_family_scope_off_cannot_claim(self):
        self.policy['test_scopes'] = []
        self.assertEqual(self.send()['state'], 'SUPPRESSED'); self.assertEqual(self.remote.claim_calls, 0)
    def test_cap_counts_persisted_attempts(self):
        self.policy['per_family_limit'] = 1
        self.assertEqual(self.send()['state'], 'VERIFIED'); self.plan = self.proposal('quote:201:1')
        reopened = delivery.RootSender(self.mail, lambda: deepcopy(self.plan), root=self.root, journal=self.journal, remote=self.remote)
        self.assertEqual(reopened.send(self.plan, self.source(), now=self.now)['state'], 'BOUNDED')
        self.assertEqual(self.mail.posts, 1)
    def test_cycle_limit_bounds_different_families(self):
        self.policy['per_cycle_limit'] = 1
        self.assertEqual(self.send()['state'], 'VERIFIED')
        self.plan = self.proposal('visit:200:1', 'customer.appointment.confirmation')
        self.assertEqual(self.send()['state'], 'BOUNDED'); self.assertEqual(self.mail.posts, 1)
    def test_payload_change_for_existing_business_key_never_resends(self):
        self.assertEqual(self.send()['state'], 'VERIFIED'); self.plan['body'] = 'Changed content'
        with self.assertRaisesRegex(ValueError, 'payload changed'): self.send()
        self.assertEqual(self.mail.posts, 1); self.assertIn(self.plan['family'], self.sender.state['holds'])
    def test_missing_root_state_cannot_be_silently_initialized(self):
        (self.root / 'state.json').unlink()
        with self.assertRaises(FileNotFoundError): delivery.RootSender(self.mail, lambda: self.plan, root=self.root)
        self.assertEqual(self.mail.posts, 0)
    def test_existing_remote_claim_never_grants_a_second_post(self):
        self.assertEqual(self.send()['state'], 'VERIFIED')
        self.sender.state['effects'].clear(); self.sender.save()
        self.assertEqual(self.send()['state'], 'VERIFIED'); self.assertEqual(self.mail.posts, 1)
    def test_uncertain_remote_claim_grants_no_provider_post(self):
        self.remote.fail_claim = True
        self.assertEqual(self.send()['state'], 'HOLD'); self.assertEqual(self.mail.posts, 0)
        self.assertEqual(self.send()['state'], 'HOLD'); self.assertEqual(self.remote.claim_calls, 1)
    def test_wrong_recipient_in_test_proposal_is_rejected_before_claim(self):
        self.plan['recipient'] = 'external@example.net'
        with self.assertRaisesRegex(ValueError, 'controlled'): self.send()
        self.assertEqual(self.remote.claim_calls, 0); self.assertEqual(self.mail.posts, 0)
    def test_wrong_source_mode_is_rejected(self):
        source = self.source(); source['proof']['mode'] = 'REAL_NEW'
        with self.assertRaisesRegex(ValueError, 'source ownership'): self.sender.send(self.plan, source, now=self.now)
        self.assertEqual(self.remote.claim_calls, 0)
    def test_extra_mail_fields_cannot_enter_envelope(self):
        self.plan = delivery.decorate(self.plan); self.plan['message']['ccAddress'] = 'other@opticable.ca'
        with self.assertRaises(ValueError): self.send()
        self.assertEqual(self.mail.posts, 0)
    def test_non_root_cannot_construct_sender(self):
        with patch.object(delivery.os, 'geteuid', return_value=1001):
            with self.assertRaises(ValueError): delivery.RootSender(self.mail, lambda: self.plan, root=self.root)
    def test_overlap_or_malformed_search_requires_reconciliation(self):
        for name in ('overlap_search', 'malformed_read'):
            with self.subTest(name=name):
                self.plan = self.proposal(name); self.sender.state['holds'].clear()
                setattr(self.mail, name, True)
                self.assertEqual(self.send()['state'], 'HOLD')
                setattr(self.mail, name, False)
    def test_provider_plaintext_html_normalization_preserves_paragraphs(self):
        value = '<div>Bonjour,<br><br>Validation contrôlée.<br><br>L’équipe Opticable</div>'
        self.assertEqual(delivery.plain(value), 'Bonjour,\n\nValidation contrôlée.\n\nL’équipe Opticable')


if __name__ == '__main__': unittest.main()
