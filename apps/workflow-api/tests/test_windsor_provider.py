from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.windsor import register_windsor_actions
from workflow.automation.store import AutomationStore


class FakeWindsor:
    def read(self, connector, *, fields, params=None):
        return {"ok": True, "status": 200, "data": {"connector": connector, "fields": fields}}

    def list_actions(self, connector):
        return {"ok": True, "status": 200, "data": [{"id": "pause_campaign"}]}

    def execute_action(self, connector, *, account, action, params=None):
        return {"ok": True, "status": 200, "data": {"action": action, "account": account}}


class WindsorProviderTests(unittest.TestCase):
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
