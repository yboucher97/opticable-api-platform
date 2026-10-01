from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.phase9_intake import IntakeLedger, event_id, source_info
from workflow.automation import test_lab_boundary as boundary
from workflow.automation.sales_lab import enhance_lab_queue
from workflow.automation.sales_queue import analyze_queue, render_sales_queue
from workflow.operator_phase7_api import install_phase7_canary_routes
import importlib.util

_spec = importlib.util.spec_from_file_location("phase9_test_lab_intake", Path(__file__).resolve().parents[3] / "ops/phase9/test_lab_intake.py")
test_lab_intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(test_lab_intake)


class IntakeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = IntakeLedger(Path(self.temp.name) / "intake.db")
        self.crm = {"id": "123456", "Email": "hckyan97+obp9a@gmail.com",
                    "Inquiry_ID": "inquiry-a", "Ingestion_Source": "ai_website",
                    "OptiBrain_Test": True, "Description": "OPTIBRAIN TEST — PHASE 9\nSynthetic",
                    "Modified_Time": "2026-10-01T00:00:02+00:00"}
        self.receipt = {"inquiry_id": "inquiry-a", "email": self.crm["Email"],
                        "source": "ai_website", "occurred_at": "2026-09-30T20:00:00-04:00",
                        "request": {"email": self.crm["Email"], "inquiry_id": "inquiry-a"},
                        "attribution": {"last_campaign": "opticable_phase9_test"},
                        "crm_action": "created_lead"}

    def test_new_returning_replay_and_immutable_evidence(self):
        first = self.ledger.record(self.receipt, self.crm)
        self.assertEqual(first["decision"], "NEW IDENTITY")
        self.assertEqual(self.ledger.record(self.receipt, self.crm)["decision"], "REPLAY")
        second = {**self.receipt, "inquiry_id": "inquiry-b", "source": "opticable_website",
                  "occurred_at": "2026-10-01T00:10:00+00:00",
                  "request": {"email": self.crm["Email"], "inquiry_id": "inquiry-b"},
                  "crm_action": "updated_lead"}
        crm = {**self.crm, "Inquiry_ID": "inquiry-b", "Ingestion_Source": "opticable_website",
               "Modified_Time": "2026-10-01T00:10:02+00:00"}
        self.assertEqual(self.ledger.record(second, crm)["decision"], "EXACT EXISTING IDENTITY")
        trace = self.ledger.trace("123456")
        self.assertEqual((trace["first_touch"], trace["latest_touch"]), ("ai_website", "opticable_website"))
        self.assertEqual(len(trace["events"]), 2)
        self.assertTrue(trace["events"][0]["occurred_at_montreal"].endswith("-04:00"))
        feedback = self.ledger.feedback(kind="LEAD_CREATED", canonical_id="123456",
                                        related_module="Leads", related_id="123456",
                                        occurred_at="2026-10-01T00:00:02Z", evidence={"crm_id": "123456"})
        self.assertEqual(feedback, self.ledger.feedback(kind="LEAD_CREATED", canonical_id="123456",
                           related_module="Leads", related_id="123456",
                           occurred_at="2026-10-01T00:00:02Z", evidence={"crm_id": "123456"}))
        with sqlite3.connect(self.ledger.path) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM intake_events")
        self.assertEqual(len(self.ledger.trace("123456")["feedback"]), 1)

    def test_conflicting_replay_and_provider_mismatch_fail_closed(self):
        self.ledger.record(self.receipt, self.crm)
        with self.assertRaisesRegex(ValueError, "replay conflicts"):
            self.ledger.record({**self.receipt, "request": {"changed": True}}, self.crm)
        with self.assertRaisesRegex(ValueError, "readback"):
            self.ledger.record({**self.receipt, "inquiry_id": "inquiry-c"}, self.crm)
        with self.assertRaisesRegex(ValueError, "readback"):
            self.ledger.record(self.receipt, {**self.crm, "OptiBrain_Test": False})
        with self.assertRaises(ValueError):
            self.ledger.record({**self.receipt, "occurred_at": "2026-10-01T00:00:00"}, self.crm)

    def test_source_missing_is_unknown_and_identity_is_stable(self):
        self.assertEqual(source_info(None), ("unknown", "Unknown"))
        self.assertEqual(source_info("manual_crm"), ("manual", "Manual CRM"))
        self.assertEqual(event_id("ai_website", "a"), event_id("ai_website", "a"))
        self.assertNotEqual(event_id("ai_website", "a"), event_id("ai_website", "b"))
        receipt = {**self.receipt, "source": "unknown", "inquiry_id": "unknown-a",
                   "request": {"inquiry_id": "unknown-a", "email": self.crm["Email"]}}
        crm = {**self.crm, "Inquiry_ID": "unknown-a", "Ingestion_Source": None}
        self.assertEqual(self.ledger.record(receipt, crm)["decision"], "NEW IDENTITY")
        self.assertEqual(self.ledger.trace("123456")["first_touch"], "unknown")

    def test_phase9_test_marker_keeps_protected_record_firewall(self):
        root = Path(self.temp.name)
        baseline = {"schema": 1, "modules": {module: {"status": "complete", "count": 0, "ids": []}
                    for module in boundary.MODULES}}
        baseline["modules"]["Leads"] = {"status": "complete", "count": 1, "ids": ["111"]}
        baseline_path = root / "PROTECTED_PREEXISTING_RECORDS.json"
        baseline_path.write_text(json.dumps(baseline))
        service_baseline_path = root / "service-protected-baseline.json"
        service_baseline_path.write_text(json.dumps({"schema": 1, "modules":
            {module: [] for module in boundary.SERVICE_MODULES}}))
        registry = {"schema": 1, "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                    "service_baseline_sha256": hashlib.sha256(service_baseline_path.read_bytes()).hexdigest(),
                    "records": {module: [] for module in boundary.MODULES}}
        registry["records"]["Leads"] = ["222"]
        registry_path = root / "registry.json"
        registry_path.write_text(json.dumps(registry))
        header = {"If-Unmodified-Since": "2026-09-30T18:00:00-04:00"}
        with patch.object(boundary, "BASELINE", baseline_path), patch.object(boundary, "REGISTRY", registry_path), \
             patch.object(boundary, "SERVICE_BASELINE", service_baseline_path), \
             patch.object(boundary.os, "geteuid", return_value=0), \
             patch.dict(os.environ, {"OPTIBRAIN_PHASE8_TEST_LAB": boundary.POLICY}):
            body = {"data": [{"id": "111", "Description": "OPTIBRAIN TEST — PHASE 9"}], "trigger": []}
            with self.assertRaisesRegex(ValueError, "protected"):
                boundary.validate_lab_request("PUT", "/crm/v8/Leads/111", body, header)
            body["data"][0]["id"] = "222"
            self.assertEqual(boundary.validate_lab_request("PUT", "/crm/v8/Leads/222", body, header), ("Leads", "222"))

    def test_reconciliation_uses_complete_crm_list_when_search_index_is_stale(self):
        class Client:
            def request(self, service, method, path, **kwargs):
                self_path = path
                if path == "/crm/v8/Leads":
                    return {"ok": True, "status": 200, "data": {"data": [
                        {"id": "222", "Email": "hckyan97+obp9intake1@gmail.com", "Inquiry_ID": "abc"}],
                        "info": {"more_records": False}}}
                raise AssertionError(self_path)
        self.assertEqual(test_lab_intake.find(Client(), "Leads", "Inquiry_ID", "abc")[0]["id"], "222")

    def test_operator_trace_requires_identity_and_escapes_provider_text(self):
        class Verifier:
            def verify(self, token):
                if token != "authorized":
                    raise ValueError("missing")
                return type("Principal", (), {"subject": "operator"})()
        class Client:
            def request(self, service, method, path, **kwargs):
                records = {
                    "/crm/v8/Leads/123456": {"id": "123456", "Full_Name": "<Test>",
                        "Email": "test@example.invalid", "First_Source": "phase9_test",
                        "First_Campaign": "opticable_phase9_test", "OptiBrain_Test": True,
                        "Description": "OPTIBRAIN TEST — PHASE 9"},
                    "/crm/v8/Contacts/234567": {"id": "234567", "Email": "test@example.invalid",
                        "Account_Name": {"id": "345678"}, "OptiBrain_Test": True,
                        "Description": "OPTIBRAIN TEST — PHASE 9"},
                    "/crm/v8/Accounts/345678": {"id": "345678", "OptiBrain_Test": True,
                        "Description": "OPTIBRAIN TEST — PHASE 9"},
                    "/crm/v8/Deals/456789": {"id": "456789", "OptiBrain_Test": True,
                        "Description": "OPTIBRAIN TEST — PHASE 9", "Amount": None,
                        "Contact_Name": {"id": "234567"}, "Account_Name": {"id": "345678"},
                        "First_Source": "phase9_test", "First_Campaign": "opticable_phase9_test"},
                }
                return {"data": {"data": [records[path]]}}
        class Store:
            db_path = Path("/tmp/automation.db")
        app = FastAPI()
        install_phase7_canary_routes(app, verifier=Verifier(), client=Client(), store=Store(),
                                     account_id="1", from_address="operator@example.com",
                                     allowed_origin="https://optibrain.example.com")
        trace = {"canonical_id": "123456", "first_touch": "ai_website",
                 "latest_touch": "opticable_website", "events": [{"source": "ai_website",
                 "occurred_at_montreal": "2026-09-30T20:00:00-04:00", "event_id": "OB-I-X",
                 "crm_action": "created_lead", "campaign": "test"}],
                 "feedback": [{"kind": "OPPORTUNITY_CREATED", "related_module": "Deals",
                     "related_id": "456789", "occurred_at_montreal": "2026-09-30T20:30:00-04:00"}]}
        original_read = Path.read_text
        def read_registry(path, *args, **kwargs):
            if str(path) == "/etc/optibrain/phase8-test-lab-registry.json":
                return json.dumps({"records": {"Leads": ["123456"],
                    "Contacts": ["234567"], "Accounts": ["345678"], "Deals": ["456789"]}})
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", read_registry), patch.object(IntakeLedger, "trace", return_value=trace):
            api = TestClient(app)
            self.assertEqual(api.get("/v1/operator/phase9/source-trace/123456").status_code, 401)
            response = api.get("/v1/operator/phase9/source-trace/123456",
                               headers={"Cf-Access-Jwt-Assertion": "authorized"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("ai_website", response.text)
        self.assertIn("opticable_website", response.text)
        self.assertIn("&lt;Test&gt;", response.text)
        self.assertNotIn("<Test>", response.text)
        self.assertIn("Verified CRM relationship", response.text)
        self.assertIn("no Lead conversion is claimed", response.text)

    def test_unknown_crm_source_stays_unknown_in_operator_queue(self):
        lead = {"id": "123456", "Full_Name": "Test", "Last_Name": "Test",
                "Company": "OPTIBRAIN TEST — PHASE 9 — Lab", "Email": "x@optibrain.invalid",
                "Description": "OPTIBRAIN TEST — PHASE 9", "OptiBrain_Test": True,
                "Lead_Status": "Not Contacted", "Converted__s": False,
                "Created_Time": "2026-09-30T20:00:00-04:00",
                "Modified_Time": "2026-09-30T20:00:00-04:00",
                "Ingestion_Source": None, "Next_Followup_At": None}
        now = datetime.fromisoformat("2026-09-30T21:00:00-04:00")
        initial = analyze_queue([lead], [], [], None, now=now,
                                leads_complete=True, relationships_complete=True)
        view = enhance_lab_queue(initial, [lead], [], [], [], [], {}, now=now)
        self.assertEqual(view["rows"][0]["source"], "Unknown")
        self.assertIn("No source metadata", view["rows"][0]["source_basis"])
        self.assertIn("Unknown", render_sales_queue(view))


if __name__ == "__main__":
    unittest.main()
