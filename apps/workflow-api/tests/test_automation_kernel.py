from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
