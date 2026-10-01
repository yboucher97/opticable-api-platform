"""Focused guards for the one-shot accepted Deal onboarding path."""
import sys
from pathlib import Path
from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ops/phase11"))
import onboard_test_deal as flow


class OnboardingTests(TestCase):
    def setUp(self):
        self.deal = {"id": "401", "Deal_Name": flow.MARKER + " Deal",
                     "Stage": "Contracts Signed", "Service_Types": "Cameras; Cabling",
                     "Description": flow.MARKER, "OptiBrain_Test": True,
                     "Created_Time": "2026-10-01T10:00:00-04:00",
                     "Account_Name": {"id": "101"}, "Contact_Name": {"id": "201"}}
        self.records = {"Deals": {"401": self.deal},
            "Accounts": {"101": {"id": "101", "OptiBrain_Test": True}},
            "Contacts": {"201": {"id": "201", "Account_Name": {"id": "101"}, "OptiBrain_Test": True}},
            "Service_Locations": {"301": {"id": "301", "Linked_Account": {"id": "101"},
                                          "Primary_Contact": {"id": "201"}, "OptiBrain_Test": True}},
            "Services": {}, "Installations": {}}
        self.lab = {"records": {m: list(rows) for m, rows in self.records.items()}}
        self.state = {"projects": {}, "crosswalk": {}, "operations": {}}

    def read(self, client, module, identity):
        return self.records[module][identity]

    def owned(self, lab, module, row):
        if row["id"] not in lab["records"][module]:
            raise ValueError("outside Test Lab")
        return row

    def test_accepted_deal_requires_unique_owned_site_and_scope(self):
        with patch.object(flow, "read", self.read), patch.object(flow, "owned", self.owned), \
             patch.object(flow, "listing", lambda *_: list(self.records["Service_Locations"].values())):
            self.assertEqual(flow.resolve_deal(None, self.lab, "401", new=True)[1:],
                             ("101", "201", "301"))
            self.deal["Stage"] = "Qualification"
            with self.assertRaisesRegex(ValueError, "accepted"):
                flow.resolve_deal(None, self.lab, "401", new=True)
            self.deal["Stage"] = "Contracts Signed"; self.deal["Service_Types"] = ""
            with self.assertRaisesRegex(ValueError, "service scope"):
                flow.resolve_deal(None, self.lab, "401", new=True)
            self.deal["Service_Types"] = "Cameras"
            self.records["Service_Locations"]["302"] = dict(self.records["Service_Locations"]["301"], id="302")
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                flow.resolve_deal(None, self.lab, "401", new=True)

    def test_onboarding_replay_creates_one_service_and_work_order(self):
        creates = []
        def write(client, state, lab, key, module, row, *, identity=None):
            self.assertIsNone(identity)
            new_id = {"Services": "501", "Installations": "601"}[module]
            result = {**row, "id": new_id, "Created_Time": "2026-10-01T10:01:00-04:00"}
            self.records[module][new_id] = result; lab["records"][module].append(new_id)
            creates.append((module, key))
            return result
        def document(state, project, name, content):
            if not project["documents"]: project["documents"].append({"name": name})
        def event(state, project, kind, obj, version):
            if kind not in [x["kind"] for x in project["events"]]:
                project["events"].append({"kind": kind})
        with patch.object(flow, "read", self.read), patch.object(flow, "owned", self.owned), \
             patch.object(flow, "listing", lambda *_: list(self.records["Service_Locations"].values())), \
             patch.object(flow, "write", write), patch.object(flow, "save", lambda *_: None), \
             patch.object(flow, "folders", lambda *_: None), patch.object(flow, "document", document), \
             patch.object(flow, "event", event), patch.object(flow, "link", lambda s, m, i, **kw: flow.stable_id(m, i)):
            first = flow.onboard(None, self.state, self.lab, "401")
            # A later second site must not change the already registered project.
            self.records["Service_Locations"]["302"] = dict(self.records["Service_Locations"]["301"], id="302")
            second = flow.onboard(None, self.state, self.lab, "401")
        self.assertIs(first, second)
        self.assertEqual([m for m, _ in creates], ["Services", "Installations"])
        self.assertEqual((len(first["work_orders"]), len(first["services"]), len(first["documents"])), (1, 1, 1))

    def test_schedule_rejects_dst_offset_and_conflicting_assignment(self):
        with self.assertRaisesRegex(ValueError, "offset"):
            flow.aware("2026-12-01T10:00:00-04:00")
        self.assertEqual(flow.aware("2026-11-01T01:30:00-04:00").astimezone(flow.TORONTO).tzname(), "EDT")
        self.assertEqual(flow.aware("2026-11-01T01:30:00-05:00").astimezone(flow.TORONTO).tzname(), "EST")
        self.assertFalse(flow.overlaps(flow.aware("2026-10-01T10:00:00-04:00"), 60,
                                       flow.aware("2026-10-01T11:00:00-04:00"), 60))
        self.assertTrue(flow.overlaps(flow.aware("2026-10-01T10:00:00-04:00"), 60,
                                      flow.aware("2026-10-01T10:59:00-04:00"), 60))
        self.records["Installations"]["601"] = {"id": "601", "Installation_Status": "Requested"}
        self.records["Installations"]["602"] = {"id": "602", "Installation_Status": "Scheduled",
            "Scheduled_Date": "2026-10-01T10:30:00-04:00", "Assigned_To": "OPTIBRAIN TEST — Crew"}
        self.lab["records"]["Installations"] = ["601", "602"]
        project = {"id": "OB-J-A", "provider": {"Deals": "401"}, "work_orders": ["601"]}
        self.state["projects"] = {"OB-J-A": project, "OB-J-B": {"work_orders": ["602"]}}
        with patch.object(flow, "read", self.read), patch.object(flow, "owned", self.owned), \
             patch.object(flow, "write", side_effect=AssertionError("write reached")):
            with self.assertRaisesRegex(ValueError, "conflicts"):
                flow.schedule(None, self.state, self.lab, project,
                              "2026-10-01T10:00:00-04:00", "OPTIBRAIN TEST — Crew", 120,
                              now=datetime.fromisoformat("2026-10-01T09:00:00-04:00"))

    def test_external_assignment_change_observed_once(self):
        self.records["Services"]["501"] = {"id": "501", "Linked_Deal": {"id": "401"},
            "Linked_Service_Location": {"id": "301"}, "Service_Stage": "Ready for Scheduling"}
        self.records["Installations"]["601"] = {"id": "601", "Linked_Service": {"id": "501"},
            "Installation_Status": "Scheduled", "Scheduled_Date": "2026-10-01T10:00:00-04:00",
            "Assigned_To": "OPTIBRAIN TEST — Crew A"}
        self.lab["records"]["Services"] = ["501"]
        self.lab["records"]["Installations"] = ["601"]
        project = {"id": "OB-J-A", "provider": {"Deals": "401", "Service_Locations": "301"},
                   "services": ["501"], "work_orders": ["601"], "events": [], "status": "SCHEDULED"}
        def event(state, project, kind, obj, version):
            identity = (kind, obj, version)
            if identity not in project["events"]: project["events"].append(identity)
        with patch.object(flow, "read", self.read), patch.object(flow, "owned", self.owned), \
             patch.object(flow, "event", event), patch.object(flow, "save", lambda *_: None):
            self.assertEqual(flow.reconcile(None, self.state, self.lab, project), 1)
            self.records["Installations"]["601"]["Assigned_To"] = "OPTIBRAIN TEST — Crew B"
            self.assertEqual(flow.reconcile(None, self.state, self.lab, project), 1)
            self.assertEqual(flow.reconcile(None, self.state, self.lab, project), 0)
        self.assertEqual([x[0] for x in project["events"]],
                         ["WORK_ORDER_SCHEDULED", "WORK_ORDER_ASSIGNMENT_CHANGED"])
