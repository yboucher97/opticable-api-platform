"""Verify the existing scoped queue and action journal together."""
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import httpx

from workflow.automation.action_evidence import ActionEvidence, approval_binding
from workflow.automation import autonomy_responses_dispatch as dispatch
from workflow.automation.autonomy_pilot import LEASE_SECONDS
from workflow.automation.autonomy_responses_queue import run_responses_task
from workflow.automation.operational_recovery import DevelopmentScope, RULE
from workflow.automation.store import AutomationStore
from test_autonomy_pilot import NOW, sample
from test_autonomy_responses import PROPOSAL, REQUEST, encode, response

BODY = encode(REQUEST)
SOURCE = 'a' * 40
RECOVERY = 'b' * 64
PROJECT = 'c' * 64


class ResponsesQueueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.scope = DevelopmentScope(Path(temp.name).resolve())
        self.scope.write('.optibrain-development.json', encode({
            'environment': 'isolated-development', 'production_allowed': False, 'rule': RULE,
            'root': str(self.scope.root), 'issued_at': NOW.isoformat(),
            'expires_at': (NOW + timedelta(hours=1)).isoformat(),
        }))
        self.journal = ActionEvidence(self.scope.path('automation.db'))
        self.invocations = []
        self.keys = 0
        self.reply = lambda: httpx.Response(200, stream=httpx.ByteStream(encode(response())))
        self.addCleanup(patch.stopall)
        patch.object(dispatch, 'PINNED_REQUEST', sha256(BODY).hexdigest()).start()
        self.kernel = patch.object(dispatch, 'cgroup_proof', return_value={}).start()
        patch.object(dispatch.httpx, 'HTTPTransport', return_value=httpx.MockTransport(self.exchange)).start()

    def observations(self, now=NOW):
        return sample(now) | {'offline_restore_receipt_sha256': RECOVERY, 'verified_project_receipt_sha256': PROJECT}

    def prepare(self):
        # Open the private ledger through the same route used by the worker.
        self.assertEqual(self.run_task()['state'], 'APPROVAL_REQUIRED')
        plan = dispatch.dispatch_plan(BODY, PROPOSAL, NOW, source=SOURCE, recovery_receipt=RECOVERY,
            project_receipt=PROJECT, organization='org-fixture', project='proj-fixture')
        self.journal.plan(plan, NOW)
        self.journal.approve(dispatch.ACTION_ID, 'synthetic_owner', NOW, binding=approval_binding(plan),
                             expires_at=(NOW + timedelta(minutes=10)).isoformat())

    def credential(self):
        self.keys += 1
        self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'STARTED')
        return 'fixture-only-secret-value'

    def exchange(self, req):
        self.assertEqual(self.step_states(), [('started',)])
        self.invocations.append(req.content)
        return self.reply()

    def step_states(self):
        uri = self.scope.path('automation.db').as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as db:
            return db.execute('SELECT status FROM automation_run_steps ORDER BY id').fetchall()

    def run_task(self, **overrides):
        kwargs = {'source': SOURCE, 'body': BODY, 'expected': PROPOSAL, 'clock': lambda: NOW,
                  'authorize': lambda p: p['approval_record']['actor'] == 'synthetic_owner',
                  'credential': self.credential, 'sample': self.observations}
        return run_responses_task(self.scope, **(kwargs | overrides))

    def test_missing_recovery_budget_or_owner_authority_leaves_no_attempt(self):
        self.prepare()
        for overrides, state in (
            ({'sample': sample}, 'APPROVAL_REQUIRED'),
            ({'sample': lambda: self.observations() | {'verified_project_receipt_sha256': 'd'*64}},
             'APPROVAL_REQUIRED'),
            ({'authorize': lambda _: False}, 'APPROVAL_REQUIRED'),
            ({'body': BODY + b' '}, 'APPROVAL_REQUIRED'),
            ({'sample': lambda: self.observations() | {'operator_paused': True}}, 'PAUSED'),
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.run_task(**overrides)['state'], state)
        self.kernel.side_effect = ValueError('envelope missing')
        self.assertEqual(self.run_task()['reason'], 'independent_kernel_limits_missing')
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([], 0, []))

    def test_one_lease_receiver_is_checkpointed_and_never_repeated(self):
        self.prepare()
        first = self.run_task()
        self.assertEqual(first['state'], 'COMPLETED')
        self.assertEqual(first, self.run_task())
        self.assertEqual(first['checkpoint']['receipt']['state'], 'VERIFIED_INTERNAL')
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([BODY], 1, [('completed',)]))

    def test_confirmed_429_is_kept_for_reconciliation_without_retry(self):
        self.prepare()
        self.reply = lambda: httpx.Response(429, headers={'retry-after': '190'})
        first = self.run_task()
        self.assertEqual(first['state'], 'HUMAN_ACTION_REQUIRED')
        self.assertEqual(first['checkpoint']['receipt']['cooldown_until'],
                         (NOW + timedelta(seconds=190)).isoformat())
        self.assertEqual(first, self.run_task())
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([BODY], 1, [('failed',)]))

    def test_interruption_after_egress_holds_both_ledgers_across_restart(self):
        self.prepare()

        def interrupt():
            raise SystemExit(70)

        self.reply = interrupt
        with self.assertRaises(SystemExit):
            self.run_task()
        after = NOW + timedelta(seconds=LEASE_SECONDS + 1)
        result = self.run_task(clock=lambda: after, sample=lambda: self.observations(after))
        self.assertEqual(result['state'], 'HUMAN_ACTION_REQUIRED')
        self.assertEqual(result['provider_journal_state'], 'STARTED')
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([BODY], 1, [('started',)]))

    def test_approved_source_bound_to_same_queue_catalogue(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'another plan'):
            self.run_task(source='f'*40)
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([], 0, []))

    def test_short_lived_journals_close_connections_on_success_and_error(self):
        self.prepare()
        store = AutomationStore(self.scope.path('automation.db'))
        with store._connect() as conn:
            self.assertEqual(conn.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute('SELECT 1')
        with self.assertRaisesRegex(RuntimeError, 'force a rollback'):
            with self.journal.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE should_rollback (id INTEGER)')
                raise RuntimeError('force a rollback')
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
        with self.journal.connect(readonly=True) as check:
            self.assertIsNone(check.execute("SELECT 1 FROM sqlite_master WHERE name='should_rollback'").fetchone())

    def interrupt_after_verified_receipt(self):
        self.prepare()

        def still_uncheckpointed(*args, **kwargs):
            self.assertEqual(self.journal.get(dispatch.ACTION_ID)['status'], 'SUCCEEDED')
            raise SystemExit(70)

        with patch.object(AutomationStore, 'complete_claimed_action', side_effect=still_uncheckpointed):
            with self.assertRaises(SystemExit):
                self.run_task()

    def test_expired_checkpoint_recovers_verified_receipt_without_credential_or_egress(self):
        self.interrupt_after_verified_receipt()
        current = NOW + timedelta(seconds=LEASE_SECONDS - 1)
        self.assertEqual(self.run_task(clock=lambda: current)['state'], 'RUNNING')
        expired = NOW + timedelta(seconds=LEASE_SECONDS + 1)
        result = self.run_task(clock=lambda: expired,
            sample=lambda: self.fail('Recovery should use existing evidence only'),
            credential=lambda: self.fail('Recovery should not read the credential'))
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(result['checkpoint']['recovery']['kind'], 'verified_provider_journal')
        self.assertEqual(result, self.run_task(clock=lambda: expired))
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([BODY], 1, [('completed',)]))
        with self.journal.connect(readonly=True) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM automation_run_failures WHERE reason_code='lease_expired_after_action'"
            ).fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM automation_audit WHERE action='expired_action_checkpoint_recovered'"
            ).fetchone()[0], 1)

    def test_expired_checkpoint_refuses_wrong_proposal(self):
        self.interrupt_after_verified_receipt()
        expired = NOW + timedelta(seconds=LEASE_SECONDS + 1)
        result = self.run_task(clock=lambda: expired, expected=PROPOSAL | {'overdue_cents': 999})
        self.assertEqual(result['state'], 'HUMAN_ACTION_REQUIRED')
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([BODY], 1, [('started',)]))

    def test_expired_checkpoint_refuses_broken_provenance_chain(self):
        self.interrupt_after_verified_receipt()
        with self.journal.connect() as db:
            db.execute('DROP TRIGGER action_evidence_immutable_update')
            db.execute("UPDATE action_evidence SET event_hash=? WHERE event_id=(SELECT max(event_id) FROM action_evidence)",
                       ('0'*64,))
        expired = NOW + timedelta(seconds=LEASE_SECONDS + 1)
        result = self.run_task(clock=lambda: expired)
        self.assertEqual(result['state'], 'HUMAN_ACTION_REQUIRED')
        self.assertEqual((self.invocations, self.keys, self.step_states()), ([BODY], 1, [('started',)]))
