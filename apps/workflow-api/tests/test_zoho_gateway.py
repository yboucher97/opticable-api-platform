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
from workflow.zoho_gateway import ZohoGatewayClient, ZohoWriteUnconfirmedError


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

    def standby_client(self) -> ZohoGatewayClient:
        settings = ZohoGatewaySettings(
            base_url="https://connect.opticable.ca",
            api_key="test-key",
            timeout_seconds=60,
            standby_enabled=True,
        )
        return ZohoGatewayClient(settings, FakeOAuth())

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
                headers={"x-request-id": "zoho-request-123"},
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
        self.assertEqual(result["request_id"], "zoho-request-123")
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

    def test_mutation_transport_failure_never_replays_through_standby(self) -> None:
        client = self.standby_client()
        request = httpx.Request("POST", "https://www.zohoapis.com/crm/v8/Leads")
        with (
            patch(
                "workflow.zoho_gateway.httpx.request",
                side_effect=httpx.ReadTimeout("response lost", request=request),
            ) as local_request,
            patch.object(client, "_standby_request") as standby,
        ):
            with self.assertRaises(ZohoWriteUnconfirmedError) as caught:
                client.request(
                    "zohoapis",
                    "POST",
                    "/crm/v8/Leads",
                    body={"data": [{"Last_Name": "Fixture"}]},
                    reason="Create fixture lead",
                    confirm=True,
                )
        self.assertTrue(getattr(caught.exception, "ambiguous_external_write", False))
        self.assertEqual(local_request.call_count, 1)
        standby.assert_not_called()

    def test_read_transport_failure_may_use_configured_standby(self) -> None:
        client = self.standby_client()
        request = httpx.Request("GET", "https://www.zohoapis.com/crm/v8/Leads")
        fallback = {"ok": True, "status": 200, "provider_path": "connect_standby", "data": []}
        with (
            patch(
                "workflow.zoho_gateway.httpx.request",
                side_effect=httpx.ReadTimeout("response lost", request=request),
            ) as local_request,
            patch.object(client, "_standby_request", return_value=fallback) as standby,
        ):
            result = client.request("zohoapis", "GET", "/crm/v8/Leads")
        self.assertEqual(result, fallback)
        self.assertEqual(local_request.call_count, 1)
        standby.assert_called_once()

    def test_mutation_preflight_failure_can_use_standby_before_local_send(self) -> None:
        class DisconnectedOAuth:
            def status(self):
                class Status:
                    configured = False
                    connected = False
                return Status()

        settings = ZohoGatewaySettings(
            base_url="https://connect.opticable.ca",
            api_key="test-key",
            timeout_seconds=60,
            standby_enabled=True,
        )
        client = ZohoGatewayClient(settings, DisconnectedOAuth())
        fallback = {"ok": True, "status": 200, "provider_path": "connect_standby", "data": {}}
        with patch.object(client, "_standby_request", return_value=fallback) as standby:
            result = client.request(
                "zohoapis",
                "POST",
                "/crm/v8/Leads",
                body={"data": [{"Last_Name": "Fixture"}]},
                reason="Create fixture lead",
                confirm=True,
            )
        self.assertEqual(result, fallback)
        standby.assert_called_once()

    def test_explicit_mutation_provider_failure_does_not_fail_over(self) -> None:
        client = self.standby_client()
        response = httpx.Response(
            503,
            json={"code": "TEMPORARY"},
            request=httpx.Request("POST", "https://www.zohoapis.com/crm/v8/Leads"),
        )
        with (
            patch("workflow.zoho_gateway.httpx.request", return_value=response) as local_request,
            patch.object(client, "_standby_request") as standby,
        ):
            with self.assertRaises(Exception):
                client.request(
                    "zohoapis",
                    "POST",
                    "/crm/v8/Leads",
                    body={"data": [{"Last_Name": "Fixture"}]},
                    reason="Create fixture lead",
                    confirm=True,
                )
        self.assertEqual(local_request.call_count, 1)
        standby.assert_not_called()

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
