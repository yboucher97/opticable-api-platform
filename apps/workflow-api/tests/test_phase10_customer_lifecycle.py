"""Focused lifecycle decisions and the existing protected CRM boundary."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.customer_lifecycle import (
    analyze_customer, build_customer_lifecycle, render_customer_lifecycle,
)
from workflow.automation.test_lab_boundary import validate_lab_request
from workflow.automation.lifecycle_events import sync_verified_lab_events
from workflow.operator_phase7_api import install_phase7_canary_routes

NOW = datetime.fromisoformat("2026-10-01T12:00:00-04:00")
MARKER = "OPTIBRAIN TEST — PHASE 10"


def account(identity="101", **updates):
    row = {"id": identity, "Account_Name": MARKER + " — Sample",
           "Description": MARKER + "\nSynthetic", "OptiBrain_Test": True}
    row.update(updates)
    return row


def deal(identity="201", **updates):
    row = {"id": identity, "Deal_Name": MARKER + " — Service", "Stage": "Closed Won",
           "Account_Name": {"id": "101"}, "Service_Types": "Cameras",
           "Description": MARKER + "\nSynthetic", "OptiBrain_Test": True,
           "Created_Time": "2026-09-01T12:00:00-04:00",
           "Modified_Time": "2026-09-01T12:00:00-04:00",
           "OptiBrain_Installed_On": "2026-01-01",
           "OptiBrain_Last_Service_On": "2026-09-01"}
    row.update(updates)
    return row


def decision(item):
    return analyze_customer(account(), [], [item], now=NOW, test_only=True)


class LifecycleTests(unittest.TestCase):
    def test_dormancy_requires_completed_work_and_reacts_to_service(self):
        old = deal(OptiBrain_Installed_On="2023-01-01",
                   OptiBrain_Last_Service_On="2024-01-01")
        self.assertTrue(decision(old)["dormant"])
        self.assertEqual(decision(old)["action"], "Review dormant customer relationship")
        self.assertFalse(decision({**old, "OptiBrain_Last_Service_On": "2026-09-30"})["dormant"])
        self.assertFalse(decision({**old, "Stage": "Qualification"})["dormant"])

    def test_maintenance_due_then_current(self):
        old = deal(OptiBrain_Maintenance_Due="2026-09-25")
        self.assertTrue(decision(old)["maintenance_due"])
        self.assertFalse(decision({**old, "OptiBrain_Maintenance_Due": "2027-03-01"})["maintenance_due"])

    def test_renewal_window_and_recurring_service(self):
        item = deal(Service_Types="PTP link", OptiBrain_Recurrence="Annual",
                    OptiBrain_Renewal_On="2027-01-01")
        self.assertFalse(decision(item)["renewal_due"])
        self.assertEqual(decision(item)["stage"], "RECURRING SERVICE")
        near = decision({**item, "OptiBrain_Renewal_On": "2026-10-25"})
        self.assertTrue(near["renewal_due"])
        self.assertEqual(near["action"], "Review recurring-service renewal")

    def test_active_project_has_one_delivery_action(self):
        item = decision(deal(Stage="Installation", OptiBrain_Installed_On=None,
                             OptiBrain_Last_Service_On=None))
        self.assertEqual(item["stage"], "ACTIVE PROJECT")
        self.assertEqual(item["action"], "Track active project delivery")
        self.assertFalse(item["renewal_due"] or item["maintenance_due"] or item["dormant"])

    def test_cross_sell_and_upsell_require_specific_evidence(self):
        cable = deal(Service_Types="Structured cabling", Description=MARKER + "\nWireless coverage planned")
        self.assertTrue(decision(cable)["cross_sell"])
        self.assertFalse(decision({**cable, "Description": MARKER + "\nCabling complete"})["cross_sell"])
        camera = deal(Description=MARKER + "\nExpansion wing has coverage gap")
        self.assertTrue(decision(camera)["upsell"])
        self.assertFalse(decision(deal())["upsell"])

    def test_no_action_and_sparse_historical_customer(self):
        healthy = decision(deal(OptiBrain_Maintenance_Due="2027-03-01"))
        self.assertEqual(healthy["action"], "No action — monitor")
        real = analyze_customer(account(OptiBrain_Test=False), [], [deal(
            OptiBrain_Test=False, OptiBrain_Installed_On=None,
            OptiBrain_Last_Service_On=None)], now=NOW, test_only=False)
        self.assertEqual((real["stage"], real["confidence"]), ("UNKNOWN", "INSUFFICIENT DATA"))
        self.assertEqual(real["action"], "No action — monitor")

    def test_montreal_dst_clock_and_html_escape(self):
        row = decision(deal(Last_Activity_Time="2026-11-01T06:30:00+00:00"))
        self.assertIn("EST", row["last_crm_activity"])
        self.assertIn("EDT", analyze_customer(account(), [], [deal(
            Last_Activity_Time="2026-10-01T16:30:00+00:00")], now=NOW,
            test_only=True)["last_crm_activity"])
        view = {"scope": "lab", "read_at": "Oct 1 EDT", "summary": {
            "needs_attention": 0, "renewal_due": 0, "maintenance_due": 0,
            "dormant": 0, "cross_sell": 0, "upsell": 0,
            "active_recurring": 0, "no_action": 1}, "rows": [{**row, "account": "<script>"}]}
        html = render_customer_lifecycle(view)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_maintenance_business_date_across_dst_change(self):
        item = deal(OptiBrain_Maintenance_Due="2026-11-01")
        before = datetime.fromisoformat("2026-11-01T03:30:00+00:00")
        after = datetime.fromisoformat("2026-11-01T04:30:00+00:00")
        self.assertFalse(analyze_customer(account(), [], [item], now=before,
                                           test_only=True)["maintenance_due"])
        self.assertTrue(analyze_customer(account(), [], [item], now=after,
                                          test_only=True)["maintenance_due"])

    def test_lifecycle_events_replay_without_duplicate(self):
        row = decision(deal())
        state = {"operations": {"camera_maintenance:deal": {"state": "verified",
            "payload_hash": "a" * 64, "at_utc": "2026-10-01T12:00:00+00:00"}},
            "scenarios": {"camera_maintenance": {"account_id": "101", "deal_id": "201"}}}
        view = {"scope": "lab", "writes_enabled": False, "rows": [row]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.db"
            self.assertEqual(sync_verified_lab_events(state, view, path)["added"], 2)
            self.assertEqual(sync_verified_lab_events(state, view, path)["added"], 0)

    def test_lab_exclusion_and_real_read_only_projection(self):
        class Client:
            def request(self, service, method, path, query=None):
                module = path.rsplit("/", 1)[-1]
                if module == "Accounts": rows = [account(), account("102", OptiBrain_Test=False)]
                elif module == "Contacts": rows = []
                else: rows = [deal()]
                return {"ok": True, "status": 200,
                        "data": {"data": rows, "info": {"more_records": False}}}
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "lab.json"
            registry.write_text(json.dumps({"records": {"Accounts": ["101"], "Contacts": [], "Deals": ["201"]}}))
            lab = build_customer_lifecycle(Client(), scope="lab", now=NOW, registry_path=registry)
            live = build_customer_lifecycle(Client(), scope="live", now=NOW, registry_path=registry)
            self.assertEqual([x["account_id"] for x in lab["rows"]], ["101"])
            self.assertEqual([x["account_id"] for x in live["rows"]], ["102"])
            self.assertFalse(live["writes_enabled"])
            self.assertIsNone(live["revenue_totals"])

    def test_operator_route_auth_and_read_only_render(self):
        class Client:
            def request(self, service, method, path, query=None):
                module = path.rsplit("/", 1)[-1]
                rows = ([account("102", OptiBrain_Test=False)] if module == "Accounts"
                        else [] if module == "Contacts" else [])
                return {"ok": True, "status": 200,
                        "data": {"data": rows, "info": {"more_records": False}}}
        class Verifier:
            def verify(self, token):
                if token != "controlled-test-token":
                    raise ValueError("missing identity")
                return SimpleNamespace(subject="operator")
        with tempfile.TemporaryDirectory() as tmp:
            app = FastAPI()
            install_phase7_canary_routes(app, verifier=Verifier(), client=Client(),
                store=SimpleNamespace(db_path=Path(tmp) / "automation.db"),
                account_id="1", from_address="operator@example.invalid",
                allowed_origin="https://operator.example.invalid", clock=lambda: NOW)
            http = TestClient(app)
            route = "/v1/operator/phase10/customer-lifecycle"
            self.assertEqual(http.get(route).status_code, 401)
            answer = http.get(route, headers={"Cf-Access-Jwt-Assertion": "controlled-test-token"})
            self.assertEqual(answer.status_code, 200)
            self.assertIn("Customer lifecycle", answer.text)
            self.assertEqual(answer.headers["cache-control"], "private, no-store, max-age=0")

    def test_protected_record_dry_run_denied_before_transport(self):
        baseline = {"schema": 1, "modules": {m: {"status": "complete", "ids": ["999"]}
                   for m in ("Leads", "Accounts", "Contacts", "Deals", "Tasks", "Events", "Calls", "Notes")}}
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            b, r = Path(tmp) / "baseline.json", Path(tmp) / "registry.json"
            b.write_text(json.dumps(baseline))
            r.write_text(json.dumps({"schema": 1, "baseline_sha256": hashlib.sha256(b.read_bytes()).hexdigest(),
                                     "records": {"Accounts": ["101"]}}))
            env = {"OPTIBRAIN_PHASE8_TEST_LAB": "phase8-protected-test-lab-v1"}
            with patch("workflow.automation.test_lab_boundary.BASELINE", b), patch(
                    "workflow.automation.test_lab_boundary.REGISTRY", r), patch(
                    "workflow.automation.test_lab_boundary.os.geteuid", return_value=0), patch.dict(
                    "os.environ", env):
                body = {"data": [{"id": "999", "OptiBrain_Test": True}], "trigger": []}
                with self.assertRaisesRegex(ValueError, "protected"):
                    validate_lab_request("PUT", "/crm/v8/Accounts/999", body,
                                         {"If-Unmodified-Since": "2026-10-01T12:00:00+00:00"})
                allowed = {"data": [{"id": "101", "OptiBrain_Test": True}], "trigger": []}
                self.assertEqual(validate_lab_request("PUT", "/crm/v8/Accounts/101", allowed,
                                                       {"If-Unmodified-Since": "2026-10-01T12:00:00+00:00"}),
                                 ("Accounts", "101"))


if __name__ == "__main__":
    unittest.main()
