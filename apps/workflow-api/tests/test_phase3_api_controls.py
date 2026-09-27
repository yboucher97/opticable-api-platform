from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workflow import api
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore


class Phase3ApiControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.definition = WorkflowDefinition.model_validate({
            "id": "phase3.api.fixture",
            "name": "Phase 3 API fixture",
            "version": 4,
            "trigger": {"event_types": ["phase3.api.fixture"]},
            "steps": [{"id": "one", "action": "core.noop"}],
        })
        self.store.upsert_workflow(self.definition)

        self.store_patch = patch.object(api, "automation_store", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

        self.client = TestClient(api.app)
        self.key_name = api.settings.api.api_key_env

    def _queued_run(self) -> tuple[str, AutomationEvent]:
        event = AutomationEvent(
            event_type="phase3.api.fixture",
            source="unit-test",
        )
        accepted, _, _, runs = self.store.ingest_event_and_runs(event)
        self.assertTrue(accepted)
        self.assertEqual(len(runs), 1)
        return runs[0][0], event

    def _make_redrive_safe(self) -> str:
        run_id, event = self._queued_run()
        context = {
            "queued_definition": self.definition.model_dump(by_alias=True),
            "event": event.model_dump(),
        }
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE automation_runs SET status='dead_letter',"
                "finished_at=?,context_json=? WHERE run_id=?",
                (now, json.dumps(context), run_id),
            )
            conn.execute(
                "INSERT INTO automation_run_failures("
                "run_id,attempt_id,category,reason_code,recorded_at,"
                "terminal_state,redrive_permitted,human_required"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    "attempt-api-fixture",
                    "provider_unavailable",
                    "attempts_exhausted",
                    now,
                    "dead_letter",
                    1,
                    0,
                ),
            )
        return run_id

    def test_health_alert_route_is_fail_closed(self) -> None:
        path = "/v1/automation/health-alerts"

        with patch.dict(os.environ, {self.key_name: "fixture-key"}):
            self.assertEqual(self.client.get(path).status_code, 401)
            response = self.client.get(
                path,
                headers={"X-API-Key": "fixture-key"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn(payload["status"], {"ok", "warning", "critical"})
            self.assertIn("alerts", payload)
            self.assertIn("database", payload)
            self.assertIn("recovery_worker", payload)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(self.key_name, None)
            self.assertEqual(self.client.get(path).status_code, 503)

    def test_state_changing_control_routes_require_api_key(self) -> None:
        run_id = "0" * 32
        redrive = f"/v1/automation/runs/{run_id}/redrive"
        cleanup = "/v1/automation/maintenance/cleanup-terminal-claims"

        with patch.dict(os.environ, {self.key_name: "fixture-key"}):
            self.assertEqual(
                self.client.post(
                    redrive,
                    json={"reason": "Explicit controlled redrive request"},
                ).status_code,
                401,
            )
            self.assertEqual(
                self.client.post(
                    cleanup,
                    json={
                        "reason": "Explicit bounded retention cleanup",
                        "retention_days": 30,
                        "limit": 10,
                    },
                ).status_code,
                401,
            )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(self.key_name, None)
            self.assertEqual(
                self.client.post(
                    redrive,
                    json={"reason": "Explicit controlled redrive request"},
                ).status_code,
                503,
            )
            self.assertEqual(
                self.client.post(
                    cleanup,
                    json={
                        "reason": "Explicit bounded retention cleanup",
                        "retention_days": 30,
                        "limit": 10,
                    },
                ).status_code,
                503,
            )

    def test_controlled_redrive_endpoint_creates_new_queued_run(self) -> None:
        source_run = self._make_redrive_safe()

        with patch.dict(os.environ, {self.key_name: "fixture-key"}):
            response = self.client.post(
                f"/v1/automation/runs/{source_run}/redrive",
                headers={"X-API-Key": "fixture-key"},
                json={"reason": "Provider recovered after verified outage"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source_run_id"], source_run)
        self.assertEqual(payload["status"], "queued")
        self.assertNotEqual(payload["run_id"], source_run)
        self.assertEqual(self.store.get_run(source_run)["status"], "dead_letter")
        self.assertEqual(self.store.get_run(payload["run_id"])["status"], "queued")

    def test_cleanup_endpoint_does_not_touch_active_claims(self) -> None:
        old_run, _ = self._queued_run()
        active_run, _ = self._queued_run()

        self.assertIsNotNone(
            self.store.claim_run(old_run, "old-worker", lease_seconds=300)
        )
        self.assertIsNotNone(
            self.store.claim_run(active_run, "active-worker", lease_seconds=300)
        )

        old_finished = (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat().replace("+00:00", "Z")

        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE automation_runs SET status='completed',finished_at=? "
                "WHERE run_id=?",
                (old_finished, old_run),
            )

        with patch.dict(os.environ, {self.key_name: "fixture-key"}):
            response = self.client.post(
                "/v1/automation/maintenance/cleanup-terminal-claims",
                headers={"X-API-Key": "fixture-key"},
                json={
                    "reason": "Explicit bounded retention cleanup",
                    "retention_days": 30,
                    "limit": 10,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_claims"], 1)

        with sqlite3.connect(self.store.db_path) as conn:
            old_claim = conn.execute(
                "SELECT 1 FROM automation_run_claims WHERE run_id=?",
                (old_run,),
            ).fetchone()
            active_claim = conn.execute(
                "SELECT 1 FROM automation_run_claims WHERE run_id=?",
                (active_run,),
            ).fetchone()

        self.assertIsNone(old_claim)
        self.assertIsNotNone(active_claim)

    def test_scheduler_heartbeat_can_be_detected_stale_while_thread_alive(self) -> None:
        class FakeThread:
            def is_alive(self) -> bool:
                return True

        with api._automation_recovery_lock:
            original_state = dict(api._automation_recovery_state)
            original_thread = api._automation_recovery_thread

        try:
            with api._automation_recovery_lock:
                api._automation_recovery_state.update({
                    "enabled": True,
                    "state": "running",
                    "consecutive_failures": 0,
                    "scan_in_progress": False,
                    "_scan_started_monotonic": None,
                    "_last_success_monotonic": (
                        api.time.monotonic()
                        - api.AUTOMATION_RECOVERY_HEARTBEAT_STALE_SECONDS
                        - 1
                    ),
                    "last_scan_started_at": "20260927T220000Z",
                    "last_scan_completed_at": "20260927T220001Z",
                    "last_success_at": "20260927T220001Z",
                    "stopped_due_to_failures": False,
                })
                api._automation_recovery_thread = FakeThread()

            health = api._automation_recovery_health()
            self.assertTrue(health["thread_alive"])
            self.assertTrue(health["heartbeat_stale"])
            self.assertFalse(health["healthy"])
            self.assertGreaterEqual(
                health["heartbeat_age_seconds"],
                int(api.AUTOMATION_RECOVERY_HEARTBEAT_STALE_SECONDS),
            )
            self.assertNotIn("_last_success_monotonic", health)
        finally:
            with api._automation_recovery_lock:
                api._automation_recovery_state.clear()
                api._automation_recovery_state.update(original_state)
                api._automation_recovery_thread = original_thread


if __name__ == "__main__":
    unittest.main()
