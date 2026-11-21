from datetime import timedelta
import json
import os
import tempfile
import unittest
from pathlib import Path

from workflow.automation.autonomy_model_rehearsal import ModelRehearsal, assess_reply, evidence_plan
from workflow.automation.operational_recovery import DevelopmentScope, RULE

from test_autonomy_pilot import NOW, quota, sample


def proof_rows():
    at = NOW.isoformat()
    def row(rid, kind, status, cents=None, group=None, classification='REAL', observed_at=at):
        return {'id': rid, 'kind': kind, 'classification': classification, 'observed_at': observed_at,
                'status': status, 'cents': cents, 'currency': 'CAD', 'exclusive_group': group,
                'source': 'FORM_RECEIPT' if kind == 'qualified_lead' else 'BOOKS',
                'version': 'd' * 64}
    return [
        row('AR01', 'collection', 'overdue', 190001),
        row('AR02', 'collection', 'overdue', 500001, classification='TEST'),
        row('AR03', 'collection', 'overdue', 600001, observed_at=(NOW - timedelta(days=1)).isoformat()),
        row('QT01', 'quote', 'sent', 280000, 'same-scope'),
        row('QT02', 'quote', 'sent', 260000, 'same-scope'),
        row('QT03', 'quote', 'invoiced', 330000, 'other'),
        row('LD01', 'qualified_lead', 'qualified'),
    ]


EXPECTED = {'selected': [{'id': code, 'version': 'd' * 64} for code in ('AR01', 'QT01', 'LD01')],
            'overdue_cents': 190001, 'conditional_quote_cents': 280000, 'currency': 'CAD',
            'disposition': 'PREPARE_INTERNAL'}


def good(**changes):
    return {'status': 200, 'tokens': 900, 'seconds': 9, 'proposal': EXPECTED, **changes}


class AcceptanceTests(unittest.TestCase):
    def test_exact_independent_plan_with_test_stale_and_quote_alternatives_excluded(self):
        self.assertEqual(evidence_plan(proof_rows(), NOW), EXPECTED)

    def test_unsupported_cash_customer_action_and_quote_duplication_rejected(self):
        alternatives = [
            EXPECTED | {'cash_collected': 100000},
            EXPECTED | {'disposition': 'SEND_CUSTOMER_MESSAGE'},
            EXPECTED | {'selected': EXPECTED['selected'] + [{'id': 'QT02', 'version': 'd' * 64}]},
            EXPECTED | {'conditional_quote_cents': 540000},
            EXPECTED | {'selected': [{'id': 'AR02', 'version': 'd' * 64}]},
            'Professional customer experience and sales outcomes',
        ]
        for proposal in alternatives:
            with self.subTest(proposal=proposal):
                result = assess_reply(good(proposal=proposal), proof_rows(), NOW, attempt=2, charged=0)
                self.assertEqual(result['state'], 'REPAIR_REQUIRED')
        with self.assertRaises(ValueError):
            evidence_plan(proof_rows() * 2, NOW)

    def test_final_repair_budget_and_ambiguous_transport_hold(self):
        for reply, used, expected in [
            (good(proposal={}), 0, 'REJECTED'),
            (good(tokens=1601), 0, 'REJECTED'),
            (good(tokens=801), 2400, 'REJECTED'),
            (good(seconds=46), 0, 'REJECTED'),
            (good(status=503, confirmed_unaccepted=True), 0, 'REJECTED'),
            (good(status=503), 0, 'HUMAN_ACTION_REQUIRED'),
            (good(status=None), 0, 'HUMAN_ACTION_REQUIRED'),
        ]:
            with self.subTest(reply=reply, used=used):
                self.assertEqual(assess_reply(reply, proof_rows(), NOW, attempt=3, charged=used)['state'], expected)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.scope = DevelopmentScope(Path(tmp.name).resolve())
        self.scope.write('.optibrain-development.json', json.dumps({
            'environment': 'isolated-development', 'production_allowed': False, 'rule': RULE,
            'root': str(self.scope.root), 'issued_at': NOW.isoformat(),
            'expires_at': (NOW + timedelta(hours=2)).isoformat(),
        }).encode())

    def run_fixture(self, replies, now, windows):
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                with os.fdopen(write_fd, 'w') as stream:
                    lane = ModelRehearsal(self.scope, source='a' * 40, evidence=proof_rows(), fixtures=replies)
                    json.dump(lane.run(lambda: sample(now), windows, clock=lambda: now), stream)
                os._exit(0)
            except BaseException:
                os._exit(1)
        os.close(write_fd)
        with os.fdopen(read_fd) as stream:
            raw = stream.read()
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        return json.loads(raw)

    def test_429_holds_across_restart_rejected_candidate_gets_one_repair(self):
        replies = ({'status': 429, 'confirmed_unaccepted': True, 'retry_after': '180', 'tokens': 0, 'seconds': 1},
                   good(proposal=EXPECTED | {'conditional_quote_cents': 999999}),
                   good())
        a = self.run_fixture(replies, NOW, quota(NOW, 20, NOW + timedelta(hours=1)))
        rs = a['results']
        first = rs['model-fixture-1']['checkpoint']['review']['assessment']
        self.assertEqual(first['state'], 'RETRY_WAIT')
        self.assertEqual(rs['deterministic-evidence']['state'], 'COMPLETED')
        self.assertEqual(rs['live-model']['state'], 'APPROVAL_REQUIRED')
        self.assertEqual(a['model_tokens'], 0)
        still_wait = NOW + timedelta(seconds=90)
        b = self.run_fixture(replies, still_wait, quota(still_wait, 20, NOW + timedelta(hours=1)))
        self.assertEqual(b['results']['model-fixture-2']['reason'], 'provider_cooldown')
        ready = NOW + timedelta(seconds=183)
        stale = self.run_fixture(replies, ready, quota(NOW, 20, NOW + timedelta(hours=1)))
        self.assertEqual(stale['results']['model-fixture-2']['reason'], 'fresh_independent_allowance_required')
        c = self.run_fixture(replies, ready, quota(ready, 20, NOW + timedelta(hours=1)))
        second = c['results']['model-fixture-2']['checkpoint']['review']
        self.assertFalse(second['candidate_accepted'])
        self.assertEqual(second['assessment']['state'], 'REPAIR_REQUIRED')
        self.assertEqual(c['results']['model-fixture-3']['state'], 'RETRY_WAIT')
        repair = ready + timedelta(seconds=1)
        d = self.run_fixture(replies, repair, quota(repair, 20, NOW + timedelta(hours=1)))
        e = self.run_fixture(replies, repair, quota(repair, 20, NOW + timedelta(hours=1)))
        self.assertEqual(d, e)
        final = d['results']['model-fixture-3']['checkpoint']['review']
        self.assertTrue(final['candidate_accepted'])
        self.assertEqual(final['assessment']['simulated_total_tokens'], 1800)
        self.assertEqual(d['model_turns'], 0)

    def test_quota_exhaustion_and_unknown_leave_offline_work_available(self):
        replies = (good(), good(), good())
        now = NOW
        limited = self.run_fixture(replies, now, quota(now, 71, now + timedelta(minutes=1)))
        self.assertEqual(limited['results']['model-fixture-1']['state'], 'RETRY_WAIT')
        self.assertEqual(limited['results']['deterministic-evidence']['state'], 'COMPLETED')
        unknown = self.run_fixture(replies, now, {})
        self.assertEqual(unknown['results']['model-fixture-1']['state'], 'BLOCKED')
        self.assertEqual(unknown['results']['deterministic-evidence'], limited['results']['deterministic-evidence'])
        end = now + timedelta(minutes=1)
        sooner = now + timedelta(seconds=5)
        before_reset = self.run_fixture(replies, sooner, quota(sooner, 10, end))
        self.assertEqual(before_reset['results']['model-fixture-1']['state'], 'RETRY_WAIT')
        self.assertEqual(before_reset['fixture_allowance']['next_at'], end.isoformat())
        after_reset = end + timedelta(seconds=1)
        unconfirmed = self.run_fixture(replies, after_reset, quota(sooner, 10, end))
        self.assertEqual(unconfirmed['results']['model-fixture-1']['state'], 'BLOCKED')
        resumed = self.run_fixture(replies, after_reset, quota(after_reset, 10, end + timedelta(days=7)))
        self.assertTrue(resumed['results']['model-fixture-1']['checkpoint']['review']['candidate_accepted'])
