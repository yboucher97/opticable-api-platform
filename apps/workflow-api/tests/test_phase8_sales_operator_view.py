"""Focused proof of the controlled read-only operator sales view."""
from datetime import datetime, timedelta, timezone
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
from workflow.automation.followup_mail import followup_status
from workflow.automation.store import AutomationStore
from workflow.operator_phase7_api import install_phase7_canary_routes


class FakeCrm:
    def __init__(self):
        self.calls = []
        self.inbound = []
        self.inbound_body = {}
        self.inbound_headers = {}
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
        assert method == "GET"
        if provider == "mail":
            if path.endswith("/messages/search"):
                return {"ok": True, "status": 200, "data": {"status": {"code": 200},
                                                                "data": list(self.inbound)}}
            message_id = path.split("/")[-2]
            suffix = path.rsplit("/", 1)[-1]
            if message_id == "1790714949014155100":
                if suffix == "details":
                    data = {"messageId": message_id, "folderId": "1083319000000008022",
                            "fromAddress": "yboucher@opticable.ca",
                            "toAddress": "&lt;hckyan97@gmail.com&gt;",
                            "subject": "Your inquiry with Opticable",
                            "receivedTime": "1790714949009", "sentDateInGMT": "1790740148000"}
                else:
                    data = {"headerContent": {"Message-ID": ["<controlled@opticable.ca>"],
                                              "Date": ["Tue, 29 Sep 2026 16:49:08 -0400"]}}
            elif message_id in self.inbound_headers:
                row = next(item for item in self.inbound if str(item["messageId"]) == message_id)
                if suffix == "details":
                    data = dict(row)
                    data["toAddress"] = "yboucher@opticable.ca"
                elif suffix == "header":
                    data = {"headerContent": self.inbound_headers[message_id]}
                else:
                    data = {"content": {"content": self.inbound_body[message_id]}}
            else:
                raise AssertionError("Unreviewed Mail path")
            return {"ok": True, "status": 200, "data": {"status": {"code": 200}, "data": data}}
        assert provider == "zohoapis"
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
        self.record_outbound()

    def record_outbound(self, recipient="hckyan97@gmail.com"):
        self.store.audit(category="outbound_approval_v1", action="consumed",
                         actor="automation-engine", success=True,
                         metadata={"source_id": f"phase7:{CONTROLLED_LEAD_ID}:" + "a" * 64,
                                   "source_type": "lead", "action_type": "send_new_email",
                                   "account_id": "1083319000000008002",
                                   "from_address": "yboucher@opticable.ca",
                                   "recipient": recipient,
                                   "provider_operation_id": "1790714949014155100"})
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("UPDATE automation_audit SET at=? WHERE category='outbound_approval_v1'",
                       ("2026-09-29T20:49:09.135723Z",))

    def view(self, clock=None):
        return build_sales_operator_view(self.crm, self.store.db_path,
                                         account_id="1083319000000008002",
                                         from_address="yboucher@opticable.ca",
                                         now=clock or self.clock)

    def add_reply(self, *, linked=True, body="Site address: 123 Test St\nCamera count: 12\nTimeline: November"):
        received = datetime.fromisoformat("2026-09-30T16:00:00-04:00")
        message_id = "1790800000000000001"
        self.crm.inbound = [{"messageId": message_id, "folderId": "1083319000000008003",
                             "fromAddress": "hckyan97@gmail.com", "subject": "Re: Your inquiry with Opticable",
                             "receivedTime": str(int(received.timestamp() * 1000)),
                             "summary": body[:100]}]
        self.crm.inbound_headers[message_id] = {
            "Message-ID": ["<reply@example.com>"],
            "In-Reply-To": ["<controlled@opticable.ca>" if linked else "<other@example.com>"]}
        self.crm.inbound_body[message_id] = body

    def test_realistic_inquiry_produces_useful_unsent_view(self):
        view = self.view()
        self.assertEqual(len(self.crm.calls), 6)
        self.assertTrue(all(method == "GET" for _, method, _ in self.crm.calls))
        self.assertEqual(view["source"]["label"], "AI website")
        self.assertTrue(view["source"]["description_agrees"])
        self.assertEqual(view["dedupe"]["matches"], 1)
        self.assertEqual(view["qualification"]["priority"], "Medium")
        self.assertEqual(view["quote_readiness"]["status"], "NEEDS INFORMATION")
        self.assertIn("Camera count and coverage areas", view["missing_information"])
        self.assertIn("Confirm preferred reply language", " ".join(view["missing_information"]))
        self.assertEqual(view["follow_up"]["current"], "Oct 1, 2026 5:00 PM EDT")
        self.assertEqual(view["follow_up"]["status"], "WAIT")
        self.assertEqual(view["evidence"]["mail"]["reply_state"], "NO_REPLY_YET")
        self.assertTrue(view["evidence"]["mail"]["last_outbound"]["provider_sent_date_disagrees"])
        self.assertFalse(view["follow_up"]["overdue"])
        self.assertEqual(view["draft"]["label"], "DRAFT — NOT SENT")
        self.assertIsNone(view["draft"]["body"])
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

    def test_est_and_dst_fallback_due_use_instants(self):
        self.crm.record["Next_Followup_At"] = "2026-11-01T01:30:00-04:00"
        self.assertEqual(self.view(datetime.fromisoformat("2026-11-01T01:15:00-04:00"))["follow_up"]["status"], "WAIT")
        # Same wall-clock hour, different offset: this is after the EDT deadline.
        after = self.view(datetime.fromisoformat("2026-11-01T01:15:00-05:00"))
        self.assertEqual(after["follow_up"]["status"], "DUE")
        self.assertEqual(after["follow_up"]["current"], "Nov 1, 2026 1:30 AM EDT")
        self.crm.record["Next_Followup_At"] = "2026-12-01T17:00:00-05:00"
        self.assertEqual(self.view(datetime.fromisoformat("2026-12-01T17:01:00-05:00"))["follow_up"]["status"], "DUE")
        self.assertEqual(self.view(datetime.fromisoformat("2026-12-02T17:01:00-05:00"))["follow_up"]["status"], "OVERDUE")
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

    def test_prior_consumed_send_prevents_early_followup(self):
        view = self.view()
        self.assertEqual(view["next_action"]["primary"],
                         "Wait until the scheduled follow-up; monitor for a reply")
        self.assertEqual(view["evidence"]["prior_outbound"]["latest"]["provider_message_id"],
                         "1790714949014155100")
        self.assertIsNone(view["draft"]["body"])
        self.assertIn("1790714949014155100", render_sales_operator_view(view))
        due = self.view(datetime.fromisoformat("2026-10-01T17:01:00-04:00"))
        self.assertEqual(due["follow_up"]["status"], "DUE")
        self.assertIn("following up", due["draft"]["body"].lower())

    def test_other_recipient_does_not_claim_a_prior_send(self):
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("DELETE FROM automation_audit WHERE category='outbound_approval_v1'")
        self.record_outbound(recipient="other@example.com")
        view = self.view()
        self.assertIsNone(view["evidence"]["prior_outbound"])
        self.assertEqual(view["follow_up"]["status"], "AMBIGUOUS")
        self.assertIsNone(view["draft"]["body"])

    def test_linked_reply_suppresses_chase_and_updates_provisional_missing(self):
        self.add_reply()
        view = self.view(datetime.fromisoformat("2026-10-02T18:00:00-04:00"))
        self.assertEqual(view["evidence"]["mail"]["reply_state"], "REPLIED")
        self.assertEqual(view["follow_up"]["status"], "REPLIED — REVIEW RESPONSE")
        self.assertIsNone(view["draft"]["body"])
        self.assertIn("Verify site address from reply", view["missing_information"])
        self.assertIn("Camera count: 12", " ".join(view["new_from_reply"]))
        self.assertIn("Review the customer reply", view["next_action"]["primary"])

    def test_unrelated_incoming_same_sender_is_ambiguous(self):
        self.add_reply(linked=False)
        view = self.view(datetime.fromisoformat("2026-10-02T18:00:00-04:00"))
        self.assertEqual(view["follow_up"]["status"], "AMBIGUOUS")
        self.assertIsNone(view["draft"]["body"])

    def test_sent_copy_of_alias_reply_does_not_hide_linked_inbound(self):
        self.add_reply(body="Service: Wi-Fi\nScope: 12 access points\nTimeline: Within three weeks")
        self.crm.inbound.append({"messageId": "1790800000000000002",
                                 "folderId": "1083319000000008022",
                                 "fromAddress": "hckyan97@gmail.com",
                                 "receivedTime": "1790800000001"})
        view = self.view(datetime.fromisoformat("2026-10-02T18:00:00-04:00"))
        self.assertEqual(view["evidence"]["mail"]["reply_state"], "REPLIED")
        self.assertIn("Scope: 12 access points", " ".join(view["new_from_reply"]))

    def test_inbound_details_time_drift_is_ambiguous(self):
        self.add_reply()
        original = self.crm.request
        def drift(provider, method, path, **kwargs):
            value = original(provider, method, path, **kwargs)
            if provider == "mail" and path.endswith("1790800000000000001/details"):
                value["data"]["data"]["receivedTime"] = "1790000000000"
            return value
        self.crm.request = drift
        view = self.view(datetime.fromisoformat("2026-10-02T18:00:00-04:00"))
        self.assertEqual(view["follow_up"]["status"], "AMBIGUOUS")
        self.assertIsNone(view["draft"]["body"])

    def test_mail_search_failure_fails_closed(self):
        original = self.crm.request
        def failed(provider, method, path, **kwargs):
            if provider == "mail" and path.endswith("/messages/search"):
                return {"ok": False, "status": 502, "data": {}}
            return original(provider, method, path, **kwargs)
        self.crm.request = failed
        with self.assertRaisesRegex(ValueError, "Mail read failed"):
            self.view()

    def test_recent_send_after_deadline_waits_before_another_outreach(self):
        mail = {"reply_state": "NO_REPLY_YET",
                "last_outbound": {"sent_at": "2026-10-01T20:30:00+00:00"}}
        deadline = datetime.fromisoformat("2026-10-01T21:00:00+00:00")
        self.assertEqual(followup_status(mail, deadline=deadline,
            now=datetime.fromisoformat("2026-10-01T22:00:00+00:00"),
            crm_modified=datetime.fromisoformat("2026-09-29T20:50:31+00:00"), active=True), "WAIT")

    def test_recent_crm_activity_prevents_neglected_label(self):
        mail = {"reply_state": "NO_REPLY_YET",
                "last_outbound": {"sent_at": "2026-09-29T20:49:09+00:00"}}
        deadline = datetime.fromisoformat("2026-10-01T21:00:00+00:00")
        self.assertEqual(followup_status(mail, deadline=deadline,
            now=datetime.fromisoformat("2026-10-03T21:00:00+00:00"),
            crm_modified=datetime.fromisoformat("2026-10-03T20:00:00+00:00"), active=True), "DUE")

    def test_route_requires_human_and_is_read_only(self):
        app = FastAPI()
        install_phase7_canary_routes(
            app, verifier=Identity(), client=self.crm, store=self.store,
            account_id="1083319000000008002", from_address="yboucher@opticable.ca",
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
