"""Focused queue, identity, due-state and controlled Task boundary checks."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.sales_queue import (
    analyze_queue, future_controlled_draft, neglected, render_sales_queue)
from workflow.automation.crm_write_boundary import (
    PHASE8_TEST_TASK_POLICY, fingerprint, require_authority,
    reviewed_phase8_test_task_call, validate_phase8_test_task, verify_transport_authority,
)
from workflow.operator_phase7_api import install_phase7_canary_routes

SPEC = importlib.util.spec_from_file_location(
    "phase8_test_artifacts", Path(__file__).resolve().parents[3] / "ops/phase8/create_test_artifacts.py")
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)

NOW = datetime.fromisoformat("2026-09-30T18:00:00-04:00")
LEAD = "5062683000007880001"


def row(id, **changes):
    value = {"id": id, "Full_Name": "Customer", "Company": "Company",
             "Email": None, "Phone": "5141234567", "Lead_Status": None,
             "Converted__s": False, "Created_Time": "2026-08-01T12:00:00-04:00",
             "Modified_Time": "2026-08-01T12:00:00-04:00",
             "Next_Followup_At": None}
    value.update(changes)
    return value


class QueueTests(unittest.TestCase):
    def test_sparse_old_lead_is_not_neglected_or_high(self):
        leads = [row("123", Email="same@example.com"), row("124", Email="same@example.com")]
        view = analyze_queue(leads, [], [], None, now=NOW, leads_complete=True,
                             relationships_complete=True)
        self.assertEqual(view["summary"]["neglected"], 0)
        self.assertEqual(view["summary"]["overdue"], 0)
        self.assertEqual(view["summary"]["new_or_unreviewed"], 2)
        self.assertEqual({x["priority"] for x in view["rows"]}, {"MEDIUM"})
        self.assertTrue(all(x["duplicate"] == "DUPLICATE IN CRM" for x in view["rows"]))
        self.assertNotIn("READY FOR QUOTE", {x["quote"] for x in view["rows"]})

    def test_quote_requires_scope_site_timing_and_open_status(self):
        complete = row("123", Email="buyer@example.com", Lead_Status="Pre-Qualified",
                       Service_Types="Cameras", Street="12 Main", Scope="8 cameras",
                       Project_Timeline="October")
        partial = {**complete, "id": "124", "Email": "other@example.com", "Scope": None}
        view = analyze_queue([partial, complete], [], [], None, now=NOW,
                             leads_complete=True, relationships_complete=True)
        by_id = {x["id"]: x for x in view["rows"]}
        self.assertEqual(by_id["123"]["quote"], "READY FOR QUOTE")
        self.assertEqual(by_id["123"]["priority"], "HIGH")
        self.assertEqual(by_id["124"]["quote"], "NEEDS INFORMATION")
        self.assertEqual(view["rows"][0]["id"], "123")

    def test_relationships_remain_suggestions_and_html_escaped(self):
        lead = row("123", Full_Name="<Customer>", Company="ACME")
        contact = {"id": "888", "Full_Name": "<Customer>", "Email": None}
        account = {"id": "999", "Account_Name": "ACME"}
        view = analyze_queue([lead], [contact], [account], None, now=NOW,
                             leads_complete=True, relationships_complete=True)
        self.assertEqual(view["rows"][0]["relationship"]["state"], "SUGGESTED")
        html = render_sales_queue(view)
        self.assertIn("&lt;Customer&gt;", html)
        self.assertNotIn("<Customer>", html)

    def test_neglected_requires_verified_no_reply_and_inactive_window(self):
        due = datetime.fromisoformat("2026-09-25T17:00:00-04:00")
        modified = due - timedelta(days=1)
        sent = (due - timedelta(days=3)).isoformat()
        args = dict(status="Not Contacted", deadline=due, modified=modified,
                    last_outbound=sent, reply_state="NO_REPLY_YET", now=NOW)
        self.assertTrue(neglected(**args))
        self.assertFalse(neglected(**{**args, "reply_state": "REPLIED"}))
        self.assertFalse(neglected(**{**args, "reply_state": "AMBIGUOUS"}))
        self.assertFalse(neglected(**{**args, "last_outbound": (NOW-timedelta(hours=1)).isoformat()}))
        self.assertFalse(neglected(**{**args, "status": "Lost Lead"}))
        self.assertFalse(neglected(**{**args, "modified": NOW-timedelta(hours=1)}))

    def test_future_draft_only_while_waiting_without_reply(self):
        controlled = {"lead": {"id": LEAD},
                      "follow_up": {"status": "WAIT", "current": "Oct 1, 2026 5:00 PM EDT"},
                      "evidence": {"mail": {"reply_state": "NO_REPLY_YET",
                                             "last_outbound": {"message_id": "123"}}},
                      "known": {"service_interest": "AI loss prevention", "city": "Montreal"}}
        draft = future_controlled_draft(controlled)
        self.assertIn("Hold for human review after Oct 1", draft["body"])
        self.assertIn("camera count", draft["body"])
        self.assertIsNone(future_controlled_draft({
            **controlled, "evidence": {"mail": {"reply_state": "REPLIED",
                                                "last_outbound": {"message_id": "123"}}}}))

    def test_montreal_deadline_edt(self):
        self.assertEqual(
            analyze_queue([row("123", Next_Followup_At="2026-10-01T21:00:00+00:00")],
                          [], [], None, now=NOW, leads_complete=True,
                          relationships_complete=True)["rows"][0]["deadline"],
            "Oct 1, 2026 5:00 PM EDT")
        self.assertEqual(
            analyze_queue([row("123", Next_Followup_At="2026-12-01T22:00:00+00:00")],
                          [], [], None, now=NOW, leads_complete=True,
                          relationships_complete=True)["rows"][0]["deadline"],
            "Dec 1, 2026 5:00 PM EST")
        self.assertEqual(
            analyze_queue([row("123", Next_Followup_At="2026-11-01T06:30:00+00:00")],
                          [], [], None, now=NOW, leads_complete=True,
                          relationships_complete=True)["rows"][0]["deadline"],
            "Nov 1, 2026 1:30 AM EST")
        with self.assertRaises(ValueError):
            analyze_queue([row("123", Next_Followup_At="2026-10-01T17:00:00")],
                          [], [], None, now=NOW, leads_complete=True,
                          relationships_complete=True)


class TaskBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.body = {"data": [{"Subject": f"TEST ONLY — OPTIBRAIN PHASE 8 — {LEAD} — " + "a"*16,
                               "What_Id": {"id": LEAD}, "$se_module": "Leads", "Status": "Not Started",
                               "Due_Date": "2026-10-01"}], "trigger": []}

    def test_exact_task_and_single_use_root_only(self):
        validate_phase8_test_task("POST", "/crm/v8/Tasks", self.body, None)
        client = object()
        h = fingerprint("POST", "/crm/v8/Tasks", self.body, None)
        with patch("workflow.automation.crm_write_boundary.os.geteuid", return_value=0), patch.dict(
                os.environ, {"OPTIBRAIN_PHASE8_TEST_TASK": PHASE8_TEST_TASK_POLICY}):
            with reviewed_phase8_test_task_call(client, self.body, payload_hash=h):
                require_authority(client, "zohoapis", "POST", "/crm/v8/Tasks", self.body, None)
                verify_transport_authority(client, "zohoapis", "POST", "/crm/v8/Tasks", self.body, None)
                with self.assertRaises(ValueError):
                    require_authority(client, "zohoapis", "POST", "/crm/v8/Tasks", self.body, None)
        with patch("workflow.automation.crm_write_boundary.os.geteuid", return_value=1000), patch.dict(
                os.environ, {"OPTIBRAIN_PHASE8_TEST_TASK": PHASE8_TEST_TASK_POLICY}):
            with self.assertRaises(ValueError):
                reviewed_phase8_test_task_call(client, self.body, payload_hash=h).__enter__()

    def test_other_lead_and_extra_fields_rejected(self):
        changed = {"data": [{**self.body["data"][0], "What_Id": {"id": "999"}}], "trigger": []}
        with self.assertRaises(ValueError):
            validate_phase8_test_task("POST", "/crm/v8/Tasks", changed, None)
        changed["data"][0]["What_Id"] = {"id": LEAD}
        changed["data"][0]["Description"] = "hidden extra"
        with self.assertRaises(ValueError):
            validate_phase8_test_task("POST", "/crm/v8/Tasks", changed, None)

    def test_task_dedupe_fails_closed_on_collision(self):
        class Client:
            def request(self, service, method, path, **kwargs):
                return {"ok": True, "status": 200, "data": {"data": [
                    {"id": "555", "Subject": "subject", "What_Id": {"id": "999"},
                     "Due_Date": "2026-10-01", "Status": "Not Started"}]}}
        with self.assertRaisesRegex(ValueError, "collision"):
            ARTIFACTS.task_search(Client(), "subject", "2026-10-01")
        self.assertEqual(ARTIFACTS.task_id_from_ack({
            "ok": True, "status": 201,
            "data": {"data": [{"status": "success", "details": {"id": "555"}}]}}), "555")
        with self.assertRaises(ValueError):
            ARTIFACTS.task_id_from_ack({"ok": True, "status": 201, "data": {"data": []}})

    def test_draft_reconciliation_requires_unique_folder_result(self):
        class Client:
            def request(self, service, method, path, **kwargs):
                return {"ok": True, "status": 200, "data": {"status": {"code": 200}, "data": [
                    {"messageId": "1", "subject": "test", "toAddress": "hckyan97@gmail.com"},
                    {"messageId": "2", "subject": "other", "toAddress": "hckyan97@gmail.com"}]}}
        self.assertEqual(len(ARTIFACTS.draft_candidates(Client(), "test")), 1)


class QueueRouteTests(unittest.TestCase):
    def test_auth_and_get_only(self):
        class Identity:
            def verify(self, token):
                if token != "human": raise ValueError("verified human required")
                return type("Person", (), {"subject": "owner"})()
        app = FastAPI()
        store = type("Store", (), {"db_path": "/tmp/no-db"})()
        install_phase7_canary_routes(app, verifier=Identity(), client=object(), store=store,
                                     account_id="123", from_address="sales@example.com",
                                     allowed_origin="https://operator.example.com")
        client = TestClient(app)
        path = "/v1/operator/phase8/sales-queue"
        self.assertEqual(client.get(path).status_code, 401)
        with patch("workflow.operator_phase7_api.build_sales_queue", return_value={
                "label": "Sample", "sample_count": 0, "read_at": "Sep 30, 2026 6:00 PM EDT",
                "summary": {key: 0 for key in ("needs_attention_now", "waiting_for_reply",
                    "replies_needing_response", "followup_due", "overdue", "potentially_quote_ready",
                    "missing_critical_information", "new_or_unreviewed")}, "rows": []}):
            response = client.get(path, headers={"Cf-Access-Jwt-Assertion": "human"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("What should I work on now?", response.text)
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(client.post(path, headers={"Cf-Access-Jwt-Assertion": "human"}).status_code, 405)
