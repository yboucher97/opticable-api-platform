from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.lifecycle_sign_tracking import register_lifecycle_sign_tracking_actions
from workflow.automation.store import AutomationStore


class FakeZoho:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.calls: list[dict] = []
        self.task_count = 0

    def request(self, service, method, path, **kwargs):
        self.calls.append({"service": service, "method": method, "path": path, **kwargs})
        if service == "sign" and method == "GET" and path == "/requests/sig-1":
            return {
                "data": {
                    "requests": {
                        "request_id": "sig-1",
                        "request_name": "Installation agreement",
                        "request_status": self.status,
                        "actions": [
                            {
                                "action_type": "SIGN",
                                "action_status": "SIGNED" if self.status == "completed" else "UNOPENED",
                                "recipient_name": "Jane Doe",
                                "recipient_email": "jane@example.com",
                            }
                        ],
                    }
                }
            }
        if service == "zohoapis" and method == "POST" and path == "/crm/v8/Tasks":
            self.task_count += 1
            return {"data": {"data": [{"code": "SUCCESS", "details": {"id": f"task-{self.task_count}"}}]}}
        raise AssertionError(f"Unexpected request: {service} {method} {path}")


class LifecycleSignTrackingTests(unittest.TestCase):
    def _engine(self, status: str = "completed"):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(tmp.name)
        workflows = root / "workflows"
        workflows.mkdir()
        (workflows / "poll.yaml").write_text(
            """
id: test.sign.poll
name: Sign poll
version: 1
enabled: true
trigger:
  event_types: [test.sign.poll]
steps:
  - id: poll
    action: lifecycle.sign_poll_status
    with:
      max_requests: 100
""".strip() + "\n",
            encoding="utf-8",
        )
        (workflows / "terminal.yaml").write_text(
            """
id: test.sign.terminal
name: Sign terminal
version: 1
enabled: true
trigger:
  event_types:
    - customer.lifecycle.contract.completed
    - customer.lifecycle.contract.declined
    - customer.lifecycle.contract.expired
    - customer.lifecycle.contract.recalled
steps:
  - id: task
    action: lifecycle.crm_contract_status_task
    with:
      contract: "{{ event.payload }}"
""".strip() + "\n",
            encoding="utf-8",
        )
        store = AutomationStore(root / "automation.db")
        engine = AutomationEngine(store, workflows)
        zoho = FakeZoho(status=status)
        register_lifecycle_sign_tracking_actions(engine, zoho, store)
        engine.sync_definitions()
        store.audit(
            category="customer_lifecycle",
            action="contract_sent",
            actor="unit-test",
            success=True,
            correlation_id="corr-1",
            target="sig-1",
            metadata={"deal_id": "deal-1", "service_id": "svc-1", "template": "installation"},
        )
        return tmp, store, engine, zoho

    def test_completed_contract_creates_one_handoff_task_across_repeated_polls(self) -> None:
        tmp, store, engine, zoho = self._engine("completed")
        try:
            first = engine.ingest(AutomationEvent(event_type="test.sign.poll", source="unit", idempotency_key="poll-1"))
            second = engine.ingest(AutomationEvent(event_type="test.sign.poll", source="unit", idempotency_key="poll-2"))
            first_run = store.get_run(first.run_ids[0])
            second_run = store.get_run(second.run_ids[0])
            self.assertEqual(first_run["status"], "completed")
            self.assertEqual(second_run["status"], "completed")
            self.assertEqual(first_run["steps"][0]["result"]["emitted"], 1)
            self.assertEqual(second_run["steps"][0]["result"]["emitted"], 0)
            self.assertEqual(zoho.task_count, 1)
            sign_calls = [c for c in zoho.calls if c["service"] == "sign"]
            self.assertTrue(sign_calls)
            self.assertTrue(all(c["method"] == "GET" for c in sign_calls))
            task_call = next(c for c in zoho.calls if c["service"] == "zohoapis")
            task = task_call["body"]["data"][0]
            self.assertEqual(task["What_Id"], "deal-1")
            self.assertEqual(task["$se_module"], "Deals")
        finally:
            tmp.cleanup()

    def test_nonterminal_contract_does_not_create_task(self) -> None:
        tmp, store, engine, zoho = self._engine("inprogress")
        try:
            response = engine.ingest(AutomationEvent(event_type="test.sign.poll", source="unit"))
            run = store.get_run(response.run_ids[0])
            result = run["steps"][0]["result"]
            self.assertEqual(run["status"], "completed")
            self.assertEqual(result["nonterminal"], 1)
            self.assertEqual(result["emitted"], 0)
            self.assertEqual(zoho.task_count, 0)
            self.assertEqual(result["sign_mutations"], 0)
            self.assertEqual(result["books_mutations"], 0)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
