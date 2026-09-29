"""Durable, single-use CRM canary approval with fake state only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from workflow.automation.phase7_crm_approval import CrmCanaryApprovalLedger
from workflow.automation.store import AutomationStore


NOW = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
BINDING = {"lead_id": "1234567890", "source_version": "2026-09-29T18:00:00+00:00",
           "plan_hash": "a" * 64, "patch_hash": "b" * 64}


class CrmCanaryApprovalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="phase7-crm-approval-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "automation.db"
        self.store = AutomationStore(self.path)
        self.ledger = CrmCanaryApprovalLedger(self.store)

    def issue(self, **changes):
        values = {"actor": "human:owner", **BINDING,
                  "expires_at": (NOW + timedelta(minutes=30)).isoformat(), "now": NOW}
        values.update(changes)
        return self.ledger.issue(**values)

    def test_human_issue_restart_and_exact_claim(self):
        approval = self.issue()
        fresh = CrmCanaryApprovalLedger(AutomationStore(self.path))
        self.assertEqual(fresh.inspect(approval.approval_id)["state"], "issued")
        claimed = fresh.claim(approval.approval_id, now=NOW, **BINDING)
        self.assertEqual(claimed, approval)
        self.assertEqual(self.ledger.inspect(approval.approval_id)["state"], "consuming")

    def test_automation_actor_duplicate_and_long_lifetime_rejected(self):
        with self.assertRaises(ValueError):
            self.issue(actor="human:automation-worker")
        approval = self.issue()
        with self.assertRaises(ValueError):
            self.issue(approval_id=approval.approval_id)
        with self.assertRaises(ValueError):
            self.issue(expires_at=(NOW + timedelta(hours=2)).isoformat())

    def test_expiry_and_each_binding_change_fail_before_claim(self):
        approval = self.issue()
        for key, value in {"lead_id": "999", "source_version": "2026-09-29T19:00:00+00:00",
                           "plan_hash": "c" * 64, "patch_hash": "d" * 64}.items():
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "binding changed"):
                self.ledger.claim(approval.approval_id, now=NOW, **{**BINDING, key: value})
        with self.assertRaisesRegex(ValueError, "expired"):
            self.ledger.claim(approval.approval_id, now=NOW + timedelta(hours=1), **BINDING)
        self.assertEqual(self.ledger.inspect(approval.approval_id)["state"], "issued")

    def test_process_loss_after_consuming_marker_never_reuses(self):
        approval = self.issue()
        self.ledger.claim(approval.approval_id, now=NOW, **BINDING)
        restarted = CrmCanaryApprovalLedger(AutomationStore(self.path))
        with self.assertRaisesRegex(ValueError, "non-reusable"):
            restarted.claim(approval.approval_id, now=NOW, **BINDING)
        restarted.finish(approval, reason="provider_unconfirmed")
        with self.assertRaisesRegex(ValueError, "non-reusable"):
            self.ledger.claim(approval.approval_id, now=NOW, **BINDING)

    def test_verified_consumption_is_single_use(self):
        approval = self.issue()
        self.ledger.claim(approval.approval_id, now=NOW, **BINDING)
        with self.assertRaisesRegex(ValueError, "verified or manual"):
            self.ledger.finish(approval, operation_id="987654321")
        self.ledger.mark_dispatch(approval, now=NOW)
        with self.assertRaisesRegex(ValueError, "already used"):
            self.ledger.mark_dispatch(approval, now=NOW)
        self.ledger.finish(approval, operation_id="987654321", verified_patch_hash="b" * 64)
        state = CrmCanaryApprovalLedger(AutomationStore(self.path)).inspect(approval.approval_id)
        self.assertEqual(state["state"], "consumed")
        self.assertEqual(state["evidence"]["provider_operation_id"], "987654321")
        with self.assertRaises(ValueError):
            self.ledger.claim(approval.approval_id, now=NOW, **BINDING)

    def test_concurrent_claims_only_one_wins(self):
        approval = self.issue()
        def claim():
            try:
                CrmCanaryApprovalLedger(AutomationStore(self.path)).claim(
                    approval.approval_id, now=NOW, **BINDING)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sorted(outcomes), [False, True])

    def test_audit_has_hashes_and_ids_without_raw_customer_data(self):
        approval = self.issue()
        self.ledger.claim(approval.approval_id, now=NOW, **BINDING)
        with self.store._connect() as connection:
            rows = connection.execute("SELECT metadata_json FROM automation_audit WHERE target=?",
                                      (approval.approval_id,)).fetchall()
        text = json.dumps([json.loads(row[0]) for row in rows])
        for forbidden in ("customer@example.net", "Hello", "+15145550100"):
            self.assertNotIn(forbidden, text)
        self.assertIn("patch_hash", text)
