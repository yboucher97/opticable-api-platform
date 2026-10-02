from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import yaml

from workflow.automation.crm_delta import CrmLeadDeltaAdapter
from workflow.automation.delta_sync import DeltaSync, SyncFailure
from workflow.automation.engine import AutomationEngine
from workflow.automation.events import EventLedger
from workflow.automation.event_schema import digest
from workflow.automation.models import AutomationEvent, WorkflowDefinition, WorkflowStep
from workflow.automation.providers.crm_leads import lead_plan, register_crm_lead_actions
from workflow.automation.store import AutomationStore
from workflow.automation.webhooks import WebhookEndpoint, accept_delivery


class LeadFake:
    def __init__(self):
        self.lead = {"id": "123", "Email": " SALES@EXAMPLE.TEST ", "Phone": "+1 (514) 555-0123",
                     "Normalized_Email": None, "Normalized_Phone": None, "Lead_Status": "Not Contacted",
                     "Modified_Time": "2026-09-28T13:00:00Z", "Created_Time": "2026-09-26T13:00:00Z",
                     "Converted__s": False, "First_Source": "preserved-first", "Last_Source": "preserved-last",
                     "Service_Types": "Wifi Installation", "City": "Montreal", "Email_Opt_Out": True}
        self.tasks, self.calls = [], []
        self.accept_then_lose = False
        self.lost_task = False
        self.error = None

    def request(self, service, method, path, **kwargs):
        self.calls.append((method, path, copy.deepcopy(kwargs)))
        if self.error:
            raise self.error
        if method == "GET":
            if path == "/crm/v8/Leads/123": rows = [self.lead]
            elif path == "/crm/v8/Tasks/search": rows = self.tasks
            elif path.startswith("/crm/v8/Tasks/"): rows = self.tasks
            elif path == "/crm/v8/Leads": rows = [{"id": "123", "Modified_Time": self.lead["Modified_Time"]}]
            else: raise AssertionError("unexpected provider read")
            return {"ok": True, "status": 200 if rows else 204, "data": {"data": copy.deepcopy(rows), "info": {"more_records": False}}}
        if method == "PUT":
            self.lead.update(kwargs["body"]["data"][0])
            if self.accept_then_lose: raise httpx.ReadTimeout("accepted but response lost")
            identity = "123"
        elif method == "POST" and path == "/crm/v8/Tasks":
            task = {"id": "789", **kwargs["body"]["data"][0]}
            task["Who_Id"] = {"id": task["Who_Id"]}
            self.tasks.append(task); identity = "789"
            if self.lost_task: raise httpx.ReadTimeout("task accepted response lost")
        else: raise AssertionError("unexpected provider write")
        return {"ok": True, "status": 200, "request_id": "evidence-only", "data": {"data": [{"status": "success", "details": {"id": identity}}]}}

    @property
    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


class LeadEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.fake = LeadFake()
        self.definitions = Path(__file__).resolve().parents[1] / "config/automation/workflows"
        self.engine = AutomationEngine(self.store, self.definitions)
        register_crm_lead_actions(self.engine, self.fake, self.store)
        for name in ("opticable-crm-lead-observe.yaml", "opticable-crm-lead-reconcile.yaml"):
            self.store.upsert_workflow(WorkflowDefinition.model_validate(yaml.safe_load((self.definitions / name).read_text())))
        self.ledger = EventLedger(self.store)
        self.env = patch.dict(os.environ, {"OPTIBRAIN_CRM_LEAD_WRITES": ""}); self.env.start(); self.addCleanup(self.env.stop)

    def hint(self, native="one"):
        return AutomationEvent(event_type="zoho.crm.Leads.insert", source="zoho_crm", source_account="org-fixture",
                               provider_event_id=native, payload={"ids": ["123"]})

    def drain(self):
        for _ in range(3): self.engine.recover_pending(limit=10)

    def observe(self, hint):
        return self.engine._actions["crm.lead.observe"]({"event": hint.model_dump(mode="json")}, None)

    def test_same_version_at_different_observation_times_reuses_immutable_review(self):
        hint = self.hint()
        hint.occurred_at = "2026-09-28T14:00:00Z"
        first = self.observe(hint)["review_event_ids"][0]
        original = self.ledger.inspect(first)["envelope"]
        later = self.hint("later")
        later.occurred_at = "2026-10-02T14:00:00Z"
        self.assertEqual(self.observe(later)["review_event_ids"], [first])
        self.assertEqual(self.ledger.inspect(first)["envelope"], original)
        self.assertEqual(len(self.ledger.list_events(limit=20)), 1)
        self.assertEqual(len([a for a in self.store.recent_audit() if a["category"] == "crm_lead_review"]), 1)
        self.assertFalse(self.fake.writes)

    def test_legacy_review_is_reused_without_payload_upgrade(self):
        version = lead_plan(self.fake.lead)["version"]
        legacy = AutomationEvent(event_type="opticable.crm.lead.reviewed", source="crm-lead-observer",
            source_account="org-fixture", provider_event_id=digest(["123", version]),
            subject_type="Leads", subject_id="123",
            payload={"lead_id": "123", "version": version})
        accepted, identity, _ = self.ledger.capture(legacy)
        self.assertTrue(accepted)
        before = self.ledger.inspect(identity)["envelope"]
        self.assertEqual(self.observe(self.hint())["review_event_ids"], [identity])
        self.assertEqual(self.ledger.inspect(identity)["envelope"], before)
        self.assertNotIn("sales_decision", before["payload"])
        self.assertFalse(self.fake.writes)

    def test_same_version_changed_fields_fail_closed_and_new_version_is_discovered(self):
        original = self.observe(self.hint())["review_event_ids"][0]
        self.fake.lead["City"] = "Ottawa"
        with self.assertRaisesRegex(ValueError, "without a new provider version"):
            self.observe(self.hint("changed"))
        self.assertEqual(len(self.ledger.list_events(limit=20)), 1)
        self.fake.lead["Modified_Time"] = "2026-10-02T14:00:00Z"
        new = self.observe(self.hint("new-version"))["review_event_ids"][0]
        self.assertNotEqual(new, original)
        self.assertEqual(len(self.ledger.list_events(limit=20)), 2)
        self.assertFalse(self.fake.writes)

    def test_normalization_preserves_attribution_and_relationships(self):
        plan = lead_plan(self.fake.lead, now=datetime(2026, 9, 28, tzinfo=timezone.utc))
        self.assertEqual(plan["patch"], {"Normalized_Email": "sales@example.test", "Normalized_Phone": "+15145550123"})
        self.assertTrue(plan["stale"])
        self.assertNotIn("First_Source", plan["patch"]); self.assertNotIn("Last_Source", plan["patch"])
        self.assertEqual(plan["routing"]["City"], "Montreal")

    def test_default_observe_emits_internal_alert_without_writes(self):
        first = self.engine.ingest(self.hint())
        self.drain()
        self.assertTrue(first.accepted); self.assertFalse(self.fake.writes)
        alerts = [a for a in self.store.recent_audit() if a["category"] == "crm_lead_review"]
        self.assertEqual(len(alerts), 1); self.assertEqual(alerts[0]["action"], "human_followup")
        self.assertTrue(alerts[0]["metadata"]["stale"])

    def test_duplicate_notifications_and_distinct_hints_same_version_collapse(self):
        self.engine.ingest(self.hint()); duplicate = self.engine.ingest(self.hint())
        self.assertTrue(duplicate.duplicate)
        self.engine.ingest(self.hint("two")); self.drain()
        reviewed = [e for e in self.ledger.list_events(limit=20) if self.ledger.inspect(e["event_id"])["envelope"]["event_type"] == "opticable.crm.lead.reviewed"]
        self.assertEqual(len(reviewed), 1)
        self.assertFalse(self.fake.writes)

    def test_restart_after_capture_before_routing(self):
        accepted, identity, _ = self.ledger.capture(self.hint())
        self.assertTrue(accepted)
        restarted = AutomationEngine(AutomationStore(self.store.db_path), self.definitions)
        register_crm_lead_actions(restarted, self.fake, restarted.store)
        for _ in range(3): restarted.recover_pending(limit=10)
        self.assertEqual(self.ledger.inspect(identity)["status"], "routed")
        self.assertFalse(self.fake.writes)

    def test_authenticated_native_notification_ledger_and_review(self):
        endpoint = WebhookEndpoint(provider="zoho_crm", source_account="org-fixture", secret_env="TEST_CRM_TOKEN",
            channel_id="456", allowed_event_types=["zoho.crm.Leads.insert"], enabled=True)
        token = "fixture-notification-token-32bytes"
        raw = json.dumps({"token": token, "channel_id": "456", "server_time": int(datetime.now(timezone.utc).timestamp() * 1000),
                          "module": "Leads", "operation": "insert", "ids": ["123"]}).encode()
        with patch.dict(os.environ, {"TEST_CRM_TOKEN": token}):
            one = accept_delivery(self.ledger, endpoint, {"content-type": "application/json"}, raw)
            two = accept_delivery(self.ledger, endpoint, {"content-type": "application/json"}, raw)
        self.drain()
        self.assertTrue(one["accepted"]); self.assertTrue(two["duplicate"])
        evidence = self.ledger.inspect(one["event_id"])
        self.assertNotIn(token, json.dumps(evidence))
        self.assertEqual(evidence["status"], "routed")
        self.assertEqual(len(evidence["routes"]), 1)
        self.assertEqual(self.store.get_run(evidence["routes"][0]["run_id"])["status"], "completed")
        self.assertEqual(len([a for a in self.store.recent_audit() if a["category"] == "crm_lead_review"]), 1)

    def test_bounded_normalization_and_one_internal_task_across_versions_restart(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"
        self.engine.ingest(self.hint()); self.drain()
        self.assertEqual([c[0] for c in self.fake.writes], ["PUT", "POST"])
        self.assertEqual(self.fake.lead["First_Source"], "preserved-first")
        self.assertEqual(self.fake.lead["Last_Source"], "preserved-last")
        self.assertEqual(len(self.fake.tasks), 1)
        self.fake.lead["Modified_Time"] = "2026-09-28T13:01:00Z"
        restarted = AutomationEngine(AutomationStore(self.store.db_path), self.definitions)
        register_crm_lead_actions(restarted, self.fake, restarted.store)
        restarted.ingest(self.hint("next-version"))
        for _ in range(3): restarted.recover_pending(limit=10)
        self.assertEqual(len(self.fake.writes), 2)
        for _, path, kwargs in self.fake.writes:
            self.assertNotIn("books", path.casefold()); self.assertEqual(kwargs["body"]["trigger"], [])
        self.assertEqual(self.fake.writes[0][2]["headers"], {"If-Unmodified-Since": "2026-09-28T13:00:00Z"})
        self.assertEqual(self.fake.writes[0][2]["body"]["skip_feature_execution"], [{"name": "cadences"}])

    def test_alert_commit_failure_rolls_back_child_capture_and_restart_can_recover(self):
        event = self.hint()
        self.ledger.capture(event)
        with self.store._connect() as conn:
            conn.execute("CREATE TRIGGER fixture_alert_failure BEFORE INSERT ON automation_audit WHEN NEW.category='crm_lead_review' BEGIN SELECT RAISE(ABORT,'fixture_crash_window'); END")
        context = {"event": event.model_dump()}
        action = self.engine._actions["crm.lead.observe"]
        with self.assertRaises(sqlite3.IntegrityError): action(context, None)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_events WHERE source='crm-lead-observer'").fetchone()[0], 0)
            conn.execute("DROP TRIGGER fixture_alert_failure")
        restarted = AutomationEngine(AutomationStore(self.store.db_path), self.definitions)
        register_crm_lead_actions(restarted, self.fake, restarted.store)
        result = restarted._actions["crm.lead.observe"](context, None)
        child = self.ledger.inspect(result["review_event_ids"][0])
        self.assertEqual(child["envelope"]["depth"], event.depth + 1)
        self.assertEqual(len([a for a in self.store.recent_audit() if a["category"] == "crm_lead_review"]), 1)
        self.assertFalse(self.fake.writes)

    def test_unknown_conversion_state_does_not_authorize_record_writes(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"
        self.fake.lead.pop("Converted__s")
        self.engine.ingest(self.hint()); self.drain()
        self.assertFalse(self.fake.writes)

    def test_lost_normalization_response_enters_phase3_human_state_no_retry(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"
        self.fake.accept_then_lose = True
        self.engine.ingest(self.hint()); self.drain()
        self.assertEqual(len(self.fake.writes), 1)
        with self.store._connect() as conn:
            statuses = {r[0] for r in conn.execute("SELECT status FROM automation_runs")}
        self.assertIn("human_action_required", statuses)
        self.fake.accept_then_lose = False; self.fake.lead["Email"] = "new@example.test"
        self.fake.lead["Modified_Time"] = "2026-09-28T13:02:00Z"
        self.engine.ingest(self.hint("changed")); self.drain()
        self.assertEqual(len(self.fake.writes), 1)

    def test_task_response_lost_is_never_recreated_on_new_event(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"; self.fake.lost_task = True
        self.engine.ingest(self.hint()); self.drain()
        self.assertEqual(len(self.fake.tasks), 1)
        self.fake.lost_task = False; self.fake.lead["Modified_Time"] = "2026-09-28T13:03:00Z"
        self.engine.ingest(self.hint("later")); self.drain()
        self.assertEqual(len(self.fake.tasks), 1)

    def test_superseded_review_does_not_write(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"
        event = AutomationEvent(event_type="opticable.crm.lead.reviewed", source="crm-lead-observer",
            payload={"lead_id": "123", "version": "2026-09-28T12:00:00Z"})
        self.engine.ingest(event); self.assertFalse(self.fake.writes)

    def test_converted_lead_not_normalized_or_given_task(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"; self.fake.lead["Converted__s"] = True
        self.engine.ingest(self.hint()); self.drain(); self.assertFalse(self.fake.writes)

    def test_replay_preserves_routes_and_no_duplicate_tasks(self):
        os.environ["OPTIBRAIN_CRM_LEAD_WRITES"] = "phase5-lead-v1"
        first = self.engine.ingest(self.hint()); self.drain()
        replay = self.ledger.replay(first.event_id, request_key="fixture-replay", actor="fixture", reason="Reviewed repeat intake")
        self.drain()
        self.assertEqual(len(self.fake.writes), 2); self.assertEqual(len(self.fake.tasks), 1)

    def test_delta_page_commits_with_existing_phase4_checkpoint(self):
        sync = DeltaSync(self.store)
        sync.initialize("zoho_crm", "org-fixture", "Leads", cursor="2026-09-28T12:59:00Z")
        result = sync.cycle("zoho_crm", "org-fixture", "Leads", CrmLeadDeltaAdapter(self.fake, "org-fixture"), page_limit=10)
        self.assertEqual(result["accepted"], 1)
        self.drain(); self.assertFalse(self.fake.writes)
        self.assertEqual(sync.snapshot("zoho_crm", "org-fixture", "Leads")["status"], "idle")

    def test_delta_overflow_never_advances_cursor(self):
        adapter = CrmLeadDeltaAdapter(self.fake, "org-fixture")
        with patch.object(self.fake, "request", return_value={"ok": True, "status": 200, "data": {"data": [], "info": {"more_records": True}}}):
            with self.assertRaisesRegex(SyncFailure, "cursor_expired"):
                adapter.fetch("2026-09-28T12:59:00Z", None, mode="incremental", limit=10)

    def test_delta_401_429_503_timeout_categories(self):
        for status, category in ((401, "authentication_failed"), (429, "rate_limited"), (503, "provider_unavailable")):
            with self.subTest(status=status):
                from workflow.zoho_gateway import ZohoGatewayError
                self.fake.error = ZohoGatewayError("safe fixture", response=httpx.Response(status, headers={"Retry-After": "30"}))
                with self.assertRaisesRegex(SyncFailure, category):
                    CrmLeadDeltaAdapter(self.fake, "org-fixture").fetch("2026-09-28T12:59:00Z", None, mode="incremental", limit=10)


if __name__ == "__main__": unittest.main()
