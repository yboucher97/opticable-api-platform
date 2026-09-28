from __future__ import annotations

import tempfile
import threading
import unittest
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from workflow.automation.capabilities import capability_summary, load_capabilities
from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore


class AutomationKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = AutomationStore(self.root / "automation.db")
        self.workflows = self.root / "workflows"
        self.workflows.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_smoke_workflow(self) -> None:
        (self.workflows / "smoke.yaml").write_text(
            """
id: test.smoke
name: Test smoke
version: 1
enabled: true
trigger:
  event_types: [test.started]
  sources: [unit-test]
steps:
  - id: set_value
    action: core.set
    with:
      values:
        answer: 42
  - id: emit_done
    action: event.emit
    with:
      event_type: test.completed
      source: automation-engine
      payload:
        ok: true
""".strip()
            + "\n",
            encoding="utf-8",
        )

    def test_workflow_executes_and_persists(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        self.assertEqual(engine.sync_definitions(), ["test.smoke"])

        response = engine.ingest(
            AutomationEvent(
                event_type="test.started",
                source="unit-test",
                idempotency_key="smoke-1",
                payload={"input": "hello"},
            )
        )
        self.assertTrue(response.accepted)
        self.assertFalse(response.duplicate)
        self.assertEqual(len(response.run_ids), 1)

        run = self.store.get_run(response.run_ids[0])
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run["status"], "completed")
        self.assertEqual([step["status"] for step in run["steps"]], ["completed", "completed"])
        self.assertEqual(run["context"]["vars"]["answer"], 42)
        definition = WorkflowDefinition.model_validate(yaml.safe_load(
            (self.workflows / "smoke.yaml").read_text()))
        repeated = engine._action_emit(run["context"], definition.steps[1])
        self.assertTrue(repeated["duplicate"])

    def test_idempotency_prevents_duplicate_run(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(
            event_type="test.started",
            source="unit-test",
            idempotency_key="same-request",
        )
        first = engine.ingest(event)
        second = engine.ingest(
            AutomationEvent(
                event_type="test.started",
                source="unit-test",
                idempotency_key="same-request",
            )
        )
        self.assertTrue(first.accepted)
        self.assertTrue(second.duplicate)
        self.assertFalse(second.accepted)
        self.assertEqual(second.event_id, first.event_id)
        self.assertEqual(len(self.store.recent_runs()), 1)

    def test_event_and_all_runs_roll_back_together_on_crash(self) -> None:
        self._write_smoke_workflow()
        (self.workflows / "second.yaml").write_text(
            (self.workflows / "smoke.yaml").read_text().replace("test.smoke", "test.second")
        )
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test", idempotency_key="crash")
        with patch("workflow.automation.events.uuid4", side_effect=[type("Id", (), {"hex": "first"})(), RuntimeError("crash")]):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                engine.ingest(event)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_runs").fetchone()[0], 0)
        result = engine.ingest(event)
        self.assertEqual(len(result.run_ids), 2)
        self.assertEqual(len(self.store.recent_runs()), 2)

    def test_duplicate_ingest_across_store_instances_has_one_run(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        other = AutomationStore(self.store.db_path)
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def submit(store: AutomationStore) -> None:
            try:
                barrier.wait()
                results.append(store.ingest_event_and_runs(AutomationEvent(
                    event_type="test.started", source="unit-test", idempotency_key="raced")))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=submit, args=(store,)) for store in (self.store, other)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(result[0] for result in results), [False, True])
        self.assertEqual(len(self.store.recent_runs()), 1)

    def test_crash_after_commit_leaves_visible_queued_run(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test", idempotency_key="before-execute")
        with patch.object(engine, "execute_run", side_effect=RuntimeError("crash")):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                engine.ingest(event)
        self.assertEqual(self.store.recent_runs()[0]["status"], "queued")
        duplicate = engine.ingest(event)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(len(self.store.recent_runs()), 1)

    def test_execution_health_flags_stale_work_without_replay(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        queued = self.store.create_run("test.smoke", event.event_id, event.event_id)
        running = self.store.create_run("test.smoke", event.event_id, event.event_id)
        failed = self.store.create_run("test.smoke", event.event_id, event.event_id)
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_runs SET created_at=? WHERE run_id=?",
                         ("2026-09-27T15:00:00Z", queued))
            conn.execute("UPDATE automation_runs SET status='running',started_at=? WHERE run_id=?",
                         ("2026-09-27T14:00:00Z", running))
            conn.execute("UPDATE automation_runs SET status='failed' WHERE run_id=?", (failed,))
        snapshot = self.store.execution_health(now=datetime(2026, 9, 27, 16, tzinfo=timezone.utc))
        self.assertEqual(snapshot, {"total": 3, "queued": 1, "claimed": 0, "running": 1,
                                    "completed": 0, "recent_failure_count": 0,
                                    "failed": 1, "partial": 0, "dead_letter": 0,
                                    "human_action_required": 0, "stale_queued": 1,
                                    "stale_running": 1, "expired_leases": 0,
                                    "oldest_queued_age_seconds": 3600,
                                    "oldest_running_age_seconds": 7200,
                                    "oldest_claim_age_seconds": 0})
        self.assertEqual(len(self.store.recent_runs()), 3)
        with self.assertRaises(ValueError):
            self.store.execution_health(now=datetime(2026, 9, 27, 16))

    def test_expired_never_started_claim_is_fenced_and_requeued(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
        old_token = self.store.claim_run(run_id, "worker-1", now=clock, lease_seconds=5)
        self.assertIsNotNone(old_token)
        self.assertIsNone(AutomationStore(self.store.db_path).claim_run(run_id, "worker-2", now=clock))
        snapshot = self.store.execution_health(now=clock + timedelta(seconds=6))
        self.assertEqual((snapshot["claimed"], snapshot["expired_leases"]), (1, 1))
        self.assertEqual(self.store.recover_expired_claims(now=clock + timedelta(seconds=6)),
                         {"requeued": 1, "human_action_required": 0})
        self.assertEqual(self.store.get_run(run_id)["status"], "queued")
        self.assertIsNone(self.store.begin_claimed_action(
            run_id, old_token, step_id="set_value", action="core.set", action_identity="a" * 64, attempt=1,
            now=clock + timedelta(seconds=6)))
        new_token = self.store.claim_run(run_id, "worker-2", now=clock + timedelta(seconds=6))
        self.assertNotEqual(new_token, old_token)

    def test_expired_started_action_requires_human_reconciliation(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
        token = self.store.claim_run(run_id, "worker-1", now=clock, lease_seconds=5)
        marker = self.store.begin_claimed_action(
            run_id, token, step_id="set_value", action="core.set", action_identity="a" * 64, attempt=1, now=clock)
        self.assertIsInstance(marker, int)
        self.assertIsNone(self.store.begin_claimed_action(
            run_id, token, step_id="set_value", action="core.set", action_identity="a" * 64, attempt=1, now=clock))
        self.assertEqual(self.store.recover_expired_claims(now=clock + timedelta(seconds=6)),
                         {"requeued": 0, "human_action_required": 1})
        self.assertEqual(self.store.get_run(run_id)["status"], "human_action_required")
        self.assertEqual(self.store.failed_work()[0]["failure_category"], "ambiguous_external")
        self.assertEqual(self.store.failed_work()[0]["reason_code"], "lease_expired_after_action")
        self.assertEqual(self.store.execution_health(now=clock + timedelta(seconds=7))["human_action_required"], 1)
        self.assertIsNone(self.store.claim_run(run_id, "worker-2", now=clock + timedelta(seconds=6)))
        self.assertEqual(self.store.recover_expired_claims(now=clock + timedelta(seconds=7)),
                         {"requeued": 0, "human_action_required": 0})

    def test_claim_transaction_rolls_back_on_audit_failure(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        with patch.object(AutomationStore, "_claim_audit", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.store.claim_run(run_id, "worker-1")
        self.assertEqual(self.store.get_run(run_id)["status"], "queued")
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_claims").fetchone()[0], 0)

    def test_claim_renewal_and_terminal_result_are_fenced(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
        token = self.store.claim_run(run_id, "worker-1", now=clock, lease_seconds=5)
        self.assertFalse(self.store.renew_claim(run_id, "wrong-token", now=clock))
        self.assertTrue(self.store.renew_claim(run_id, token, now=clock + timedelta(seconds=4),
                                               lease_seconds=10))
        marker = self.store.begin_claimed_action(
            run_id, token, step_id="set_value", action="core.set", action_identity="a" * 64, attempt=1,
            now=clock + timedelta(seconds=6))
        self.assertIsInstance(marker, int)
        self.assertFalse(self.store.finish_claim(run_id, token, status="completed", now=clock))
        self.assertFalse(self.store.complete_claimed_action(
            run_id, "wrong-token", marker, succeeded=True, now=clock))
        self.assertTrue(self.store.complete_claimed_action(
            run_id, token, marker, succeeded=True, result={"ok": True}, now=clock))
        self.assertTrue(self.store.finish_claim(run_id, token, status="completed", now=clock))
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")
        self.assertFalse(self.store.renew_claim(run_id, token, now=clock))

    def test_claim_schema_addition_preserves_existing_runs(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        with self.store._connect() as conn:
            from _phase4_fixtures import remove_event_schema
            remove_event_schema(conn)
            conn.execute("PRAGMA user_version=0")
            conn.execute("DROP TABLE automation_run_claims")
            conn.execute("DROP TABLE automation_run_failures")
        migrated = AutomationStore(self.store.db_path)
        self.assertEqual(migrated.get_run(run_id)["status"], "queued")
        self.assertIsNotNone(migrated.claim_run(run_id, "worker-after-migration"))
        with migrated._connect() as conn:
            self.assertIsNotNone(conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='automation_run_failures'"
            ).fetchone())

    def test_expired_worker_cannot_finalize_action_before_recovery_scan(self) -> None:
        self._write_smoke_workflow()
        AutomationEngine(self.store, self.workflows).sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
        token = self.store.claim_run(run_id, "worker-1", now=clock, lease_seconds=5)
        marker = self.store.begin_claimed_action(
            run_id, token, step_id="set_value", action="core.set", action_identity="a" * 64, attempt=1, now=clock)
        expired = clock + timedelta(seconds=6)
        self.assertFalse(self.store.complete_claimed_action(
            run_id, token, marker, succeeded=True, now=expired))
        self.assertFalse(self.store.finish_claim(run_id, token, status="completed", now=expired))
        self.assertEqual(self.store.recover_expired_claims(now=expired),
                         {"requeued": 0, "human_action_required": 1})

    def test_terminal_failure_category_is_durable_and_safe_to_inspect(self) -> None:
        self._write_smoke_workflow()
        AutomationEngine(self.store, self.workflows).sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test",
                                payload={"secret": "never-show-this"})
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
        token = self.store.claim_run(run_id, "worker-1", now=clock)
        marker = self.store.begin_claimed_action(
            run_id, token, step_id="set_value", action="core.set", action_identity="a" * 64, attempt=1, now=clock)
        self.assertTrue(self.store.complete_claimed_action(
            run_id, token, marker, succeeded=False, error="token=never-show-this",
            failure_category="permanent", reason_code="provider_rejected", now=clock))
        with self.assertRaises(ValueError):
            self.store.finish_claim(run_id, token, status="dead_letter",
                                    failure_category="permanent", reason_code="token=never-show-this", now=clock)
        with self.assertRaises(ValueError):
            self.store.finish_claim(run_id, token, status="dead_letter", now=clock)
        with patch.object(AutomationStore, "_claim_audit", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.store.finish_claim(run_id, token, status="dead_letter", failure_category="permanent",
                                        reason_code="provider_rejected", now=clock)
        self.assertEqual(self.store.get_run(run_id)["status"], "running")
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_failures").fetchone()[0], 1)
        self.assertTrue(self.store.finish_claim(run_id, token, status="dead_letter",
                                                failure_category="permanent", reason_code="provider_rejected",
                                                error="token=never-show-this", now=clock))
        item = AutomationStore(self.store.db_path).failed_work()[0]
        self.assertEqual((item["run_id"], item["failure_category"], item["reason_code"],
                          item["step_attempts"]), (run_id, "permanent", "provider_rejected", 1))
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_failures").fetchone()[0], 2)
        history = self.store.failure_history(run_id)
        self.assertEqual([entry["reason_code"] for entry in history],
                         ["provider_rejected", "provider_rejected"])
        self.assertEqual(history[0]["terminal_state"], "dead_letter")
        self.assertNotIn("never-show-this", str(history))
        self.assertNotIn("never-show-this", str(item))
        self.assertFalse(self.store.finish_claim(run_id, token, status="dead_letter",
                                                 failure_category="permanent", reason_code="provider_rejected",
                                                 now=clock))

    def test_early_lease_renewal_cannot_shorten_existing_lease(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test")
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        clock = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
        token = self.store.claim_run(run_id, "worker-1", now=clock, lease_seconds=300)
        self.assertTrue(self.store.renew_claim(run_id, token, now=clock, lease_seconds=5))
        self.assertEqual(self.store.recover_expired_claims(now=clock + timedelta(seconds=6)),
                         {"requeued": 0, "human_action_required": 0})

    def test_failed_work_inspection_omits_payloads_and_raw_errors(self) -> None:
        self._write_smoke_workflow()
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        event = AutomationEvent(event_type="test.started", source="unit-test",
                                payload={"secret": "never-show-this"})
        self.store.ingest_event(event)
        run_id = self.store.create_run("test.smoke", event.event_id, event.event_id)
        self.store.set_run_status(run_id, "failed", error="token=never-show-this")
        self.store.append_step(run_id=run_id, step_id="set_value", action="core.set",
                               attempt=1, status="failed", started_at="2026-09-27T16:00:00Z",
                               error="token=never-show-this")
        result = self.store.failed_work()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["run_id"], run_id)
        self.assertEqual(result[0]["step_attempts"], 1)
        self.assertNotIn("never-show-this", str(result))

    def test_unknown_action_fails_durably(self) -> None:
        (self.workflows / "bad.yaml").write_text(
            """
id: test.bad
name: Bad action
version: 1
enabled: true
trigger:
  event_types: [test.bad]
steps:
  - id: missing
    action: provider.does_not_exist
""".strip()
            + "\n",
            encoding="utf-8",
        )
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        response = engine.ingest(AutomationEvent(event_type="test.bad", source="unit-test"))
        run = self.store.get_run(response.run_ids[0])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "unknown_action")
        self.assertEqual(run["steps"][0]["status"], "failed")

    def test_workflow_templates_resolve_event_and_prior_step_context(self) -> None:
        (self.workflows / "templates.yaml").write_text(
            """
id: test.templates
name: Template resolution
version: 1
enabled: true
trigger:
  event_types: [lead.created]
steps:
  - id: capture
    action: core.noop
    with:
      email: "{{ event.payload.email }}"
      greeting: "Lead {{ event.payload.name }}"
      metadata: "{{ event.payload.metadata }}"
  - id: reuse
    action: core.noop
    with:
      prior_email: "{{ steps.capture.inputs.email }}"
""".strip()
            + "\n",
            encoding="utf-8",
        )
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        response = engine.ingest(
            AutomationEvent(
                event_type="lead.created",
                source="unit-test",
                payload={
                    "email": "lead@example.com",
                    "name": "Jane",
                    "metadata": {"source": "website", "score": 7},
                },
            )
        )
        run = self.store.get_run(response.run_ids[0])
        self.assertEqual(run["status"], "completed")
        first = run["steps"][0]["result"]["inputs"]
        second = run["steps"][1]["result"]["inputs"]
        self.assertEqual(first["email"], "lead@example.com")
        self.assertEqual(first["greeting"], "Lead Jane")
        self.assertEqual(first["metadata"], {"source": "website", "score": 7})
        self.assertEqual(second["prior_email"], "lead@example.com")

    def test_missing_template_reference_fails_durably(self) -> None:
        (self.workflows / "missing-template.yaml").write_text(
            """
id: test.missing-template
name: Missing template
version: 1
enabled: true
trigger:
  event_types: [test.template.missing]
steps:
  - id: fail
    action: core.noop
    with:
      value: "{{ event.payload.does_not_exist }}"
""".strip()
            + "\n",
            encoding="utf-8",
        )
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        response = engine.ingest(
            AutomationEvent(event_type="test.template.missing", source="unit-test")
        )
        run = self.store.get_run(response.run_ids[0])
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "template_reference_missing")
        self.assertEqual(run["steps"][0]["status"], "failed")

    def test_capability_grading_loads(self) -> None:
        path = self.root / "capabilities.yaml"
        path.write_text(
            """
capabilities:
  - provider: example
    product: product
    capability: test
    grade: B
    score: 80
    access_mode: api
    status: connected
""".strip()
            + "\n",
            encoding="utf-8",
        )
        records = load_capabilities(path)
        summary = capability_summary(records)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["average_score"], 80.0)
        self.assertEqual(summary["grade_counts"], {"B": 1})


if __name__ == "__main__":
    unittest.main()
