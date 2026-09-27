from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workflow import api
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore


class InspectionBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.store.upsert_workflow(WorkflowDefinition.model_validate({
            "id": "inspection", "name": "Inspection fixture",
            "trigger": {"event_types": ["inspection.event"]},
            "steps": [{"id": "one", "action": "core.noop"}],
        }))
        self.run_id = self.store.ingest_event_and_runs(AutomationEvent(
            event_type="inspection.event", source="unit-test"))[3][0][0]
        self.client = TestClient(api.app)
        self.store_patch = patch.object(api, "automation_store", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.key_name = api.settings.api.api_key_env

    def test_protected_inspection_routes_require_configured_key(self) -> None:
        paths = (
            "/v1/automation/execution-health",
            "/v1/automation/failed-work",
            f"/v1/automation/runs/{self.run_id}/failures",
            "/v1/automation/runs/missing/failures",
            "/v1/automation/runs",
            "/v1/automation/audit",
        )
        with patch.dict(os.environ, {self.key_name: "fixture-key"}):
            for path in paths:
                with self.subTest(path=path, case="missing client key"):
                    self.assertEqual(self.client.get(path).status_code, 401)
                with self.subTest(path=path, case="wrong client key"):
                    self.assertEqual(self.client.get(path, headers={"X-API-Key": "wrong"}).status_code, 401)
                with self.subTest(path=path, case="valid client key"):
                    expected = 404 if "/missing/failures" in path else 200
                    self.assertEqual(self.client.get(path, headers={"X-API-Key": "fixture-key"}).status_code,
                                     expected)
        for value in (None, "", "   "):
            with patch.dict(os.environ, {}, clear=False):
                if value is None:
                    os.environ.pop(self.key_name, None)
                else:
                    os.environ[self.key_name] = value
                with patch.object(self.store, "run_exists", side_effect=AssertionError("database reached")):
                    for path in paths:
                        with self.subTest(path=path, server_key=value):
                            response = self.client.get(path)
                            self.assertEqual(response.status_code, 503)
                            self.assertNotIn("fixture-key", response.text)

    def test_failure_history_never_loads_large_step_results(self) -> None:
        large_json = '{"data":"' + ("x" * 8192) + '"}'
        with sqlite3.connect(self.store.db_path) as conn:
            conn.executemany(
                "INSERT INTO automation_run_steps(run_id,step_id,action,attempt,status,started_at,result_json) "
                "VALUES(?,?,?,?,?,?,?)",
                [(self.run_id, f"step-{i}", "core.noop", 1, "completed",
                  "2026-01-01T00:00:00Z", large_json) for i in range(1001)],
            )
            conn.executemany(
                "INSERT INTO automation_run_failures(run_id,attempt_id,category,reason_code,recorded_at) "
                "VALUES(?,?,?,?,?)",
                [(self.run_id, f"attempt-{i}", "permanent", "fixture_error",
                  "2026-01-01T00:00:00Z") for i in range(5)],
            )
        with (patch.dict(os.environ, {self.key_name: "fixture-key"}),
              patch.object(self.store, "get_run", side_effect=AssertionError("full run loaded"))):
            url = f"/v1/automation/runs/{self.run_id}/failures"
            response = self.client.get(url + "?limit=1", headers={"X-API-Key": "fixture-key"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["failures"]), 1)
            self.assertEqual(response.json()["failures"][0]["attempt_id"], "attempt-4")
            self.assertEqual(len(self.store.failure_history(self.run_id, 1)), 1)
            self.assertEqual(self.client.get(
                url + "?limit=1000", headers={"X-API-Key": "fixture-key"}).status_code, 422)
            for invalid in ("0", "-1", "nonsense"):
                self.assertEqual(self.client.get(
                    url + "?limit=" + invalid, headers={"X-API-Key": "fixture-key"}).status_code, 422)
            self.assertEqual(self.client.get(
                "/v1/automation/runs/missing/failures",
                headers={"X-API-Key": "fixture-key"}).status_code, 404)

    def test_existing_run_without_failures_returns_empty_history(self) -> None:
        with patch.dict(os.environ, {self.key_name: "fixture-key"}):
            response = self.client.get(
                f"/v1/automation/runs/{self.run_id}/failures?limit=1",
                headers={"X-API-Key": "fixture-key"})
        self.assertEqual((response.status_code, response.json()), (200, {"failures": []}))


if __name__ == "__main__":
    unittest.main()
