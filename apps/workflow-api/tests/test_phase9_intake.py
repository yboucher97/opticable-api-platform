from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.phase9_intake import IntakeLedger, event_id, source_info
from workflow.automation import test_lab_boundary as boundary
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

    def test_phase9_test_marker_keeps_protected_record_firewall(self):
        root = Path(self.temp.name)
        baseline = {"schema": 1, "modules": {module: {"status": "complete", "count": 0, "ids": []}
                    for module in boundary.MODULES}}
        baseline["modules"]["Leads"] = {"status": "complete", "count": 1, "ids": ["111"]}
        baseline_path = root / "PROTECTED_PREEXISTING_RECORDS.json"
        baseline_path.write_text(json.dumps(baseline))
        registry = {"schema": 1, "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                    "records": {module: [] for module in boundary.MODULES}}
        registry["records"]["Leads"] = ["222"]
        registry_path = root / "registry.json"
        registry_path.write_text(json.dumps(registry))
        header = {"If-Unmodified-Since": "2026-09-30T18:00:00-04:00"}
        with patch.object(boundary, "BASELINE", baseline_path), patch.object(boundary, "REGISTRY", registry_path), \
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


if __name__ == "__main__":
    unittest.main()
