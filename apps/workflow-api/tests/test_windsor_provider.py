from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.windsor import register_windsor_actions
from workflow.automation.store import AutomationStore
from workflow.windsor_api import WindsorApiError


class FakeWindsor:
    def read(self, connector, *, fields, params=None):
        return {"ok": True, "status": 200, "data": {"connector": connector, "fields": fields}}

    def list_actions(self, connector):
        return {"ok": True, "status": 200, "data": [{"id": "pause_campaign"}]}

    def execute_action(self, connector, *, account, action, params=None):
        return {"ok": True, "status": 200, "data": {"action": action, "account": account}}


class WindsorProviderTests(unittest.TestCase):
    def test_read_retries_rate_limit_but_write_remains_untrusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = AutomationStore(root / "automation.db")
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "w.yaml").write_text("""
id: test.windsor.read
name: Windsor read retry
version: 1
enabled: true
trigger:
  event_types: [test.windsor.read]
steps:
  - id: read
    action: windsor.read
    with:
      connector: google_ads
      fields: [campaign]
    retry:
      max_attempts: 2
      backoff_seconds: 2
""".strip() + "\n", encoding="utf-8")

            class LimitedWindsor(FakeWindsor):
                calls = 0

                def read(self, connector, *, fields, params=None):
                    self.calls += 1
                    if self.calls == 1:
                        response = httpx.Response(429, headers={"Retry-After": "5"},
                                                  request=httpx.Request("GET", "https://example.invalid/read"))
                        raise WindsorApiError("rate limited", response=response)
                    return super().read(connector, fields=fields, params=params)

            client = LimitedWindsor()
            engine = AutomationEngine(store, workflows)
            register_windsor_actions(engine, client, store)
            engine.sync_definitions()
            with patch("workflow.automation.engine.time.sleep") as sleeper:
                response = engine.ingest(AutomationEvent(event_type="test.windsor.read", source="unit-test"))
            self.assertEqual(client.calls, 2)
            sleeper.assert_called_once_with(5.0)
            self.assertEqual(store.get_run(response.run_ids[0])["status"], "completed")
            self.assertEqual(store.failure_history(response.run_ids[0])[0]["category"], "rate_limited")

    def test_blocks_cost_increasing_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=AutomationStore(root/"automation.db"); workflows=root/"workflows"; workflows.mkdir()
            (workflows/"w.yaml").write_text("""
id: test.windsor
name: Windsor test
version: 1
enabled: true
trigger:
  event_types: [test.windsor]
steps:
  - id: spend
    action: windsor.execute_action
    with:
      connector: google_ads
      account: "123"
      action_id: set_campaign_budget
      reason: test
      params: {budget: 100}
""".strip()+"\n", encoding="utf-8")
            engine=AutomationEngine(store, workflows); register_windsor_actions(engine, FakeWindsor(), store); engine.sync_definitions()
            response=engine.ingest(AutomationEvent(event_type="test.windsor", source="unit-test"))
            run=store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "failed")

    def test_allows_non_cost_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=AutomationStore(root/"automation.db"); workflows=root/"workflows"; workflows.mkdir()
            (workflows/"w.yaml").write_text("""
id: test.windsor
name: Windsor test
version: 1
enabled: true
trigger:
  event_types: [test.windsor]
steps:
  - id: pause
    action: windsor.execute_action
    with:
      connector: google_ads
      account: "123"
      action_id: pause_campaign
      reason: policy test
      params: {campaign_id: "1"}
""".strip()+"\n", encoding="utf-8")
            engine=AutomationEngine(store, workflows); register_windsor_actions(engine, FakeWindsor(), store); engine.sync_definitions()
            response=engine.ingest(AutomationEvent(event_type="test.windsor", source="unit-test"))
            run=store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")


if __name__ == "__main__":
    unittest.main()
