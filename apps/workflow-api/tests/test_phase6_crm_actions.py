from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import yaml

from workflow.automation.desired_journal import DesiredJournal
from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.providers.crm_leads import (
    PHASE6_POLICY,
    register_crm_lead_actions,
)
from workflow.automation.sales_decision import build_sales_decision
from workflow.automation.store import AutomationStore


class Phase6LeadFake:
    def __init__(self):
        self.lead = {
            "id": "123",
            "Email": " SALES@EXAMPLE.TEST ",
            "Phone": "+1 (514) 555-0123",
            "Mobile": None,
            "Normalized_Email": None,
            "Normalized_Phone": None,
            "Lead_Status": "Not Contacted",
            "Modified_Time": "2026-09-28T13:00:00Z",
            "Created_Time": "2026-09-26T13:00:00Z",
            "Converted__s": False,
            "Service_Types": "Structured Cabling",
            "City": "Montreal",
            "State": "Quebec",
            "Ingestion_Source": "fixture",
            "Next_Followup_At": None,
            "Email_Opt_Out": False,
        }
        self.tasks = []
        self.calls = []
        self.accept_then_lose = False
        self.lost_task = False

    def request(self, service, method, path, **kwargs):
        self.calls.append((method, path, copy.deepcopy(kwargs)))
        if service != "zohoapis":
            raise AssertionError("unexpected provider")

        if method == "GET":
            if path == "/crm/v8/Leads/123":
                rows = [self.lead]
            elif path == "/crm/v8/Tasks/search":
                rows = self.tasks
            elif path.startswith("/crm/v8/Tasks/"):
                identity = path.rsplit("/", 1)[-1]
                rows = [task for task in self.tasks if str(task.get("id")) == identity]
            else:
                raise AssertionError("unexpected provider read " + path)
            return {
                "ok": True,
                "status": 200 if rows else 204,
                "data": {
                    "data": copy.deepcopy(rows),
                    "info": {"more_records": False},
                },
            }

        if method == "PUT" and path == "/crm/v8/Leads/123":
            self.lead.update(kwargs["body"]["data"][0])
            if self.accept_then_lose:
                raise httpx.ReadTimeout("accepted but response lost")
            identity = "123"
        elif method == "POST" and path == "/crm/v8/Tasks":
            task = {"id": "789", **kwargs["body"]["data"][0]}
            task["Who_Id"] = {"id": task["Who_Id"]}
            self.tasks.append(task)
            identity = "789"
            if self.lost_task:
                raise httpx.ReadTimeout("task accepted but response lost")
        else:
            raise AssertionError("unexpected provider write")

        return {
            "ok": True,
            "status": 200,
            "request_id": "evidence-only",
            "data": {
                "data": [{"status": "success", "details": {"id": identity}}],
            },
        }

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]


class Phase6CrmActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.fake = Phase6LeadFake()
        self.definitions = Path(__file__).resolve().parents[1] / "config/automation/workflows"
        self.engine = AutomationEngine(self.store, self.definitions)
        register_crm_lead_actions(self.engine, self.fake, self.store)
        for name in ("opticable-crm-lead-observe.yaml", "opticable-crm-lead-reconcile.yaml"):
            definition = WorkflowDefinition.model_validate(
                yaml.safe_load((self.definitions / name).read_text())
            )
            self.store.upsert_workflow(definition)
        self.env = patch.dict(
            os.environ,
            {"OPTIBRAIN_CRM_LEAD_WRITES": PHASE6_POLICY},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def hint(self, native="one", occurred_at="2026-09-28T14:00:00Z"):
        return AutomationEvent(
            event_type="zoho.crm.Leads.insert",
            source="zoho_crm",
            source_account="org-fixture",
            provider_event_id=native,
            occurred_at=occurred_at,
            payload={"ids": ["123"]},
        )

    def reviewed(self, decision, *, native="direct"):
        return AutomationEvent(
            event_type="opticable.crm.lead.reviewed",
            source="crm-lead-observer",
            source_account="org-fixture",
            provider_event_id=native,
            occurred_at="2026-09-28T14:00:00Z",
            payload={
                "lead_id": "123",
                "version": decision.version,
                "sales_decision": decision.model_dump(),
            },
        )

    def drain(self):
        for _ in range(4):
            self.engine.recover_pending(limit=20)

    def statuses(self):
        with self.store._connect() as conn:
            return {row[0] for row in conn.execute("SELECT status FROM automation_runs")}

    def test_phase6_updates_followup_normalization_and_one_internal_task(self):
        self.engine.ingest(self.hint())
        self.drain()

        self.assertEqual([call[0] for call in self.fake.writes], ["PUT", "POST"])
        self.assertEqual(self.fake.lead["Normalized_Email"], "sales@example.test")
        self.assertEqual(self.fake.lead["Normalized_Phone"], "+15145550123")
        self.assertEqual(
            self.fake.lead["Next_Followup_At"],
            "2026-09-29T21:00:00+00:00",
        )
        self.assertEqual(len(self.fake.tasks), 1)
        self.assertEqual(self.fake.tasks[0]["Due_Date"], "2026-09-29")
        self.assertEqual(self.fake.tasks[0]["Status"], "Not Started")
        self.assertEqual(self.fake.writes[0][2]["headers"], {
            "If-Unmodified-Since": "2026-09-28T13:00:00Z",
        })
        self.assertEqual(
            self.fake.writes[0][2]["body"]["skip_feature_execution"],
            [{"name": "cadences"}],
        )

        evidence = json.dumps(self.store.recent_audit(), sort_keys=True)
        self.assertNotIn("sales@example.test", evidence)
        self.assertNotIn("+15145550123", evidence)

    def test_new_version_preserves_future_followup_and_does_not_duplicate_task(self):
        self.engine.ingest(self.hint())
        self.drain()
        self.assertEqual(len(self.fake.writes), 2)

        self.fake.lead["Modified_Time"] = "2026-09-28T14:01:00Z"
        self.engine.ingest(self.hint("next", "2026-09-28T14:02:00Z"))
        self.drain()

        self.assertEqual(len(self.fake.writes), 2)
        self.assertEqual(len(self.fake.tasks), 1)
        self.assertEqual(
            self.fake.lead["Next_Followup_At"],
            "2026-09-29T21:00:00+00:00",
        )

    def test_lost_lead_response_reconciles_exact_hash_without_second_put(self):
        self.fake.accept_then_lose = True
        self.engine.ingest(self.hint())
        self.drain()
        self.assertEqual([call[0] for call in self.fake.writes], ["PUT"])
        self.assertIn("human_action_required", self.statuses())

        self.fake.accept_then_lose = False
        self.fake.lead["Modified_Time"] = "2026-09-28T14:01:00Z"
        self.engine.ingest(self.hint("after-loss", "2026-09-28T14:02:00Z"))
        self.drain()

        self.assertEqual([call[0] for call in self.fake.writes], ["PUT", "POST"])
        latest = DesiredJournal(self.store).last(
            "crm-lead-phase6-update:123",
            ("verified",),
        )
        self.assertIsNotNone(latest)
        self.assertTrue(latest["metadata"].get("reconciled_by_readback"))

    def test_lost_lead_response_with_drift_never_retries(self):
        self.fake.accept_then_lose = True
        self.engine.ingest(self.hint())
        self.drain()
        self.assertEqual(len(self.fake.writes), 1)

        self.fake.accept_then_lose = False
        self.fake.lead["Normalized_Email"] = "drift@example.test"
        self.fake.lead["Modified_Time"] = "2026-09-28T14:01:00Z"
        self.engine.ingest(self.hint("drift", "2026-09-28T14:02:00Z"))
        self.drain()

        self.assertEqual(len(self.fake.writes), 1)
        latest = DesiredJournal(self.store).last(
            "crm-lead-phase6-update:123",
            ("started", "manual", "verified"),
        )
        self.assertEqual(latest["action"], "manual")

    def test_lost_task_response_is_reconciled_by_identity_without_second_post(self):
        self.fake.lost_task = True
        self.engine.ingest(self.hint())
        self.drain()
        self.assertEqual([call[0] for call in self.fake.writes], ["PUT", "POST"])
        self.assertEqual(len(self.fake.tasks), 1)

        self.fake.lost_task = False
        self.fake.lead["Modified_Time"] = "2026-09-28T14:01:00Z"
        self.engine.ingest(self.hint("task-reconcile", "2026-09-28T14:02:00Z"))
        self.drain()

        self.assertEqual([call[0] for call in self.fake.writes], ["PUT", "POST"])
        self.assertEqual(len(self.fake.tasks), 1)
        verified = [
            row for row in self.store.recent_audit(limit=100)
            if row["category"] == "desired_state_v1"
            and row["action"] == "verified"
            and str(row["target"]).startswith("crm-lead-phase6-task:123:")
        ]
        self.assertTrue(any(row["metadata"].get("reconciled_by_readback") for row in verified))

    def test_trusted_service_fill_requires_hashed_reviewed_decision(self):
        self.fake.lead["Service_Types"] = None
        decision = build_sales_decision(
            self.fake.lead,
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
            trusted_service_hint={
                "value": "Structured Cabling",
                "evidence": "explicit_customer_selection",
            },
        )
        self.engine.ingest(self.reviewed(decision))
        self.drain()

        self.assertEqual(self.fake.lead["Service_Types"], "Structured Cabling")
        self.assertEqual(self.fake.writes[0][0], "PUT")
        self.assertIn("Service_Types", self.fake.writes[0][2]["body"]["data"][0])

    def test_tampered_sales_decision_fails_before_any_write(self):
        decision = build_sales_decision(
            self.fake.lead,
            now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc),
        ).model_dump()
        decision["followup_at"] = "2026-10-31T21:00:00+00:00"
        event = AutomationEvent(
            event_type="opticable.crm.lead.reviewed",
            source="crm-lead-observer",
            occurred_at="2026-09-28T14:00:00Z",
            payload={
                "lead_id": "123",
                "version": decision["version"],
                "sales_decision": decision,
            },
        )
        self.engine.ingest(event)
        self.drain()
        self.assertFalse(self.fake.writes)

    def test_converted_lead_has_no_phase6_provider_writes(self):
        self.fake.lead["Converted__s"] = True
        self.engine.ingest(self.hint())
        self.drain()
        self.assertFalse(self.fake.writes)


if __name__ == "__main__":
    unittest.main()
