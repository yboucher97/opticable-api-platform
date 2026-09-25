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


class FakeOAuth:
    def status(self):
        class Status:
            configured = True
            connected = True
        return Status()

    def access_token(self):
        return "local-token"


class ZohoGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = ZohoGatewaySettings(
            base_url="https://connect.opticable.ca",
            api_key="test-key",
            timeout_seconds=60,
            standby_enabled=False,
        )
        self.client = ZohoGatewayClient(self.settings, FakeOAuth())

    def test_rejects_mutation_without_reason_or_confirmation(self) -> None:
        with self.assertRaises(ValueError):
            self.client.request("creator", "POST", "/data/x/y/form/z", body={"data": []})
        with self.assertRaises(ValueError):
            self.client.request(
                "creator", "POST", "/data/x/y/form/z",
                body={"data": []}, reason="Create test", confirm=False
            )

    def test_strips_credential_headers_and_uses_local_provider(self) -> None:
        captured = {}

        def fake_request(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            return httpx.Response(
                200,
                json={"ok": True},
                request=httpx.Request(method, url),
            )

        with patch("workflow.zoho_gateway.httpx.request", side_effect=fake_request):
            result = self.client.request(
                "creator",
                "GET",
                "/meta/applications",
                headers={"Authorization": "bad", "X-API-Key": "bad", "environment": "stage"},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_path"], "local")
        self.assertEqual(captured["headers"]["environment"], "stage")
        self.assertEqual(captured["headers"]["Authorization"], "Zoho-oauthtoken local-token")

    def test_connect_standby_is_off_by_default(self) -> None:
        class BrokenOAuth:
            def status(self):
                class Status:
                    configured = False
                    connected = False
                return Status()

        client = ZohoGatewayClient(self.settings, BrokenOAuth())
        with self.assertRaises(Exception):
            client.request("creator", "GET", "/meta/applications")

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
