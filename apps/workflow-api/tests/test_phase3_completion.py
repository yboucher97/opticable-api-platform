from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow.automation.health_monitor import AutomationHealthMonitor
from workflow.automation.maintenance import AutomationMaintenance
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore


class Phase3HealthMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.monitor = AutomationHealthMonitor(
            self.store,
            sample_interval_seconds=30,
            queue_backlog_threshold=5,
            queue_growth_threshold=3,
            recent_failure_threshold=2,
        )
        self.worker = {
            "enabled": True,
            "state": "running",
            "thread_alive": True,
            "healthy": True,
            "scan_stalled": False,
            "heartbeat_stale": False,
            "stopped_due_to_failures": False,
            "consecutive_failures": 0,
        }

    def test_healthy_snapshot_has_no_alerts(self) -> None:
        snapshot = self.monitor.evaluate(
            self.worker,
            database_health={
                "queued": 0,
                "claimed": 0,
                "running": 0,
                "stale_queued": 0,
                "stale_running": 0,
                "expired_leases": 0,
                "human_action_required": 0,
                "dead_letter": 0,
                "recent_failure_count": 0,
            },
        )
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["alerts"], [])

    def test_worker_stall_and_execution_failures_are_critical(self) -> None:
        worker = dict(self.worker, scan_stalled=True, healthy=False)
        snapshot = self.monitor.evaluate(
            worker,
            database_health={
                "queued": 1,
                "claimed": 0,
                "running": 1,
                "stale_queued": 1,
                "stale_running": 1,
                "expired_leases": 1,
                "human_action_required": 2,
                "dead_letter": 1,
                "recent_failure_count": 3,
            },
        )
        codes = {item["code"] for item in snapshot["alerts"]}
        self.assertEqual(snapshot["status"], "critical")
        self.assertIn("recovery_worker_stalled", codes)
        self.assertIn("expired_leases", codes)
        self.assertIn("human_action_required", codes)
        self.assertIn("stale_running", codes)

    def test_stale_scheduler_heartbeat_is_critical(self) -> None:
        worker = dict(self.worker, heartbeat_stale=True, healthy=False)
        snapshot = self.monitor.evaluate(
            worker,
            database_health={
                "queued": 0,
                "claimed": 0,
                "running": 0,
                "stale_queued": 0,
                "stale_running": 0,
                "expired_leases": 0,
                "human_action_required": 0,
                "dead_letter": 0,
                "recent_failure_count": 0,
            },
        )
        self.assertEqual(snapshot["status"], "critical")
        self.assertIn(
            "recovery_worker_heartbeat_stale",
            {item["code"] for item in snapshot["alerts"]},
        )

    def test_queue_growth_is_compared_to_previous_durable_sample(self) -> None:
        snapshot = self.monitor.evaluate(
            self.worker,
            database_health={
                "queued": 8,
                "claimed": 0,
                "running": 0,
                "stale_queued": 0,
                "stale_running": 0,
                "expired_leases": 0,
                "human_action_required": 0,
                "dead_letter": 0,
                "recent_failure_count": 0,
            },
            previous_sample={"queued": 2},
        )
        codes = {item["code"] for item in snapshot["alerts"]}
        self.assertIn("queue_growth", codes)
        self.assertIn("queue_backlog", codes)

    def test_observe_persists_initial_state_then_deduplicates_transition(self) -> None:
        first = self.monitor.observe(self.worker, force=True)
        second = self.monitor.observe(self.worker, force=True)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertTrue(first["state_changed"])
        self.assertFalse(second["state_changed"])
        audit = self.store.recent_audit(20)
        health_items = [item for item in audit if item["category"] == "automation_health"]
        self.assertEqual(
            sum(item["action"] == "alert_state_changed" for item in health_items),
            1,
        )
        self.assertEqual(sum(item["action"] == "sample" for item in health_items), 2)
        sample = next(item for item in health_items if item["action"] == "sample")
        self.assertNotIn("payload", sample["metadata"])
        self.assertNotIn("error", sample["metadata"])


    def test_alert_transition_bypasses_periodic_sample_throttle(self) -> None:
        first = self.monitor.observe(self.worker, force=True)
        self.assertEqual(first["status"], "ok")

        dead = dict(
            self.worker,
            thread_alive=False,
            healthy=False,
        )

        # This happens immediately, well inside the 30-second sample interval.
        second = self.monitor.observe(dead)

        self.assertEqual(second["status"], "critical")
        self.assertTrue(second["state_changed"])
        self.assertTrue(second["sample_persisted"])

        codes = {
            item["code"]
            for item in second["alerts"]
        }
        self.assertIn("recovery_worker_dead", codes)

        transitions = [
            item
            for item in self.store.recent_audit(20)
            if item["category"] == "automation_health"
            and item["action"] == "alert_state_changed"
        ]
        self.assertEqual(len(transitions), 2)




class Phase3MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.maintenance = AutomationMaintenance(self.store)
        self.definition = WorkflowDefinition.model_validate({
            "id": "phase3.fixture",
            "name": "Phase 3 fixture",
            "version": 7,
            "trigger": {"event_types": ["phase3.fixture"]},
            "steps": [{"id": "one", "action": "core.noop"}],
        })
        self.store.upsert_workflow(self.definition)

    def _queued_run(self) -> tuple[str, AutomationEvent]:
        event = AutomationEvent(event_type="phase3.fixture", source="unit-test")
        accepted, _, _, runs = self.store.ingest_event_and_runs(event)
        self.assertTrue(accepted)
        self.assertEqual(len(runs), 1)
        return runs[0][0], event

    def test_cleanup_deletes_only_old_terminal_claims(self) -> None:
        old_run, _ = self._queued_run()
        active_run, _ = self._queued_run()
        old_attempt = self.store.claim_run(old_run, "worker-old", lease_seconds=300)
        active_attempt = self.store.claim_run(active_run, "worker-active", lease_seconds=300)
        self.assertIsNotNone(old_attempt)
        self.assertIsNotNone(active_attempt)

        old_finished = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat().replace("+00:00", "Z")
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE automation_runs SET status='completed',finished_at=? WHERE run_id=?",
                (old_finished, old_run),
            )

        result = self.maintenance.cleanup_terminal_claims(retention_days=30, limit=10)
        self.assertEqual(result, {"deleted_claims": 1})

        with sqlite3.connect(self.store.db_path) as conn:
            old_claim = conn.execute(
                "SELECT 1 FROM automation_run_claims WHERE run_id=?", (old_run,)
            ).fetchone()
            active_claim = conn.execute(
                "SELECT 1 FROM automation_run_claims WHERE run_id=?", (active_run,)
            ).fetchone()
        self.assertIsNone(old_claim)
        self.assertIsNotNone(active_claim)

    def _make_redrive_terminal(self, *, permitted: bool, human_required: bool = False,
                               category: str = "provider_unavailable") -> str:
        run_id, event = self._queued_run()
        context = {
            "queued_definition": self.definition.model_dump(by_alias=True),
            "event": event.model_dump(),
        }
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE automation_runs SET status='dead_letter',finished_at=?,context_json=? WHERE run_id=?",
                (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                 json.dumps(context), run_id),
            )
            conn.execute(
                "INSERT INTO automation_run_failures(run_id,attempt_id,category,reason_code,recorded_at,"
                "terminal_state,redrive_permitted,human_required) VALUES(?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    "attempt-fixture",
                    category,
                    "attempts_exhausted",
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "dead_letter",
                    int(permitted),
                    int(human_required),
                ),
            )
        return run_id

    def test_redrive_creates_new_queued_run_from_exact_snapshot(self) -> None:
        source_run = self._make_redrive_terminal(permitted=True)
        result = self.maintenance.redrive(
            source_run,
            actor="unit-test",
            reason="Provider recovered after bounded outage",
        )
        self.assertEqual(result["source_run_id"], source_run)
        self.assertEqual(result["status"], "queued")
        self.assertNotEqual(result["run_id"], source_run)
        new_run = self.store.get_run(result["run_id"])
        self.assertIsNotNone(new_run)
        self.assertEqual(new_run["status"], "queued")
        self.assertEqual(new_run["context"]["redrive_of_run_id"], source_run)
        self.assertEqual(new_run["context"]["queued_definition"]["version"], 7)
        self.assertEqual(self.store.get_run(source_run)["status"], "dead_letter")

    def test_redrive_refuses_human_or_ambiguous_work(self) -> None:
        human = self._make_redrive_terminal(
            permitted=True,
            human_required=True,
            category="ambiguous_external",
        )
        with self.assertRaises(ValueError):
            self.maintenance.redrive(
                human,
                actor="unit-test",
                reason="Unsafe ambiguous write must remain blocked",
            )

    def test_redrive_refuses_missing_exact_workflow_snapshot(self) -> None:
        source_run = self._make_redrive_terminal(permitted=True)
        with sqlite3.connect(self.store.db_path) as conn:
            conn.execute(
                "UPDATE automation_runs SET context_json='{}' WHERE run_id=?",
                (source_run,),
            )
        with self.assertRaises(ValueError):
            self.maintenance.redrive(
                source_run,
                actor="unit-test",
                reason="Missing exact workflow snapshot must fail closed",
            )


if __name__ == "__main__":
    unittest.main()
