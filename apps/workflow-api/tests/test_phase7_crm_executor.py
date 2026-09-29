"""Fake-provider proof for the unregistered single-Lead CRM canary path."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.crm_write_boundary import (
    require_authority, reviewed_canary_call, verify_transport_authority,
)
from workflow.automation.phase7_canary import build_canary_plan, hydrate_unique_lead
from workflow.automation.phase7_crm_approval import CrmCanaryApprovalLedger
from workflow.automation.phase7_crm_executor import execute_approved_canary
from workflow.automation.store import AutomationStore


NOW = datetime.now(timezone.utc).replace(microsecond=0)
VERSION = (NOW - timedelta(hours=1)).isoformat()


class FakeCrm:
    def __init__(self):
        self.lead = {
            "id": "1234567890", "Modified_Time": VERSION, "Created_Time": VERSION,
            "Email": "fixture@example.net", "Email_Opt_Out": False,
            "Normalized_Email": "", "Lead_Status": "Not Contacted",
            "Converted__s": False, "City": "Montreal", "Language": "en",
            "Next_Followup_At": None,
        }
        self.calls = []
        self.writes = 0
        self.accept_then_lose_response = False
        self.malformed_ack = False
        self.offset_readback = False
        self.before_transport = None

    def request(self, service, method, path, **kwargs):
        self.calls.append((service, method, path))
        if service != "zohoapis":
            raise AssertionError("Unexpected provider")
        if method == "GET" and path.endswith("/search"):
            return {"ok": True, "status": 200,
                    "data": {"data": [{"id": self.lead["id"], "Email": self.lead["Email"]}],
                             "info": {"more_records": False}}}
        if method == "GET" and path == "/crm/v8/Leads/1234567890":
            record = dict(self.lead)
            if self.offset_readback and record.get("Next_Followup_At"):
                record["Next_Followup_At"] = datetime.fromisoformat(
                    record["Next_Followup_At"]
                ).astimezone(timezone(timedelta(hours=-4))).isoformat()
            return {"ok": True, "status": 200, "data": {"data": [record]}}
        if method == "PUT" and path == "/crm/v8/Leads/1234567890":
            require_authority(self, service, method, path, kwargs["body"], kwargs["headers"])
            if self.before_transport:
                self.before_transport()
            verify_transport_authority(self, service, method, path, kwargs["body"], kwargs["headers"])
            self.writes += 1
            self.lead.update(kwargs["body"]["data"][0])
            if self.accept_then_lose_response:
                raise TimeoutError("response lost after fake provider acceptance")
            if self.malformed_ack:
                return {"ok": True, "status": 200, "data": {"data": [{}]}}
            return {"ok": True, "status": 200,
                    "data": {"data": [{"status": "success", "details": {"id": self.lead["id"]}}]}}
        raise AssertionError("Unreviewed CRM request")


class CrmCanaryExecutorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="phase7-canary-executor-")
        self.addCleanup(tmp.cleanup)
        self.store = AutomationStore(Path(tmp.name) / "automation.db")
        self.client = FakeCrm()
        lead, evidence = hydrate_unique_lead(self.client, "1234567890")
        self.plan = build_canary_plan(lead, evidence, now=NOW)
        self.approval = CrmCanaryApprovalLedger(self.store).issue(
            actor="human:owner", lead_id=self.plan.lead_id,
            source_version=self.plan.source_version,
            plan_hash=self.plan.plan_hash, patch_hash=self.plan.crm_patch_hash,
            expires_at=(NOW + timedelta(minutes=30)).isoformat(), now=NOW)
        self.client.calls.clear()

    def execute(self):
        return execute_approved_canary(self.client, self.store, self.approval.approval_id, now=NOW)

    def enabled(self):
        return patch.dict(os.environ, {
            "OPTIBRAIN_CRM_CANARY": "phase7-single-canary-v1",
            "OPTIBRAIN_CRM_CANARY_APPROVAL_ID": self.approval.approval_id,
        })

    def test_disabled_policy_does_not_read_or_write(self):
        with patch.dict(os.environ, {"OPTIBRAIN_CRM_CANARY": ""}):
            with self.assertRaisesRegex(ValueError, "disabled"):
                self.execute()
        self.assertEqual(self.client.calls, [])

    def test_missing_single_approval_pin_does_not_read_or_write(self):
        with patch.dict(os.environ, {"OPTIBRAIN_CRM_CANARY": "phase7-single-canary-v1",
                                     "OPTIBRAIN_CRM_CANARY_APPROVAL_ID": ""}):
            with self.assertRaisesRegex(ValueError, "disabled"):
                self.execute()
        self.assertEqual(self.client.calls, [])

    def test_exact_approved_lead_patch_is_single_use(self):
        with self.enabled():
            result = self.execute()
            self.assertEqual(result["state"], "consumed")
            self.assertEqual(self.client.writes, 1)
            with self.assertRaises(ValueError):
                self.execute()
        self.assertEqual(self.client.writes, 1)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "consumed")

    def test_equivalent_timezone_readback_consumes_exact_patch(self):
        self.client.offset_readback = True
        with self.enabled():
            result = self.execute()
        self.assertEqual(result["state"], "consumed")
        self.assertEqual(self.client.writes, 1)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "consumed")

    def test_source_drift_blocks_before_claim_or_write(self):
        self.client.lead["Modified_Time"] = "2026-09-29T17:30:00+00:00"
        with self.enabled():
            with self.assertRaisesRegex(ValueError, "changed before consumption"):
                self.execute()
        self.assertEqual(self.client.writes, 0)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "issued")

    def test_response_loss_after_acceptance_becomes_manual_without_retry(self):
        self.client.accept_then_lose_response = True
        with self.enabled():
            with self.assertRaisesRegex(ValueError, "human reconciliation"):
                self.execute()
            with self.assertRaises(ValueError):
                self.execute()
        self.assertEqual(self.client.writes, 1)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "manual")

    def test_malformed_ack_becomes_manual_without_retry(self):
        self.client.malformed_ack = True
        with self.enabled():
            with self.assertRaisesRegex(ValueError, "human reconciliation"):
                self.execute()
        self.assertEqual(self.client.writes, 1)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "manual")

    def test_phase6_global_flag_is_not_needed_and_cannot_replace_canary_flag(self):
        with patch.dict(os.environ, {"OPTIBRAIN_CRM_CANARY": "", "OPTIBRAIN_CRM_LEAD_WRITES": "phase6-sales-v1"}):
            with self.assertRaisesRegex(ValueError, "disabled"):
                self.execute()
        self.assertEqual(self.client.writes, 0)

    def test_policy_change_before_transport_prevents_write_and_becomes_manual(self):
        self.client.before_transport = lambda: os.environ.__setitem__("OPTIBRAIN_CRM_CANARY", "")
        with self.enabled():
            with self.assertRaisesRegex(ValueError, "human reconciliation"):
                self.execute()
        self.assertEqual(self.client.writes, 0)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "manual")

    def test_manual_revocation_before_transport_prevents_write(self):
        self.client.before_transport = lambda: CrmCanaryApprovalLedger(self.store).finish(
            self.approval, reason="policy_disabled")
        with self.enabled():
            with self.assertRaisesRegex(ValueError, "human reconciliation"):
                self.execute()
        self.assertEqual(self.client.writes, 0)
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(self.approval.approval_id)["state"], "manual")

    def test_direct_bypass_and_other_modules_are_rejected(self):
        patch_body = {"data": [{"id": "1234567890", **self.plan.crm_patch}], "trigger": [],
                      "skip_feature_execution": [{"name": "cadences"}]}
        headers = {"If-Unmodified-Since": VERSION}
        with self.enabled():
            with self.assertRaisesRegex(ValueError, "single-use reconciler authority"):
                require_authority(self.client, "zohoapis", "PUT", "/crm/v8/Leads/1234567890",
                                  patch_body, headers)
            with self.assertRaisesRegex(ValueError, "approved boundary"):
                with reviewed_canary_call(self.client, "POST", "/crm/v8/Accounts",
                                          {"data": [{"Account_Name": "unsafe"}], "trigger": []},
                                          {}, self.approval, CrmCanaryApprovalLedger(self.store)):
                    pass
            with self.assertRaisesRegex(ValueError, "not been durably claimed"):
                with reviewed_canary_call(self.client, "PUT", "/crm/v8/Leads/1234567890",
                                          patch_body, headers, self.approval,
                                          CrmCanaryApprovalLedger(self.store)):
                    pass
        self.assertEqual(self.client.writes, 0)
