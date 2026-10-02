from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import sqlite3
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workflow.operator_phase7_api import install_phase7_canary_routes

from workflow.automation.phase9_form_receipts import (
    FormReceiptLedger, collect_form_mail, collect_connector_receipts, parse_notification,
    reconcile_form_crm,
)


MESSAGE = "1790820040661162800"
EMAIL = "hckyan97+obp9form1@gmail.com"
HTML = """<table><tr><td>Nom du contact</td><td>:</td><td>Phase Nine, OPTIBRAIN TEST PHASE 9</td></tr>
<tr><td>Entreprise</td><td>:</td><td>OPTIBRAIN TEST — PHASE 9 — Warehouse</td></tr>
<tr><td>Courriel</td><td>:</td><td>hckyan97+obp9form1@gmail.com</td></tr>
<tr><td>Téléphone</td><td>:</td><td>5145550187</td></tr>
<tr><td>Code de référence / partenaire</td><td>:</td><td>OBP9-FORM-1</td></tr>
<tr><td>Notes sur le projet</td><td>:</td><td>TEST ONLY synthetic project</td></tr></table>"""
DETAILS = {"messageId": MESSAGE, "fromAddress": "notifications@zohoforms.com",
           "toAddress": "&lt;soumissions@opticable.ca&gt;", "receivedTime": "1790820040656",
           "subject": "Demande de soumission de OPTIBRAIN TEST — PHASE 9 — Warehouse"}
HEADERS = {"Authentication-Results": ["dkim=pass; dmarc=pass header.from=zohoforms.com"],
           "Message-ID": ["<unique@public.zohoforms.com>"]}
NOW = datetime(2026, 10, 1, 3, tzinfo=timezone.utc)


class FormReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = FormReceiptLedger(Path(self.temp.name) / "phase9-form-receipts.db")
        self.receipt = parse_notification(message_id=MESSAGE, details=DETAILS,
            content={"content": HTML}, headers=HEADERS, now=NOW)

    def test_real_shape_creates_one_immutable_receipt_and_replays(self):
        self.assertEqual(self.receipt["submitted_email"], EMAIL)
        self.assertTrue(self.receipt["test_only"])
        self.assertEqual(self.receipt["campaign"], None)
        self.assertEqual(self.ledger.record(self.receipt), "CREATED")
        self.assertEqual(stat.S_IMODE(self.ledger.path.stat().st_mode), 0o600)
        self.assertEqual(self.ledger.record(self.receipt), "REPLAY")
        self.assertEqual(len(self.ledger.list()), 1)
        with sqlite3.connect(self.ledger.path) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE form_receipts SET source='manual_crm'")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.record({**self.receipt, "campaign": "invented"})

    def test_published_english_form_labels_are_supported_without_invented_campaign(self):
        body = """<table><tr><td>Name of the contact</td><td>:</td><td>Phase Nine, Test</td></tr>
        <tr><td>Company</td><td>:</td><td>OPTIBRAIN TEST — PHASE 9 — Warehouse</td></tr>
        <tr><td>Email</td><td>:</td><td>hckyan97+obp9form1@gmail.com</td></tr>
        <tr><td>Phone</td><td>:</td><td>5145550187</td></tr>
        <tr><td>Description of your needs</td><td>:</td><td>TEST ONLY</td></tr></table>"""
        result = parse_notification(message_id=MESSAGE, details=DETAILS,
            content={"content": body}, headers=HEADERS, now=NOW)
        self.assertEqual(result["source_detail"], "Main website English quote form")
        self.assertIsNone(result["campaign"])

    def test_untrusted_notification_and_future_time_fail_closed(self):
        for details, headers, clock in [
            ({**DETAILS, "fromAddress": "attacker@example.com"}, HEADERS, NOW),
            (DETAILS, {**HEADERS, "Authentication-Results": ["dkim=fail"]}, NOW),
            (DETAILS, HEADERS, datetime(2026, 9, 30, tzinfo=timezone.utc)),
        ]:
            with self.assertRaises(ValueError):
                parse_notification(message_id=MESSAGE, details=details,
                                   content={"content": HTML}, headers=headers, now=clock)
    def test_controlled_owner_destination_and_phase16_lineage(self):
        content=HTML.replace(EMAIL,'logs@opticable.ca').replace('OPTIBRAIN TEST — PHASE 9 — Warehouse','OPTIBRAIN TEST — PHASE 16 — Form Company').replace('OBP9-FORM-1','phase16-20261002-lifecycle-v1-form-fr')
        details={**DETAILS,'toAddress':'&lt;yboucher@opticable.ca&gt;'}
        receipt=parse_notification(message_id=MESSAGE,details=details,content={'content':content},headers=HEADERS,now=NOW)
        self.assertTrue(receipt['test_only'])
        for recipient in ('soumissions@opticable.ca.evil.example','customer@example.net'):
            with self.subTest(recipient=recipient),self.assertRaises(ValueError):
                parse_notification(message_id=MESSAGE,details={**details,'toAddress':recipient},content={'content':content},headers=HEADERS,now=NOW)

    def test_link_requires_registered_test_provider_readback(self):
        self.ledger.record(self.receipt)
        crm = {"id": "123456", "Email": EMAIL, "OptiBrain_Test": True,
               "Description": "OPTIBRAIN TEST — PHASE 9\nSynthetic",
               "Modified_Time": "2026-10-01T00:00:00Z"}
        with self.assertRaises(ValueError):
            self.ledger.link_test_lead(self.receipt["event_id"], crm, set())
        with self.assertRaises(ValueError):
            self.ledger.link_test_lead(self.receipt["event_id"], {**crm, "OptiBrain_Test": False}, {"123456"})
        self.assertEqual(self.ledger.link_test_lead(self.receipt["event_id"], crm, {"123456"}), "LINKED")
        self.assertEqual(self.ledger.link_test_lead(self.receipt["event_id"], crm, {"123456"}), "REPLAY")
        self.assertEqual(self.ledger.list()[0]["canonical_id"], "123456")

    def test_new_test_classifier_preserves_original_provider_receipt(self):
        original = {**self.receipt, "test_only": False}
        self.ledger.record(original)
        self.assertEqual(self.ledger.record(self.receipt), "REPLAY")
        row = self.ledger.list()[0]
        self.assertTrue(row["test_only"])
        self.assertFalse(row["original_test_only"])
        self.assertEqual(json.loads(row["evidence_json"]), original)
        with sqlite3.connect(self.ledger.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM form_test_classifications").fetchone()[0], 1)
            for statement in ("DELETE FROM form_test_classifications", "UPDATE form_test_classifications SET event_id='other'"):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.record({**self.receipt, "fields": {**self.receipt["fields"], "company": "changed"}})

    def test_classification_cannot_turn_real_intake_into_test_or_reverse_exclusion(self):
        real = {**self.receipt, "submitted_email": "customer@example.net", "test_only": False}
        self.ledger.record(real)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.record({**real, "test_only": True})
        other = FormReceiptLedger(Path(self.temp.name) / "other.db")
        other.record(self.receipt)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            other.record({**self.receipt, "test_only": False})

    def test_unique_main_form_crm_match_is_read_only_and_missing_email_is_visible(self):
        self.ledger.record(self.receipt)
        original = {"id": "123456", "First_Name": "Phase Nine",
                    "Last_Name": "OPTIBRAIN TEST PHASE 9", "Company": "OPTIBRAIN TEST — PHASE 9 — Warehouse",
                    "Phone": "5145550187", "Email": None,
                    "Created_Time": "2026-09-30T22:00:40-04:00"}
        # The fixture name mirrors the real provider's comma-separated form value.
        changed = {**self.receipt, "fields": {**self.receipt["fields"],
                   "name": "Phase Nine, OPTIBRAIN TEST PHASE 9", "phone": "5145550187"}}
        self.ledger = FormReceiptLedger(Path(self.temp.name) / "another.db")
        self.ledger.record(changed)
        class Client:
            calls = []
            def request(self, service, method, path, **kwargs):
                self.calls.append((service, method, path))
                return {"ok": True, "data": {"data": [original], "info": {"more_records": False}}}
        client = Client()
        self.assertEqual(reconcile_form_crm(client, self.ledger)["matched"], 1)
        self.assertEqual(self.ledger.list()[0]["provider_match_status"], "MATCHED_MISSING_EMAIL")
        self.assertEqual(self.ledger.list()[0]["canonical_id"], "123456")
        self.assertTrue(all(method == "GET" for _, method, _ in client.calls))
        self.ledger.record_connector({"schema": 1, "source": "ai_website",
            "origin": "https://ai.opticable.ca", "inquiry_id": "return-b",
            "request_hash": "c" * 64, "occurred_at": "2026-10-01T02:30:00Z",
            "submitted_email": EMAIL, "attribution": {"last_campaign": "test-return"},
            "action": "updated_lead", "module": "Leads", "record_id": "123456"})
        self.assertEqual([event["source"] for event in self.ledger.timeline("123456")],
                         ["zoho_form", "ai_website"])

    def test_collector_fetches_read_only_and_deduplicates(self):
        class Client:
            def __init__(self):
                self.calls = []
            def request(self, service, method, path, **kwargs):
                self.calls.append((service, method, path))
                if path.endswith("/messages/search"):
                    data = [{"messageId": MESSAGE, "folderId": "777", "fromAddress": DETAILS["fromAddress"]}]
                elif path.endswith("/details"):
                    data = DETAILS
                elif path.endswith("/content"):
                    data = {"content": HTML}
                elif path.endswith("/header"):
                    data = {"headerContent": HEADERS}
                else:
                    raise AssertionError(path)
                return {"ok": True, "data": {"data": data}}
        client = Client()
        self.assertEqual(collect_form_mail(client, self.ledger, now=NOW)["created"], 1)
        self.assertEqual(collect_form_mail(client, self.ledger, now=NOW)["replayed"], 1)
        self.assertTrue(all(method == "GET" for _, method, _ in client.calls))

    def test_authenticated_connector_export_preserves_event_and_detects_conflict(self):
        receipt = {"schema": 1, "source": "ai_website", "origin": "https://ai.opticable.ca",
                   "inquiry_id": "stable-intake-a", "request_hash": "a" * 64,
                   "occurred_at": "2026-10-01T00:10:00Z", "submitted_email": EMAIL,
                   "attribution": {"last_campaign": "test"}, "action": "updated_lead",
                   "module": "Leads", "record_id": "123456", "possible_duplicate_record_id": None}
        class Http:
            def get(self, url, *, params, headers):
                assert url == "https://connect.opticable.ca/api/intake-receipts"
                assert headers == {"Authorization": "Bearer read-only-key"}
                class Response:
                    status_code = 200
                    def json(self):
                        return {"ok": True, "receipts": [receipt], "cursor": None}
                return Response()
        self.assertEqual(collect_connector_receipts(Http(), self.ledger,
            base_url="https://connect.opticable.ca", api_key="read-only-key")["created"], 1)
        self.assertEqual(collect_connector_receipts(Http(), self.ledger,
            base_url="https://connect.opticable.ca", api_key="read-only-key")["replayed"], 1)
        self.assertEqual(self.ledger.list_connector()[0]["canonical_id"], "123456")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.ledger.record_connector({**receipt, "request_hash": "b" * 64})
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.ledger.record_connector({**receipt, "attribution": {"last_campaign": "changed"}})
        ambiguous = {**receipt, "inquiry_id": "stable-intake-b", "request_hash": "c" * 64,
                     "action": "possible_duplicate", "record_id": None,
                     "possible_duplicate_record_id": "123456"}
        self.assertEqual(self.ledger.record_connector(ambiguous), "CREATED")
        self.assertIsNone(next(row for row in self.ledger.list_connector()
                               if row["inquiry_id"] == "stable-intake-b")["canonical_id"])
        with self.assertRaises(ValueError):
            self.ledger.record_connector({**ambiguous, "record_id": "123456"})

    def test_operator_receipts_are_authenticated_and_escaped(self):
        class Verifier:
            def verify(self, token):
                if token != "operator":
                    raise ValueError("missing identity")
                return type("Person", (), {"subject": "operator"})()
        class Store:
            db_path = Path(self.temp.name) / "automation.db"
        self.ledger.record(self.receipt)
        app = FastAPI()
        install_phase7_canary_routes(app, verifier=Verifier(), client=object(), store=Store(),
                                     account_id="1", from_address="operator@example.com",
                                     allowed_origin="https://optibrain.example.com")
        api = TestClient(app)
        self.assertEqual(api.get("/v1/operator/phase9/intake-receipts").status_code, 401)
        result = api.get("/v1/operator/phase9/intake-receipts",
                         headers={"Cf-Access-Jwt-Assertion": "operator"})
        self.assertEqual(result.status_code, 200)
        self.assertIn("need CRM review", result.text)
        self.assertIn(self.receipt["event_id"], result.text)
        self.assertIn("EDT", result.text)


if __name__ == "__main__":
    unittest.main()
