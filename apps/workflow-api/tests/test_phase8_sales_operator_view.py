"""Focused proof of the controlled read-only operator sales view."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.sales_operator_view import (
    CONTROLLED_LEAD_ID, build_sales_operator_view, render_sales_operator_view,
)
from workflow.automation.store import AutomationStore
from workflow.operator_phase7_api import install_phase7_canary_routes


class FakeCrm:
    def __init__(self):
        self.calls = []
        self.record = {
            "id": CONTROLLED_LEAD_ID, "Full_Name": "OptiBrain Phase 7 Canary",
            "Company": "Opticable Internal Canary", "Email": "hckyan97@gmail.com",
            "Email_Opt_Out": False, "Lead_Status": "Not Contacted", "Converted__s": False,
            "Created_Time": "2026-09-29T16:28:11-04:00",
            "Modified_Time": "2026-09-29T16:50:31-04:00",
            "Next_Followup_At": "2026-10-01T17:00:00-04:00",
            "Ingestion_Source": "ai_website", "City": "Montreal",
            "Description": "Ingestion source: ai_website\nService: ai_loss_prevention\nLanguage: en\nExisting cameras: yes\nProject: Test one site",
        }

    def request(self, provider, method, path, **kwargs):
        self.calls.append((provider, method, path))
        assert provider == "zohoapis" and method == "GET"
        if path == f"/crm/v8/Leads/{CONTROLLED_LEAD_ID}":
            return {"ok": True, "status": 200, "data": {"data": [dict(self.record)]}}
        if path == "/crm/v8/Leads/search":
            return {"ok": True, "status": 200, "data": {"data": [
                {"id": CONTROLLED_LEAD_ID, "Email": self.record["Email"]}],
                "info": {"more_records": False}}}
        raise AssertionError("Unreviewed provider path")


class Identity:
    def verify(self, token):
        if token != "fixture-human-token":
            raise ValueError("human identity required")
        return type("Principal", (), {"subject": "fixture-human", "actor": "human:fixture-human"})()


class SalesOperatorViewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="phase8-sales-view-")
        self.addCleanup(tmp.cleanup)
        self.store = AutomationStore(Path(tmp.name) / "automation.db")
        self.crm = FakeCrm()
        self.clock = datetime.fromisoformat("2026-09-30T17:00:00-04:00")

    def view(self, clock=None):
        return build_sales_operator_view(self.crm, self.store.db_path, now=clock or self.clock)

    def test_realistic_inquiry_produces_useful_unsent_view(self):
        view = self.view()
        self.assertEqual(len(self.crm.calls), 3)
        self.assertTrue(all(method == "GET" for _, method, _ in self.crm.calls))
        self.assertEqual(view["source"]["label"], "AI website")
        self.assertTrue(view["source"]["description_agrees"])
        self.assertEqual(view["dedupe"]["matches"], 1)
        self.assertEqual(view["qualification"]["priority"], "Medium")
        self.assertEqual(view["quote_readiness"]["status"], "NEEDS INFORMATION")
        self.assertIn("Camera count and coverage areas", view["missing_information"])
        self.assertIn("Confirm preferred reply language", " ".join(view["missing_information"]))
        self.assertEqual(view["follow_up"]["current"], "Oct 1, 2026 5:00 PM EDT")
        self.assertFalse(view["follow_up"]["overdue"])
        self.assertEqual(view["draft"]["label"], "DRAFT — NOT SENT")
        self.assertIn("camera count", view["draft"]["body"])
        self.assertFalse(view["evidence"]["audit"]["current_version_reviewed"])

    def test_exact_email_duplicate_fails_closed(self):
        original = self.crm.request
        def duplicate(provider, method, path, **kwargs):
            value = original(provider, method, path, **kwargs)
            if path.endswith("/search"):
                value["data"]["data"].append({"id": "999", "Email": self.crm.record["Email"]})
            return value
        self.crm.request = duplicate
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.view()

    def test_snapshot_change_between_reads_fails_closed(self):
        original = self.crm.request
        def changed(provider, method, path, **kwargs):
            value = original(provider, method, path, **kwargs)
            if path.endswith(CONTROLLED_LEAD_ID) and "query" not in kwargs:
                value["data"]["data"][0]["Modified_Time"] = "2026-09-29T16:51:31-04:00"
            return value
        self.crm.request = changed
        with self.assertRaisesRegex(ValueError, "changed"):
            self.view()

    def test_est_and_dst_fallback_overdue_use_instants(self):
        self.crm.record["Next_Followup_At"] = "2026-11-01T01:30:00-04:00"
        self.assertFalse(self.view(datetime.fromisoformat("2026-11-01T01:15:00-04:00"))["follow_up"]["overdue"])
        # Same wall-clock hour, different offset: this is after the EDT deadline.
        after = self.view(datetime.fromisoformat("2026-11-01T01:15:00-05:00"))
        self.assertTrue(after["follow_up"]["overdue"])
        self.assertEqual(after["follow_up"]["current"], "Nov 1, 2026 1:30 AM EDT")
        self.crm.record["Next_Followup_At"] = "2026-12-01T17:00:00-05:00"
        self.assertTrue(self.view(datetime.fromisoformat("2026-12-01T17:01:00-05:00"))["follow_up"]["overdue"])
        self.assertEqual(self.view(datetime.fromisoformat("2026-12-01T16:59:00-05:00"))["follow_up"]["current"], "Dec 1, 2026 5:00 PM EST")

    def test_malformed_or_naive_followup_fails_closed(self):
        for value in ("2026-11-01T01:30:00", "invalid"):
            self.crm.record["Next_Followup_At"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.view()

    def test_html_escapes_provider_text_and_has_no_send_control(self):
        self.crm.record["Description"] = self.crm.record["Description"].replace(
            "Project: Test one site", "Project: <script>alert(1)</script>")
        html = render_sales_operator_view(self.view())
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("DRAFT — NOT SENT", html)
        self.assertNotIn("<form", html)
        self.assertNotIn("<button", html)

    def test_source_mismatch_does_not_promote_form_claims(self):
        self.crm.record["Description"] = self.crm.record["Description"].replace(
            "Ingestion source: ai_website", "Ingestion source: other")
        view = self.view()
        self.assertFalse(view["source"]["description_agrees"])
        self.assertIsNone(view["known"]["service_interest"])
        self.assertIsNone(view["draft"]["body"])

    def test_audit_version_matches_equivalent_offsets(self):
        event_id = "a" * 32
        envelope = {"source": "crm-lead-observer", "event_type": "opticable.crm.lead.reviewed",
                    "subject_id": CONTROLLED_LEAD_ID,
                    "payload": {"version": "2026-09-29T20:50:31+00:00"}}
        stamp = "2026-09-29T20:50:36.000000Z"
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("INSERT INTO automation_event_ledger "
                       "(event_id,source_account,dedupe_identity,content_hash,envelope_json,received_at,root_event_id) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (event_id, "test", "test-identity", "b" * 64, json.dumps(envelope),
                        stamp, event_id))
            db.execute("INSERT INTO automation_event_processing "
                       "(event_id,status,first_seen_at,last_seen_at,updated_at) VALUES (?,?,?,?,?)",
                       (event_id, "routed", stamp, stamp, stamp))
        view = self.view()
        self.assertTrue(view["evidence"]["audit"]["current_version_reviewed"])
        self.assertEqual(view["evidence"]["audit"]["review_event_id"], event_id)
        self.crm.record["Modified_Time"] = "2026-09-29T16:51:31-04:00"
        self.assertFalse(self.view()["evidence"]["audit"]["current_version_reviewed"])

    def test_route_requires_human_and_is_read_only(self):
        app = FastAPI()
        install_phase7_canary_routes(
            app, verifier=Identity(), client=self.crm, store=self.store,
            account_id="1234567890", from_address="yboucher@opticable.ca",
            allowed_origin="https://optibrain.opticable.ca", clock=lambda: self.clock)
        client = TestClient(app)
        path=f"/v1/operator/phase8/sales-view/{CONTROLLED_LEAD_ID}"
        self.assertEqual(client.get(path).status_code, 401)
        self.assertEqual(client.get("/v1/operator/phase8/sales-view/999",
                                    headers={"Cf-Access-Jwt-Assertion": "fixture-human-token"}).status_code, 404)
        self.assertEqual(len(self.crm.calls), 0)
        response = client.get(path, headers={"Cf-Access-Jwt-Assertion": "fixture-human-token"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])
        self.assertIn("DRAFT — NOT SENT", response.text)
        self.assertEqual(client.post(path, headers={"Cf-Access-Jwt-Assertion": "fixture-human-token"}).status_code, 405)
        self.assertTrue(all(method == "GET" for _, method, _ in self.crm.calls))
