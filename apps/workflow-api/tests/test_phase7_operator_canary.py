"""Unregistered authenticated operator preview/issuance, fake provider only."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.phase7_crm_approval import CrmCanaryApprovalLedger
from workflow.automation.outbound_approval import OutboundApprovalLedger
from workflow.automation.store import AutomationStore
from workflow.operator_access import AccessPrincipal
from workflow.operator_phase7_api import install_phase7_canary_routes


NOW = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
ORIGIN = "https://approvals.opticable.ca"


class FakeVerifier:
    def verify(self, token):
        if token != "signed-human-fixture":
            raise ValueError("not verified")
        return AccessPrincipal(subject="owner", email="owner@example.net", actor="human:owner")


class FakeCrm:
    def __init__(self):
        self.lead = {"id": "1234567890", "Modified_Time": "2026-09-29T17:00:00+00:00",
                     "Created_Time": "2026-09-29T17:00:00+00:00", "Email": "fixture@example.net",
                     "Email_Opt_Out": False, "Lead_Status": "Not Contacted",
                     "Converted__s": False, "Language": "en", "Normalized_Email": "",
                     "Next_Followup_At": None, "City": "Montreal"}
        self.calls = []

    def request(self, provider, method, path, **_kwargs):
        self.calls.append((provider, method, path))
        if provider != "zohoapis" or method != "GET":
            raise AssertionError("operator route attempted provider mutation")
        if path.endswith("/search"):
            return {"ok": True, "status": 200,
                    "data": {"data": [{"id": self.lead["id"], "Email": self.lead["Email"]}],
                             "info": {"more_records": False}}}
        return {"ok": True, "status": 200, "data": {"data": [dict(self.lead)]}}


class Phase7OperatorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="phase7-operator-")
        self.addCleanup(tmp.cleanup)
        self.store = AutomationStore(Path(tmp.name) / "automation.db")
        self.provider = FakeCrm()
        app = FastAPI()
        install_phase7_canary_routes(app, verifier=FakeVerifier(), client=self.provider,
                                     store=self.store, account_id="12345",
                                     from_address="sales@opticable.ca",
                                     allowed_origin=ORIGIN, clock=lambda: NOW)
        self.client = TestClient(app)
        self.auth = {"Cf-Access-Jwt-Assertion": "signed-human-fixture"}

    def test_preview_requires_human_and_is_read_only(self):
        path = "/v1/operator/phase7/canary/1234567890"
        self.assertEqual(self.client.get(path).status_code, 401)
        response = self.client.get(path, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
        self.assertEqual(response.json()["review"]["recipient"], "fixture@example.net")
        self.assertFalse(response.json()["crm_mutation_enabled"])
        self.assertTrue(all(method == "GET" for _, method, _ in self.provider.calls))

    def test_issue_binds_exact_preview_and_cannot_write(self):
        preview = self.client.get("/v1/operator/phase7/canary/1234567890", headers=self.auth).json()
        body = {"lead_id": "1234567890", "plan_hash": preview["plan"]["plan_hash"],
                "patch_hash": preview["plan"]["crm_patch_hash"]}
        url = "/v1/operator/phase7/crm-approvals"
        self.assertEqual(self.client.post(url, json=body, headers=self.auth).status_code, 403)
        headers = {**self.auth, "Origin": ORIGIN}
        self.assertEqual(self.client.post(url, content="{}", headers=headers).status_code, 415)
        result = self.client.post(url, json=body, headers=headers)
        self.assertEqual(result.status_code, 201)
        approval = CrmCanaryApprovalLedger(self.store).inspect(result.json()["approval_id"])
        self.assertEqual(approval["state"], "issued")
        self.assertEqual(approval["approval"].actor, "human:owner")
        consume = self.client.post(
            f"/v1/operator/phase7/crm-approvals/{result.json()['approval_id']}/consume",
            json={}, headers=headers)
        self.assertEqual(consume.status_code, 409)
        self.assertEqual(consume.json()["reason"], "crm_canary_not_registered")
        self.assertEqual(CrmCanaryApprovalLedger(self.store).inspect(result.json()["approval_id"])["state"], "issued")
        self.assertTrue(all(method == "GET" for _, method, _ in self.provider.calls))

    def test_stale_preview_blocks_issuance(self):
        preview = self.client.get("/v1/operator/phase7/canary/1234567890", headers=self.auth).json()
        self.provider.lead["Modified_Time"] = "2026-09-29T17:30:00+00:00"
        body = {"lead_id": "1234567890", "plan_hash": preview["plan"]["plan_hash"],
                "patch_hash": preview["plan"]["crm_patch_hash"]}
        result = self.client.post("/v1/operator/phase7/crm-approvals", json=body,
                                  headers={**self.auth, "Origin": ORIGIN})
        self.assertEqual(result.status_code, 409)
        self.assertTrue(all(method == "GET" for _, method, _ in self.provider.calls))

    def test_outbound_approval_binds_exact_package_without_sending(self):
        preview = self.client.get("/v1/operator/phase7/canary/1234567890", headers=self.auth).json()
        body = {"lead_id": "1234567890", "plan_hash": preview["plan"]["plan_hash"],
                "package_hash": preview["review"]["package_hash"], "reviewed_language": "en"}
        headers = {**self.auth, "Origin": ORIGIN}
        url = "/v1/operator/phase7/outbound-approvals"
        self.assertEqual(self.client.post(url, json={**body, "package_hash": "a" * 64},
                                          headers=headers).status_code, 409)
        result = self.client.post(url, json=body, headers=headers)
        self.assertEqual(result.status_code, 201)
        approval_id = result.json()["approval_id"]
        self.assertEqual(OutboundApprovalLedger(self.store).inspect(approval_id)["state"], "issued")
        consume_url = f"{url}/{approval_id}/consume"
        blocked = self.client.post(consume_url, json={}, headers=headers)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["reason"], "outbound_canary_not_registered")
        self.provider.lead["Email"] = "changed@example.net"
        self.assertEqual(self.client.post(consume_url, json={}, headers=headers).status_code, 409)
        self.assertEqual(OutboundApprovalLedger(self.store).inspect(approval_id)["state"], "issued")
        self.assertTrue(all(method == "GET" for _, method, _ in self.provider.calls))
