from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.zoho import register_zoho_actions
from workflow.automation.store import AutomationStore
from workflow.config import ZohoGatewaySettings
from workflow.zoho_gateway import ZohoGatewayClient


class ZohoGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = ZohoGatewaySettings(
            base_url="https://connect.opticable.ca",
            api_key="test-key",
            timeout_seconds=60,
        )
        self.client = ZohoGatewayClient(self.settings)

    def test_rejects_mutation_without_reason_or_confirmation(self) -> None:
        with self.assertRaises(ValueError):
            self.client.request("creator", "POST", "/data/x/y/form/z", body={"data": []})
        with self.assertRaises(ValueError):
            self.client.request(
                "creator", "POST", "/data/x/y/form/z",
                body={"data": []}, reason="Create test", confirm=False
            )

    def test_strips_credential_headers(self) -> None:
        captured = {}

        def fake_post(url, **kwargs):
            captured["payload"] = kwargs["json"]
            return httpx.Response(
                200,
                json={"ok": True, "status": 200, "data": {"ok": True}},
                request=httpx.Request("POST", url),
            )

        with patch("workflow.zoho_gateway.httpx.post", side_effect=fake_post):
            result = self.client.request(
                "creator",
                "GET",
                "/meta/applications",
                headers={"Authorization": "bad", "X-API-Key": "bad", "environment": "stage"},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(captured["payload"]["headers"], {"environment": "stage"})

    def test_workflow_action_uses_gateway(self) -> None:
        class FakeGateway:
            def request(self, service, method, path, **kwargs):
                return {"ok": True, "status": 200, "data": {"service": service, "path": path}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = AutomationStore(root / "automation.db")
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "zoho.yaml").write_text(
                """
id: test.zoho
name: Zoho gateway action
version: 1
enabled: true
trigger:
  event_types: [test.zoho]
steps:
  - id: list_creator_apps
    action: zoho.request
    with:
      service: creator
      method: GET
      path: /meta/applications
""".strip() + "\n",
                encoding="utf-8",
            )

            engine = AutomationEngine(store, workflows)
            register_zoho_actions(engine, FakeGateway(), store)
            engine.sync_definitions()
            response = engine.ingest(AutomationEvent(event_type="test.zoho", source="unit-test"))
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["steps"][0]["result"]["data"]["service"], "creator")


if __name__ == "__main__":
    unittest.main()
