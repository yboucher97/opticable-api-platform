from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.crm_write_boundary import require_authority, verify_transport_authority
from workflow.automation.phase9_form_receipts import FormReceiptLedger, parse_notification
from workflow.automation.phase9_form_enrichment import (
    POLICY, enrich_form_leads, validate_form_request, aware,
)
from workflow.automation.phase9_intake import IntakeLedger


class Provider:
    def __init__(self, lead, occurred, *, source="zoho_forms", other_email=None, fail_after_put=False):
        self.lead = lead
        self.occurred = occurred
        self.source = source
        self.other_email = other_email
        self.fail_after_put = fail_after_put
        self.puts = 0

    def request(self, service, method, path, **kwargs):
        if method == "PUT":
            require_authority(self, service, method, path, kwargs["body"], kwargs["headers"])
            verify_transport_authority(self, service, method, path, kwargs["body"], kwargs["headers"])
            self.puts += 1
            self.lead.update(kwargs["body"]["data"][0])
            self.lead["Modified_Time"] = (aware(self.lead["Created_Time"]) + timedelta(seconds=1)).isoformat()
            if self.fail_after_put:
                raise TimeoutError("acknowledgement lost after provider accepted write")
            return {"ok": True, "data": {"data": [{"status": "success", "details": {"id": self.lead["id"]}}]}}
        if path.endswith("/__timeline"):
            return {"ok": True, "data": {"__timeline": [{"id": "77", "action": "added",
                "source": self.source, "audited_time": self.lead["Created_Time"]}],
                "info": {"more_records": False}}}
        if path == "/crm/v8/Leads":
            if kwargs.get("query", {}).get("fields") == "id,Email":
                rows = [self.lead]
                if self.other_email:
                    rows.append({"id": "888", "Email": self.other_email})
            else:
                rows = [self.lead]
            return {"ok": True, "data": {"data": rows, "info": {"more_records": False}}}
        if path == "/crm/v8/Contacts":
            return {"ok": True, "data": {"data": [], "info": {"more_records": False}}}
        if path == f"/crm/v8/Leads/{self.lead['id']}":
            return {"ok": True, "data": {"data": [dict(self.lead)]}}
        raise AssertionError((service, method, path))


class FormEnrichmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger = FormReceiptLedger(Path(temp.name) / "phase9-form-receipts.db")
        occurred = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        html = """<table><tr><td>Nom du contact</td><td>:</td><td>Phase Nine, OPTIBRAIN TEST CLOSURE</td></tr>
        <tr><td>Entreprise</td><td>:</td><td>OPTIBRAIN TEST — PHASE 9 — Form Closure</td></tr>
        <tr><td>Courriel</td><td>:</td><td>hckyan97+obp9closure@gmail.com</td></tr>
        <tr><td>Téléphone</td><td>:</td><td>5145550199</td></tr>
        <tr><td>Notes sur le projet</td><td>:</td><td>TEST ONLY synthetic project</td></tr></table>"""
        self.receipt = parse_notification(message_id="1790990000000000001",
            details={"messageId": "1790990000000000001", "fromAddress": "notifications@zohoforms.com",
                     "toAddress": "soumissions@opticable.ca", "receivedTime": str(int(occurred.timestamp()*1000))},
            content={"content": html}, headers={"Authentication-Results": ["dkim=pass; dmarc=pass"],
            "Message-ID": ["<closure@public.zohoforms.com>"]}, now=occurred)
        self.lead = {"id": "777", "First_Name": "Phase Nine", "Last_Name": "OPTIBRAIN TEST CLOSURE",
            "Company": self.receipt["fields"]["company"], "Phone": "5145550199",
            "Created_Time": occurred.isoformat(), "Modified_Time": occurred.isoformat(),
            "Email": None, "Normalized_Email": None, "Ingestion_Source": None,
            "First_Source": None, "Last_Source": None, "First_Touch_Time": None,
            "Last_Touch_Time": None, "Inquiry_ID": None, "Source_Record_ID": None,
            "OptiBrain_Test": False, "Description": None}
        self.ledger.record(self.receipt)
        self.ledger.match_provider(self.receipt["event_id"], self.lead)
        self.go_live = (occurred - timedelta(minutes=1)).isoformat()
        self.env = patch.dict(os.environ, {"OPTIBRAIN_PHASE9_FORM_ENRICHMENT": POLICY})
        self.protection = patch("workflow.automation.phase9_form_enrichment.protected_ids",
                                return_value=({"999"}, occurred - timedelta(days=1)))
        self.env.start(); self.protection.start()
        self.addCleanup(self.env.stop); self.addCleanup(self.protection.stop)

    def test_one_exact_provider_write_readback_replay_and_intake(self):
        client = Provider(self.lead, self.receipt["occurred_at"])
        first = enrich_form_leads(client, self.ledger, go_live=self.go_live)
        self.assertEqual(first["attempted"], 1)
        self.assertEqual(first["verified"], 1)
        self.assertEqual(client.puts, 1)
        self.assertEqual(self.lead["Email"], self.receipt["submitted_email"])
        self.assertEqual(self.lead["First_Source"], "zoho_form")
        self.assertEqual(self.lead["Inquiry_ID"], self.receipt["event_id"])
        self.assertTrue(self.lead["OptiBrain_Test"])
        self.assertEqual(self.ledger.verified_test_ids(), {"777"})
        self.assertEqual(len(IntakeLedger(self.ledger.path.parent / "phase9-intake.db").trace("777")["events"]), 1)
        self.assertEqual(enrich_form_leads(client, self.ledger, go_live=self.go_live)["attempted"], 0)
        self.assertEqual(client.puts, 1)

    def test_protected_target_and_wrong_creation_source_never_transport(self):
        for protection, source in [({"777"}, "zoho_forms"), ({"999"}, "crm_api")]:
            with self.subTest(protection=protection, source=source), patch(
                    "workflow.automation.phase9_form_enrichment.protected_ids",
                    return_value=(protection, aware(self.go_live)-timedelta(days=1))):
                client = Provider(self.lead, self.receipt["occurred_at"], source=source)
                result = enrich_form_leads(client, self.ledger, go_live=self.go_live)
                self.assertEqual(result["review"], 1)
                self.assertEqual(client.puts, 0)

    def test_existing_exact_email_collision_requires_review(self):
        client = Provider(self.lead, self.receipt["occurred_at"], other_email=self.receipt["submitted_email"])
        self.assertEqual(enrich_form_leads(client, self.ledger, go_live=self.go_live)["review"], 1)
        self.assertEqual(client.puts, 0)

    def test_lost_ack_reconciles_without_second_write(self):
        client = Provider(self.lead, self.receipt["occurred_at"], fail_after_put=True)
        with self.assertRaises(TimeoutError):
            enrich_form_leads(client, self.ledger, go_live=self.go_live)
        self.assertEqual(self.ledger.enrichment_state(self.receipt["event_id"])["state"], "ATTEMPTED")
        self.assertEqual(enrich_form_leads(client, self.ledger, go_live=self.go_live)["verified"], 1)
        self.assertEqual(client.puts, 1)

    def test_feedback_failure_after_verified_write_recovers_without_second_put(self):
        client = Provider(self.lead, self.receipt["occurred_at"])
        with patch("workflow.automation.phase9_form_enrichment._record_test_intake",
                   side_effect=PermissionError("ledger unavailable")):
            with self.assertRaises(PermissionError):
                enrich_form_leads(client, self.ledger, go_live=self.go_live)
        self.assertEqual(self.ledger.enrichment_state(self.receipt["event_id"])["state"], "VERIFIED")
        self.assertEqual(enrich_form_leads(client, self.ledger, go_live=self.go_live)["attempted"], 0)
        self.assertEqual(client.puts, 1)
        trace = IntakeLedger(self.ledger.path.parent / "phase9-intake.db").trace("777")
        self.assertEqual([item["kind"] for item in trace["feedback"]], ["LEAD_CREATED"])

    def test_transport_rejects_unjournaled_protected_and_mismatched_field(self):
        body = {"data": [{"id": "999", "Email": self.receipt["submitted_email"]}],
                "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
        headers = {"If-Unmodified-Since": self.lead["Modified_Time"]}
        value = {"crm_id": "999", "ledger": self.ledger, "event_id": self.receipt["event_id"],
                 "baseline_path": Path("/ignored"), "hash": "0"*64}
        with patch("workflow.automation.phase9_form_enrichment.protected_ids",
                   return_value=({"999"}, aware(self.go_live)-timedelta(days=1))):
            with self.assertRaisesRegex(ValueError, "protected"):
                validate_form_request("PUT", "/crm/v8/Leads/999", body, headers, value)


if __name__ == "__main__":
    unittest.main()
