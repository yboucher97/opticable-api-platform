from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.automation.capabilities import capability_summary, load_capabilities
from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
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
        with patch("workflow.automation.store.uuid4", side_effect=[type("Id", (), {"hex": "first"})(), RuntimeError("crash")]):
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
        self.assertIn("Unknown automation action", run["error"])
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
        self.assertIn("Workflow template reference not found", run["error"])
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
