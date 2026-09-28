from __future__ import annotations

import hashlib
import asyncio
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from workflow.automation.events import EventLedger
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore
from workflow.automation.webhooks import WebhookEndpoint, WebhookError, accept_delivery, verify_delivery
from workflow.automation.delta_sync import DeltaSync

SECRET = "fixture-secret-" + "a" * 32


class WebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.ledger = EventLedger(self.store)
        self.env = patch.dict(os.environ, {"PHASE4_TEST_WEBHOOK_SECRET": SECRET}); self.env.start(); self.addCleanup(self.env.stop)

    def endpoint(self, provider="github", **kwargs):
        return WebhookEndpoint(provider=provider, source_account="account-one", secret_env="PHASE4_TEST_WEBHOOK_SECRET",
            allowed_event_types=["github.push"], enabled=True, **kwargs)

    def github(self, raw=b'{"repository":{"id":123},"ref":"refs/heads/main"}', delivery=None):
        return raw, {"content-type": "application/json", "x-github-event": "push", "x-github-delivery": delivery or str(uuid4()),
                     "x-hub-signature-256": "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()}

    def test_valid_signature_intake_and_duplicate(self):
        raw, headers = self.github()
        first = accept_delivery(self.ledger, self.endpoint(), headers, raw)
        second = accept_delivery(self.ledger, self.endpoint(), headers, raw)
        self.assertTrue(first["accepted"]); self.assertTrue(second["duplicate"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(self.ledger.inspect(first["event_id"])["status"], "accepted")
        self.assertEqual(self.store.recent_runs(), [])

    def test_invalid_signature_does_not_persist_payload(self):
        raw, headers = self.github(); headers["x-hub-signature-256"] = "sha256=invalid"
        with self.assertRaises(WebhookError): accept_delivery(self.ledger, self.endpoint(), headers, raw)
        self.assertEqual(self.ledger.list_events(), [])

    def test_signature_verifies_exact_raw_bytes(self):
        raw, headers = self.github()
        with self.assertRaises(WebhookError): verify_delivery(self.endpoint(), headers, raw + b" ")

    def test_missing_short_or_disabled_secret_fails_closed(self):
        raw, headers = self.github()
        for value in ("", "short", " " * 32):
            with self.subTest(value=value), patch.dict(os.environ, {"PHASE4_TEST_WEBHOOK_SECRET": value}), self.assertRaises(WebhookError):
                verify_delivery(self.endpoint(), headers, raw)
        endpoint = self.endpoint().model_copy(update={"enabled": False})
        with self.assertRaises(WebhookError): verify_delivery(endpoint, headers, raw)

    def test_malformed_duplicate_key_nan_and_nonobject_json_rejected(self):
        for raw in (b"{", b"[]", b'{"id":1,"id":2}', b'{"value":NaN}', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(WebhookError):
                body, headers = self.github(raw); verify_delivery(self.endpoint(), headers, body)

    def test_oversized_and_bad_content_type_rejected(self):
        raw, headers = self.github()
        for content_type in ("text/plain", "application/x-www-form-urlencoded", ""):
            with self.subTest(content_type=content_type), self.assertRaises(WebhookError):
                verify_delivery(self.endpoint(), dict(headers, **{"content-type": content_type}), raw)
        large, headers = self.github(b"x" * 262145)
        with self.assertRaises(WebhookError): verify_delivery(self.endpoint(), headers, large)

    def test_unsupported_authenticated_event_is_quarantined(self):
        raw, headers = self.github(); headers["x-github-event"] = "unknown"
        result = accept_delivery(self.ledger, self.endpoint(), headers, raw)
        self.assertTrue(result["quarantined"])
        self.assertEqual(self.ledger.inspect(result["event_id"])["last_error"], "unsupported_event_type")

    def test_altered_unsigned_delivery_header_cannot_replay_body(self):
        raw, headers = self.github()
        accept_delivery(self.ledger, self.endpoint(), headers, raw)
        headers["x-github-delivery"] = str(uuid4())
        with self.assertRaises(ValueError): accept_delivery(self.ledger, self.endpoint(), headers, raw)
        self.assertEqual(len(self.ledger.list_events()), 1)

    def test_signed_relay_valid_stale_future_invalid_and_replayed(self):
        endpoint = self.endpoint("signed_relay").model_copy(update={"allowed_event_types": ["fixture.event"]})
        raw = b'{"event_type":"fixture.event","payload":{"id":"one"}}'
        now = datetime.now(timezone.utc)
        for delta, valid in ((0, True), (-301, False), (301, False)):
            stamp, delivery = str(int((now + timedelta(seconds=delta)).timestamp())), "relay-one"
            headers = {"content-type": "application/json", "x-optibrain-timestamp": stamp, "x-optibrain-delivery": delivery,
                       "x-optibrain-signature": hmac.new(SECRET.encode(), stamp.encode() + b"." + delivery.encode() + b"." + raw, hashlib.sha256).hexdigest()}
            with self.subTest(delta=delta):
                if valid:
                    verify_delivery(endpoint, headers, raw, now=now)
                    self.assertTrue(accept_delivery(self.ledger, endpoint, headers, raw)["accepted"])
                    self.assertTrue(accept_delivery(self.ledger, endpoint, headers, raw)["duplicate"])
                    headers["x-optibrain-delivery"] = "tampered"
                    with self.assertRaises(WebhookError): verify_delivery(endpoint, headers, raw, now=now)
                else:
                    with self.assertRaises(WebhookError): verify_delivery(endpoint, headers, raw, now=now)

    def test_zoho_channel_token_timestamp_and_secret_removal(self):
        endpoint = self.endpoint("zoho_crm", channel_id="123").model_copy(update={"allowed_event_types": ["zoho.crm.Leads.insert"]})
        now = datetime.now(timezone.utc)
        data = {"token": SECRET, "channel_id": "123", "server_time": int(now.timestamp() * 1000),
                "module": "Leads", "operation": "insert", "ids": ["456"], "query_params": {"authorization": "neverstore"}}
        headers = {"content-type": "application/json"}
        result = accept_delivery(self.ledger, endpoint, headers, json.dumps(data).encode())
        persisted = json.dumps(self.ledger.inspect(result["event_id"]))
        self.assertNotIn(SECRET, persisted); self.assertNotIn("neverstore", persisted)
        for field, value in (("token", "wrong"), ("channel_id", "wrong"), ("server_time", 0), ("ids", [123])):
            with self.subTest(field=field), self.assertRaises(WebhookError):
                verify_delivery(endpoint, headers, json.dumps(dict(data, **{field: value})).encode(), now=now)

    def test_google_notification_requires_pinned_unexpired_channel(self):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        headers = {"x-goog-channel-token": SECRET, "x-goog-channel-id": "channel", "x-goog-resource-id": "resource",
                   "x-goog-message-number": "10", "x-goog-resource-state": "exists"}
        for provider in ("google_calendar", "google_drive"):
            with self.subTest(provider=provider):
                endpoint = self.endpoint(provider, channel_id="channel", resource_id="resource", expires_at=expiry)
                event, _ = verify_delivery(endpoint, headers, b"")
                self.assertEqual(event.provider_event_id, "channel:10")
                for field in ("x-goog-channel-token", "x-goog-channel-id", "x-goog-resource-id", "x-goog-message-number"):
                    with self.subTest(field=field), self.assertRaises(WebhookError):
                        verify_delivery(endpoint, dict(headers, **{field: "wrong"}), b"")
                with self.assertRaises(WebhookError):
                    verify_delivery(endpoint.model_copy(update={"expires_at": "2000-01-01T00:00:00Z"}), headers, b"")

    def test_cloudflare_header_auth_and_content_dedupe(self):
        endpoint = self.endpoint("cloudflare").model_copy(update={"allowed_event_types": ["cloudflare.notification"]})
        headers = {"content-type": "application/json", "cf-webhook-auth": SECRET}
        one = accept_delivery(self.ledger, endpoint, headers, b'{"text":"fixture"}')
        two = accept_delivery(self.ledger, endpoint, headers, b'{"text":"fixture"}')
        self.assertTrue(one["accepted"]); self.assertTrue(two["duplicate"])
        with self.assertRaises(WebhookError): verify_delivery(endpoint, {}, b'{}')

    def test_google_push_nudges_incremental_sync_and_respects_backoff(self):
        sync = DeltaSync(self.store)
        sync.initialize("google.calendar", "account-one", "calendar", cursor="existing")
        endpoint = self.endpoint("google_calendar", channel_id="channel", resource_id="resource", sync_stream="calendar",
                                 expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        endpoint = endpoint.model_copy(update={"allowed_event_types": ["google.calendar.notification"]})
        headers = {"x-goog-channel-token": SECRET, "x-goog-channel-id": "channel", "x-goog-resource-id": "resource",
                   "x-goog-message-number": "10", "x-goog-resource-state": "exists"}
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_sync_checkpoints SET status='backoff',next_attempt_at=9999999999999999")
        accept_delivery(self.ledger, endpoint, headers, b"")
        state = sync.snapshot("google.calendar", "account-one", "calendar")
        self.assertEqual(state["notifications"], 1)
        self.assertEqual(state["next_attempt_at"], 9999999999999999)
        with self.store._connect() as conn: conn.execute("UPDATE automation_sync_checkpoints SET status='idle'")
        headers["x-goog-message-number"] = "11"
        accept_delivery(self.ledger, endpoint, headers, b"")
        self.assertEqual(sync.snapshot("google.calendar", "account-one", "calendar")["next_attempt_at"], 0)
        accept_delivery(self.ledger, endpoint, headers, b"")
        self.assertEqual(sync.snapshot("google.calendar", "account-one", "calendar")["notifications"], 2)

    def test_google_hint_does_not_route_as_a_delta_resource_change(self):
        self.store.upsert_workflow(WorkflowDefinition.model_validate({"id": "google.resource-change",
            "name": "Resource change fixture", "trigger": {"event_types": ["google.calendar.changed"]},
            "steps": [{"id": "internal", "action": "core.noop"}]}))
        endpoint = self.endpoint("google_calendar", channel_id="channel", resource_id="resource",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()).model_copy(
            update={"allowed_event_types": ["google.calendar.notification"]})
        headers = {"x-goog-channel-token": SECRET, "x-goog-channel-id": "channel", "x-goog-resource-id": "resource",
                   "x-goog-message-number": "10", "x-goog-resource-state": "exists"}
        hint = accept_delivery(self.ledger, endpoint, headers, b"")
        self.ledger.process(hint["event_id"])
        self.assertEqual(self.store.recent_runs(), [])
        change = AutomationEvent(event_type="google.calendar.changed", source="google.calendar",
                                 source_account="account-one", provider_event_id="resource-version-one")
        self.ledger.capture(change)
        self.ledger.process(change.event_id)
        self.assertEqual(len(self.store.recent_runs()), 1)


class EventApiTests(unittest.TestCase):
    endpoint = WebhookTests.endpoint
    github = WebhookTests.github
    def setUp(self):
        WebhookTests.setUp(self)
        from workflow import api
        self.api = api
        self.client = TestClient(api.app)
        store_patch = patch.object(api, "automation_store", self.store); store_patch.start(); self.addCleanup(store_patch.stop)
        self.key_name = api.settings.api.api_key_env
        auth_patch = patch.dict(os.environ, {self.key_name: "fixture-api-key"}); auth_patch.start(); self.addCleanup(auth_patch.stop)
        self.auth = {"X-API-Key": "fixture-api-key"}

    def test_all_event_inspection_controls_fail_closed(self):
        routes = ["/v1/automation/event-health", "/v1/automation/usage", "/v1/automation/events", "/v1/automation/events/missing", "/v1/automation/sync/checkpoints"]
        for value in (None, "", " "):
            with patch.dict(os.environ, {}, clear=False):
                if value is None: os.environ.pop(self.key_name, None)
                else: os.environ[self.key_name] = value
                for route in routes:
                    with self.subTest(route=route, key=value):
                        self.assertEqual(self.client.get(route).status_code, 503)
                self.assertEqual(self.client.post("/v1/automation/events/missing/replay", json={"request_key": "fixture-request", "reason": "Fixture review reason"}).status_code, 503)
        for route in routes:
            with self.subTest(route=route): self.assertEqual(self.client.get(route).status_code, 401)

    def test_webhook_api_body_size_method_and_security(self):
        endpoint = self.endpoint()
        raw, headers = self.github()
        with patch("workflow.automation.event_api.load_endpoints", return_value={"fixture": endpoint}):
            route = "/v1/automation/webhooks/fixture"
            self.assertEqual(self.client.get(route).status_code, 405)
            accepted = self.client.post(route, content=raw, headers=headers)
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(self.client.post(route, content=raw, headers=headers).json()["duplicate"])
            self.assertEqual(self.client.post(route, content=raw, headers=dict(headers, **{"x-hub-signature-256": "wrong"})).status_code, 401)
            self.assertEqual(self.client.post(route, content=b"x" * 262145, headers=headers).status_code, 413)
            self.assertEqual(self.client.post(route, content=b"{", headers=self.github(b"{")[1]).status_code, 400)
            self.assertEqual(len(self.ledger.list_events()), 1)
        usage = self.client.get("/v1/automation/usage", headers=self.auth).json()["usage"]
        self.assertTrue(any(item["metric"] == "webhook_verification_failures" for item in usage))

    def test_replay_one_range_and_time_window_are_bounded_and_audited(self):
        ids = [self.ledger.capture(AutomationEvent(event_type="fixture", source="fixture", dedupe_identity=str(i)))[1] for i in range(6)]
        self.ledger.process_pending()
        reason = {"request_key": "one-request", "reason": "Fixture operator review"}
        self.assertEqual(self.client.post(f"/v1/automation/events/{ids[0]}/replay", json=reason, headers=self.auth).status_code, 200)
        body = dict(reason, request_key="range-request", after="0", through="f" * 32, limit=2)
        response = self.client.post("/v1/automation/events/replay-batch", json=body, headers=self.auth)
        self.assertEqual(response.status_code, 200); self.assertLessEqual(response.json()["count"], 2)
        body = dict(reason, request_key="window-request", start="2000-01-01T00:00:00Z", end="2099-01-01T00:00:00Z", limit=3)
        response = self.client.post("/v1/automation/events/replay-batch", json=body, headers=self.auth)
        self.assertEqual(response.status_code, 200); self.assertLessEqual(response.json()["count"], 3)
        self.assertEqual(self.client.post("/v1/automation/events/replay-batch", json=reason, headers=self.auth).status_code, 422)
        self.assertEqual(self.client.get("/v1/automation/events?limit=101", headers=self.auth).status_code, 422)

    def test_existing_event_ingest_is_now_fail_closed(self):
        with patch.dict(os.environ, {self.key_name: ""}):
            self.assertEqual(self.client.post("/v1/automation/events", json={"event_type": "fixture", "source": "fixture"}).status_code, 503)

    def test_repeated_security_headers_are_rejected_before_intake(self):
        raw, headers = self.github()
        names = ("content-type", "x-hub-signature-256", "x-github-delivery", "x-github-event",
                 "x-goog-channel-token", "x-goog-channel-id", "x-goog-resource-id",
                 "x-goog-message-number", "x-goog-resource-state", "cf-webhook-auth",
                 "x-optibrain-signature", "x-optibrain-timestamp", "x-optibrain-delivery")
        with patch("workflow.automation.event_api.load_endpoints", return_value={"fixture": self.endpoint()}):
            for name in names:
                repeated = [(key, value) for key, value in headers.items() if key != name]
                repeated.extend([(name, headers.get(name, "first")), (name, "second")])
                with self.subTest(header=name):
                    self.assertEqual(self.client.post("/v1/automation/webhooks/fixture", content=raw,
                                                      headers=repeated).status_code, 400)
        self.assertEqual(self.ledger.list_events(), [])

    def test_request_read_deadline_rejects_slow_delivery(self):
        from workflow.automation.event_body_limit import EventBodyLimit
        messages = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        async def downstream(scope, receive, send):
            self.fail("expired request reached application")
        with patch("workflow.automation.event_body_limit.time") as clock:
            clock.monotonic.side_effect = [0, 11]
            asyncio.run(EventBodyLimit(downstream)({"type": "http", "method": "POST",
                      "path": "/v1/automation/events"}, receive, send))
        self.assertEqual(messages[0]["status"], 408)

    def test_event_json_allocation_is_bounded_before_validation(self):
        response = self.client.post("/v1/automation/events", content=b"x" * 1048577, headers={**self.auth, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
