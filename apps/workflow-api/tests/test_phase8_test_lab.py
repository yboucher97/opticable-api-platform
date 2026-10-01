"""Focused firewall and sales-state regressions for provider-backed Test Lab work."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation import test_lab_boundary as boundary
from workflow.automation.crm_write_boundary import require_authority, verify_transport_authority
from workflow.automation.sales_lab import enhance_lab_queue
from workflow.automation.sales_queue import analyze_queue

NOW = datetime.fromisoformat("2026-09-30T19:00:00-04:00")
MARKER = "OPTIBRAIN TEST — PHASE 8"


class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        baseline = {"schema": 1, "modules": {module: {"status": "complete", "count": 0, "ids": []}
                     for module in boundary.MODULES}}
        baseline["modules"]["Leads"] = {"status": "complete", "count": 1, "ids": ["111"]}
        (root / "PROTECTED_PREEXISTING_RECORDS.json").write_text(json.dumps(baseline))
        registry = {"schema": 1, "baseline_sha256": hashlib.sha256(
            (root / "PROTECTED_PREEXISTING_RECORDS.json").read_bytes()).hexdigest(),
            "records": {module: [] for module in boundary.MODULES}}
        registry["records"]["Leads"] = ["222"]
        (root / "registry.json").write_text(json.dumps(registry))
        self.patches = [patch.object(boundary, "BASELINE", root / "PROTECTED_PREEXISTING_RECORDS.json"),
                        patch.object(boundary, "REGISTRY", root / "registry.json"),
                        patch.object(boundary.os, "geteuid", return_value=0),
                        patch.dict(os.environ, {"OPTIBRAIN_PHASE8_TEST_LAB": boundary.POLICY})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_preexisting_id_and_relationship_blocked_before_transport(self):
        header = {"If-Unmodified-Since": "2026-09-30T18:00:00-04:00"}
        protected = {"data": [{"id": "111", "Scope": "forbidden"}], "trigger": []}
        with self.assertRaisesRegex(ValueError, "protected"):
            boundary.validate_lab_request("PUT", "/crm/v8/Leads/111", protected, header)
        task = {"data": [{"Subject": MARKER + " — follow-up", "Description": MARKER,
                          "What_Id": {"id": "111"}, "$se_module": "Leads"}], "trigger": []}
        with self.assertRaisesRegex(ValueError, "outside Test Lab"):
            boundary.validate_lab_request("POST", "/crm/v8/Tasks", task, None)

    def test_owned_exact_call_is_single_use_and_email_allowlisted(self):
        header = {"If-Unmodified-Since": "2026-09-30T18:00:00-04:00"}
        body = {"data": [{"id": "222", "Scope": None}], "trigger": []}
        client = object()
        with boundary.reviewed_test_lab_call(client, "PUT", "/crm/v8/Leads/222", body, header):
            require_authority(client, "zohoapis", "PUT", "/crm/v8/Leads/222", body, header)
            verify_transport_authority(client, "zohoapis", "PUT", "/crm/v8/Leads/222", body, header)
            with self.assertRaises(ValueError):
                require_authority(client, "zohoapis", "PUT", "/crm/v8/Leads/222", body, header)
        bad = {"data": [{"id": "222", "Email": "real-customer@example.com"}], "trigger": []}
        with self.assertRaisesRegex(ValueError, "not synthetic"):
            boundary.validate_lab_request("PUT", "/crm/v8/Leads/222", bad, header)


def lead(id, *, email, service=None, street=None, scope=None, timeline=None,
         due=None, status="Not Contacted", description=MARKER):
    return {"id": id, "Full_Name": MARKER + " — " + id, "Company": MARKER + " — Company",
            "Email": email, "Lead_Status": status, "Converted__s": False,
            "Created_Time": "2026-09-30T18:00:00-04:00",
            "Modified_Time": "2026-09-30T18:00:00-04:00",
            "Next_Followup_At": due, "Service_Types": service, "Street": street,
            "Scope": scope, "Project_Timeline": timeline, "Description": description,
            "OptiBrain_Test": True, "Ingestion_Source": "test_ai_website"}


def task(id, lead_id, due, status="Not Started"):
    return {"id": id, "What_Id": {"id": lead_id}, "Due_Date": due, "Status": status}


class LabDecisionTests(unittest.TestCase):
    def evaluate(self, leads, tasks=(), mail=None, contacts=(), accounts=(), deals=()):
        view = analyze_queue(leads, list(contacts), list(accounts), None, now=NOW,
                             leads_complete=True, relationships_complete=True)
        return enhance_lab_queue(view, leads, list(contacts), list(accounts), list(deals),
                                 list(tasks), mail or {}, now=NOW)

    def test_quote_scope_and_real_relationship_chain(self):
        complete = lead("222", email="quote@optibrain.invalid", service="Wi-Fi",
                        street="100 Test Road", scope="12 access points", timeline="Next month")
        contact = {"id": "333", "Full_Name": complete["Full_Name"],
                   "Email": complete["Email"], "Account_Name": {"id": "444"}}
        account = {"id": "444", "Account_Name": complete["Company"]}
        deal = {"id": "555", "Account_Name": {"id": "444"}, "Contact_Name": {"id": "333"}}
        row = self.evaluate([complete], contacts=[contact], accounts=[account], deals=[deal])["rows"][0]
        self.assertEqual((row["quote"], row["priority"]), ("READY FOR QUOTE", "HIGH"))
        self.assertEqual(row["relationship"]["state"], "SUGGESTED")
        self.assertEqual(len(row["relationship"]["verified_links"]), 2)
        self.assertIn("12 access points", row["draft"]["body"])
        incomplete = {**complete, "Scope": None}
        row = self.evaluate([incomplete])["rows"][0]
        self.assertEqual(row["quote"], "NEEDS INFORMATION")

    def test_due_overdue_completed_and_recent_outbound(self):
        overdue = lead("222", email="late@optibrain.invalid", service="Cameras",
                       due="2026-09-24T17:00:00-04:00", status="Attempted to Contact")
        row = self.evaluate([overdue], [task("333", "222", "2026-09-24")])["rows"][0]
        self.assertEqual((row["followup"], row["neglected"]), ("OVERDUE", True))
        row = self.evaluate([overdue], [task("333", "222", "2026-09-24", "Completed")])["rows"][0]
        self.assertFalse(row["neglected"])
        due = {**overdue, "Next_Followup_At": "2026-09-30T18:00:00-04:00"}
        row = self.evaluate([due], [task("333", "222", "2026-09-30")])["rows"][0]
        self.assertEqual(row["followup"], "DUE")
        mail = {"reply_state": "NO_REPLY_YET", "last_outbound": {
            "sent_at": "2026-09-30T18:30:00-04:00", "sent_at_local": "Sep 30, 2026 6:30 PM EDT",
            "recipient": "late@optibrain.invalid", "subject": "TEST"}, "last_inbound": None,
            "new_information": []}
        row = self.evaluate([due], [task("333", "222", "2026-09-30")], {"222": mail})["rows"][0]
        self.assertEqual(row["followup"], "WAIT")
        self.assertIsNone(row["draft"])

    def test_linked_reply_changes_action_and_draft(self):
        item = lead("222", email="info@opticable.ca", service="Wi-Fi",
                    due="2026-10-02T17:00:00-04:00", status="Attempted to Contact")
        mail = {"reply_state": "REPLIED", "last_outbound": {
            "sent_at": "2026-09-30T18:00:00-04:00", "sent_at_local": "Sep 30, 2026 6:00 PM EDT",
            "recipient": item["Email"], "subject": "TEST"},
            "last_inbound": {"received_at_local": "Sep 30, 2026 6:30 PM EDT",
                             "summary": "Site address: 500 Test Street"},
            "new_information": ["Site address: 500 Test Street (from reply; verify)"]}
        row = self.evaluate([item], [task("333", "222", "2026-10-02")], {"222": mail})["rows"][0]
        self.assertEqual(row["state"], "REPLIED — NEEDS RESPONSE")
        self.assertEqual(row["priority"], "HIGH")
        self.assertNotIn("follow up on my previous note", row["draft"]["body"])
        self.assertIn("500 Test Street", row["draft"]["body"])

    def test_low_requires_noncommercial_evidence_and_duplicate_blocks_draft(self):
        incomplete = lead("222", email="new@optibrain.invalid")
        low = lead("333", email="low@optibrain.invalid", timeline="No project planned; research only")
        dup_a = lead("444", email="same@optibrain.invalid")
        dup_b = lead("555", email="same@optibrain.invalid")
        rows = {x["id"]: x for x in self.evaluate([incomplete, low, dup_a, dup_b])["rows"]}
        self.assertEqual(rows["222"]["priority"], "MEDIUM")
        self.assertEqual(rows["333"]["priority"], "LOW")
        self.assertIsNone(rows["333"]["draft"])
        self.assertEqual(rows["444"]["state"], "POSSIBLE DUPLICATE")
        self.assertIsNone(rows["444"]["draft"])
