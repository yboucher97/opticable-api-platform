"""Focused Phase 11 operational chain, read boundary, and provider mutation firewall."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.operations import (build_operations, classify_document, event_id,
                                           local_time, render_operations, stable_id)
from workflow.automation import test_lab_boundary as boundary
from workflow.operator_phase7_api import install_phase7_canary_routes

MARK = "OPTIBRAIN TEST — PHASE 11"
NOW = datetime.fromisoformat("2026-10-01T13:00:00+00:00")


def fixture():
    ids = {"Accounts": "101", "Contacts": "201", "Service_Locations": "301",
           "Deals": "401", "Services": "501", "Installations": "601", "Cases": "701", "Tasks": "801"}
    records = {
        "Accounts": {"id": "101", "Account_Name": MARK + " Customer", "Description": MARK,
                     "OptiBrain_Test": True},
        "Contacts": {"id": "201", "Full_Name": "Test Contact", "Description": MARK,
                     "Account_Name": {"id": "101"}, "OptiBrain_Test": True},
        "Service_Locations": {"id": "301", "Name": MARK + " Site", "Linked_Account": {"id": "101"},
                              "Primary_Contact": {"id": "201"}, "OptiBrain_Test": True},
        "Deals": {"id": "401", "Deal_Name": MARK + " Project", "Description": MARK,
                  "Account_Name": {"id": "101"}, "Contact_Name": {"id": "201"},
                  "OptiBrain_Test": True, "First_Source": "AI website"},
        "Services": {"id": "501", "Name": MARK + " Cameras", "OptiBrain_Test": True,
                     "Linked_Service_Location": {"id": "301"}, "Linked_Deal": {"id": "401"},
                     "Service_Stage": "Active", "OptiBrain_Installed_On": "2026-10-01"},
        "Installations": {"id": "601", "Name": MARK + " Repair", "Linked_Service": {"id": "501"},
                          "Installation_Status": "Requested", "Scheduled_Date": None},
        "Cases": {"id": "701", "Subject": MARK + " Camera offline", "Description": MARK,
                  "Account_Name": {"id": "101"}, "Related_To": {"id": "201"},
                  "Deal_Name": {"id": "401"}, "Status": "New"},
        "Tasks": {"id": "801", "Subject": MARK + " Archive photos", "Description": MARK,
                  "What_Id": {"id": "401"}, "$se_module": "Deals", "Status": "Completed",
                  "Due_Date": "2026-10-02"},
    }
    project_id = stable_id("Deals", "401")
    projection = {"schema": 1, "crosswalk": {stable_id(module, identity): {
        "internal_id": stable_id(module, identity), "module": module,
        "provider_id": identity, "test_only": True,
        "created_at_utc": "2026-10-01T12:00:00+00:00"} for module, identity in ids.items()},
        "projects": {project_id: {"id": project_id,
        "status": "COMPLETED", "provider": {k: ids[k] for k in
            ("Accounts", "Contacts", "Service_Locations", "Deals")},
        "services": ["501"], "work_orders": ["601"], "tickets": ["701"],
        "ticket_work_orders": {"701": ["601"]}, "tasks": ["801"],
        "task_categories": {"801": "DOCUMENT"}, "documents": [], "events": [],
        "folder": {"path": "/test"}, "scheduled": None}}}
    lab = {"records": {module: [identity] for module, identity in ids.items()}}
    return records, projection, lab


class FakeCRM:
    def __init__(self, records): self.records = records
    def request(self, service, method, path):
        assert (service, method) == ("zohoapis", "GET")
        _, _, module, identity = path.strip("/").split("/")
        row = self.records[module]
        if row["id"] != identity: raise AssertionError("Unexpected provider identity")
        return {"ok": True, "data": {"data": [row]}}


class OperationalTests(unittest.TestCase):
    def view(self, records, projection, lab):
        with tempfile.TemporaryDirectory() as root:
            p, l = Path(root) / "project.json", Path(root) / "lab.json"
            p.write_text(json.dumps(projection)); l.write_text(json.dumps(lab))
            return build_operations(FakeCRM(records), scope="lab", projection_path=p,
                                    lab_path=l, now=NOW)

    def test_owned_ticket_and_work_drive_one_action(self):
        records, project, lab = fixture()
        view = self.view(records, project, lab)
        row = view["projects"][0]
        self.assertEqual((row["action"], view["summary"]["open_tickets"]), ("Schedule work", 1))
        self.assertEqual(row["tickets"][0]["action"], "Schedule work")
        records["Installations"]["Installation_Status"] = "Completed"
        self.assertEqual(self.view(records, project, lab)["projects"][0]["action"], "Resolve ticket")
        records["Cases"]["Status"] = "Closed"
        self.assertEqual(self.view(records, project, lab)["projects"][0]["action"], "No action")

    def test_relationship_change_fails_closed_and_live_excludes_lab(self):
        records, project, lab = fixture()
        records["Cases"]["Account_Name"] = {"id": "999"}
        with self.assertRaisesRegex(ValueError, "Ticket relationship"):
            self.view(records, project, lab)
        self.assertEqual(build_operations(FakeCRM(records), scope="live", now=NOW)["projects"], [])
        lab["records"]["Services"] = []
        with self.assertRaisesRegex(ValueError, "Installed Service"):
            self.view(records, project, lab)

    def test_crosswalk_keeps_internal_id_if_owned_provider_record_is_replaced(self):
        records, project, lab = fixture()
        old_internal = stable_id("Services", "501")
        project["crosswalk"][old_internal]["provider_id"] = "502"
        p = next(iter(project["projects"].values()))
        p["services"] = ["502"]
        records["Services"]["id"] = "502"
        records["Installations"]["Linked_Service"] = {"id": "502"}
        lab["records"]["Services"] = ["502"]
        row = self.view(records, project, lab)["projects"][0]
        self.assertEqual(row["services"][0]["id"], old_internal)
        self.assertEqual(row["work_orders"][0]["service_id"], old_internal)

    def test_ids_events_files_and_montreal_dst(self):
        self.assertEqual(stable_id("Deals", "401"), stable_id("Deals", "401"))
        self.assertNotEqual(stable_id("Deals", "401"), stable_id("Deals", "402"))
        self.assertNotEqual(stable_id("Deals", "401"), stable_id("Accounts", "401"))
        self.assertEqual(event_id("WORK_ORDER_COMPLETED", "OB-WO-X", "v1"),
                         event_id("WORK_ORDER_COMPLETED", "OB-WO-X", "v1"))
        self.assertNotEqual(event_id("WORK_ORDER_COMPLETED", "OB-WO-X", "v1"),
                            event_id("WORK_ORDER_COMPLETED", "OB-WO-X", "v2"))
        self.assertEqual(classify_document("2026-10-01_OB-J-ABC_SitePlan.pdf"), "PLAN")
        self.assertEqual(classify_document("camera-after.jpg"), "PHOTO")
        self.assertIn("EDT", local_time("2026-11-01T05:30:00+00:00"))
        self.assertIn("EST", local_time("2026-11-01T06:30:00+00:00"))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            local_time("2026-11-01T01:30:00")

    def test_terminal_event_replay_ignores_unrelated_provider_version(self):
        module = runpy.run_path(str(Path(__file__).resolve().parents[3] /
                                    "ops/phase11/test_lab_operations.py"))
        state = {}; project = {"events": []}
        with patch.dict(module["event"].__globals__, {"save": lambda value: None}):
            self.assertTrue(module["event"](state, project, "WORK_ORDER_COMPLETED", "OB-WO-X", "v1"))
            self.assertFalse(module["event"](state, project, "WORK_ORDER_COMPLETED", "OB-WO-X", "v2"))
        self.assertEqual(len(project["events"]), 1)

    def test_folder_and_document_replay_are_content_addressed(self):
        module = runpy.run_path(str(Path(__file__).resolve().parents[3] /
                                    "ops/phase11/test_lab_operations.py"))
        project = {"id": stable_id("Deals", "401"),
                   "provider": {"Accounts": "101", "Service_Locations": "301"},
                   "documents": [], "events": []}
        state = {}
        with tempfile.TemporaryDirectory() as root, patch.dict(module["folders"].__globals__,
                {"ROOT": Path(root), "save": lambda value: None}):
            first = module["folders"](state, project)
            second = module["folders"](state, project)
            self.assertEqual(first, second)
            name = "2026-10-01_" + project["id"] + "_SitePlan.txt"
            with patch.dict(module["document"].__globals__, {"ROOT": Path(root),
                             "save": lambda value: None}):
                module["document"](state, project, name, b"OPTIBRAIN TEST")
                module["document"](state, project, name, b"OPTIBRAIN TEST")
                self.assertEqual(len(project["documents"]), 1)
                with self.assertRaisesRegex(ValueError, "collision"):
                    module["document"](state, project, name, b"different bytes")

    def test_render_escapes_and_routes_require_identity(self):
        records, project, lab = fixture()
        records["Accounts"]["Account_Name"] = "<script>"
        view = self.view(records, project, lab)
        self.assertIn("&lt;script&gt;", render_operations(view))
        self.assertNotIn("<script>", render_operations(view))
        class Verifier:
            def verify(self, token):
                if token != "test-operator": raise ValueError("missing")
                return SimpleNamespace(subject="operator")
        app = FastAPI()
        with tempfile.TemporaryDirectory() as root:
            install_phase7_canary_routes(app, verifier=Verifier(), client=FakeCRM(records),
                store=SimpleNamespace(db_path=Path(root) / "automation.db"), account_id="1",
                from_address="operator@example.invalid", allowed_origin="https://example.invalid")
            http = TestClient(app)
            with patch("workflow.operator_phase7_api.build_operations", return_value=view):
                for path in ("/v1/operator/phase11/operations",
                             "/v1/operator/phase11/project/" + view["projects"][0]["id"]):
                    self.assertEqual(http.get(path).status_code, 401)
                    answer = http.get(path, headers={"Cf-Access-Jwt-Assertion": "test-operator"})
                    self.assertEqual(answer.status_code, 200)
                    self.assertEqual(answer.headers["cache-control"], "private, no-store, max-age=0")

    def test_protected_cases_and_installation_relations_blocked_before_transport(self):
        protected = {m: {"status": "complete", "ids": ["999"]} for m in
                     ("Leads", "Contacts", "Accounts", "Deals", "Tasks", "Events", "Calls", "Notes")}
        with tempfile.TemporaryDirectory() as root:
            b, s, c, r = (Path(root) / name for name in
                          ("baseline.json", "services.json", "cases.json", "registry.json"))
            b.write_text(json.dumps({"schema": 1, "modules": protected}))
            s.write_text(json.dumps({"schema": 1, "modules": {
                "Services": ["888"], "Service_Locations": ["777"], "Installations": ["666"]}}))
            c.write_text(json.dumps({"schema": 1, "ids": ["555"]}))
            r.write_text(json.dumps({"schema": 1,
                "baseline_sha256": hashlib.sha256(b.read_bytes()).hexdigest(),
                "service_baseline_sha256": hashlib.sha256(s.read_bytes()).hexdigest(),
                "case_baseline_sha256": hashlib.sha256(c.read_bytes()).hexdigest(),
                "records": {"Accounts": ["101"], "Contacts": ["201"], "Deals": ["401"],
                            "Services": ["501"], "Installations": ["601"], "Cases": ["701"]}}))
            env = {"OPTIBRAIN_PHASE8_TEST_LAB": boundary.POLICY}
            header = {"If-Unmodified-Since": "2026-10-01T12:00:00+00:00"}
            with patch.object(boundary, "BASELINE", b), patch.object(boundary, "SERVICE_BASELINE", s), \
                 patch.object(boundary, "CASE_BASELINE", c), patch.object(boundary, "REGISTRY", r), \
                 patch.object(boundary.os, "geteuid", return_value=0), patch.dict("os.environ", env):
                case = {"data": [{"id": "555", "Status": "Closed"}], "trigger": []}
                with self.assertRaisesRegex(ValueError, "protected"):
                    boundary.validate_lab_request("PUT", "/crm/v8/Cases/555", case, header)
                case["data"][0]["id"] = "701"
                self.assertEqual(boundary.validate_lab_request("PUT", "/crm/v8/Cases/701", case, header),
                                 ("Cases", "701"))
                install = {"data": [{"Name": MARK + " install",
                            "Linked_Service": {"id": "501"}}], "trigger": []}
                self.assertEqual(boundary.validate_lab_request("POST", "/crm/v8/Installations", install, None),
                                 ("Installations", None))
                install["data"][0]["Linked_Service"] = {"id": "888"}
                with self.assertRaisesRegex(ValueError, "outside Test Lab"):
                    boundary.validate_lab_request("POST", "/crm/v8/Installations", install, None)


if __name__ == "__main__": unittest.main()
