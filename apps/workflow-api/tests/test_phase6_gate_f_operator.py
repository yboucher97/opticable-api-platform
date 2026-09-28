from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
import jwt

from workflow.automation.event_schema import digest
from workflow.automation.events import EventLedger
from workflow.automation.models import AutomationEvent
from workflow.automation.operator_outbound import AuthoritativeOutboundResolver
from workflow.automation.outbound_approval import OutboundApprovalLedger
from workflow.automation.sales_decision import build_sales_decision
from workflow.automation.store import AutomationStore
from workflow.operator_access import AccessIdentityVerifier
from workflow.operator_outbound_api import install_operator_outbound_routes


TEAM = "https://opticable.cloudflareaccess.com"
AUD = "a" * 64
ORIGIN = "https://approvals.opticable.ca"


class FakeProvider:
    def __init__(self):
        self.lead = {
            "id": "123",
            "Email": "client@example.test",
            "Email_Opt_Out": False,
            "Converted__s": False,
            "Lead_Status": "Not Contacted",
            "Modified_Time": "2026-09-28T18:00:00Z",
            "Created_Time": "2026-09-27T18:00:00Z",
            "Language": "fr",
            "City": "Montreal",
            "State": "QC",
        }
        self.details_sender = "client@example.test"
        self.internet_id = "<source@example.test>"
        self.calls = []

    def request(self, service, method, path, **kwargs):
        self.calls.append((service, method, path, copy.deepcopy(kwargs)))
        if (service, method, path) == ("zohoapis", "GET", "/crm/v8/Leads/123"):
            return {"ok": True, "status": 200, "data": {"data": [copy.deepcopy(self.lead)]}}
        if service == "mail" and method == "GET" and path.endswith("/details"):
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "status": {"code": 200, "description": "success"},
                    "data": {
                        "messageId": "888",
                        "folderId": "999",
                        "fromAddress": self.details_sender,
                        "subject": "Need cabling",
                    },
                },
            }
        if service == "mail" and method == "GET" and path.endswith("/header"):
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "status": {"code": 200, "description": "success"},
                    "data": {
                        "messageId": "888",
                        "headerContent": {"Message-Id": [self.internet_id]},
                    },
                },
            }
        raise AssertionError(f"Forbidden provider operation: {service} {method} {path}")


class GateFOperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.provider = FakeProvider()
        self.ledger = EventLedger(self.store)
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()
        self.subject = "owner-123"
        self.email = "owner@opticable.ca"
        self.verifier = AccessIdentityVerifier(
            team_domain=TEAM,
            audience=AUD,
            allowed_subjects={self.subject},
            key_resolver=lambda token: self.public_key,
        )
        self.resolver = AuthoritativeOutboundResolver(
            self.provider,
            self.store,
            account_id="456",
            from_address="info@opticable.ca",
        )
        self.review_event_id = self._capture_review()
        self.outbound_ledger = OutboundApprovalLedger(self.store)
        self.callback_calls = []

    def token(self, *, sub=None, email=None, aud=AUD, issuer=TEAM, expired=False, key=None, include_nbf=True):
        now = datetime.now(timezone.utc)
        claims = {
            "aud": [aud],
            "email": self.email if email is None else email,
            "exp": int((now + (-timedelta(minutes=2) if expired else timedelta(minutes=10))).timestamp()),
            "iat": int((now - timedelta(seconds=5)).timestamp()),
            "iss": issuer,
            "type": "app",
            "sub": self.subject if sub is None else sub,
        }
        if include_nbf:
            claims["nbf"] = int((now - timedelta(seconds=5)).timestamp())
        if claims.get("email") is None:
            claims.pop("email", None)
        return jwt.encode(
            claims,
            key or self.private_key,
            algorithm="RS256",
            headers={"kid": "fixture-key", "typ": "JWT"},
        )

    def headers(self, token=None, *, origin=None):
        value = {"Cf-Access-Jwt-Assertion": token or self.token()}
        if origin is not None:
            value.update({"Origin": origin, "Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"})
        return value

    def _capture_review(self, *, message=False):
        extra = {}
        if message:
            message_event_id = uuid4().hex
            message = AutomationEvent(
                event_id=message_event_id,
                event_type="customer.lifecycle.email.received",
                source="zoho-mail-poller",
                source_account="456",
                payload={
                    "mailbox_account_id": "456",
                    "mailbox_address": "info@opticable.ca",
                    "sender_email": "client@example.test",
                    "message_id": "888",
                    "folder_id": "999",
                    "subject": "Need cabling",
                    "body": "Private inbound body",
                },
            )
            self.ledger.capture(message)
            captured = self.ledger.inspect(message_event_id)
            extra = {
                "message_event_id": message_event_id,
                "message_content_hash": captured["content_hash"],
            }
        decision = build_sales_decision(
            self.provider.lead,
            now=datetime(2026, 9, 28, 18, 5, tzinfo=timezone.utc),
        )
        review_event_id = uuid4().hex
        review = AutomationEvent(
            event_id=review_event_id,
            event_type="opticable.crm.lead.reviewed",
            source="crm-lead-observer",
            source_account="fixture-org",
            payload={
                "lead_id": "123",
                "version": decision.version,
                "sales_decision": decision.model_dump(),
                **extra,
            },
        )
        self.ledger.capture(review)
        return review_event_id

    def app(self, *, verifier=None, resolver=None, callback=None, clock=None):
        app = FastAPI()
        install_operator_outbound_routes(
            app,
            verifier=verifier or self.verifier,
            resolver=resolver or self.resolver,
            ledger=self.outbound_ledger,
            store=self.store,
            allowed_origin=ORIGIN,
            consume_callback=callback,
            clock=clock,
        )
        return TestClient(app)

    def preview(self, client=None, review=None, token=None):
        client = client or self.app()
        return client.get(
            f"/v1/operator/outbound/candidates/{review or self.review_event_id}",
            headers=self.headers(token),
        )

    def issue(self, client, candidate, *, token=None, extra=None):
        body = {
            "review_event_id": candidate["review_event_id"],
            "candidate_hash": candidate["candidate_hash"],
            "expires_in_minutes": 30,
        }
        body.update(extra or {})
        return client.post(
            "/v1/operator/outbound/approvals",
            headers=self.headers(token, origin=ORIGIN),
            json=body,
        )

    def test_valid_access_identity_preview_is_read_only(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["operator"]["subject"], self.subject)
        self.assertEqual(body["candidate"]["recipient"], "client@example.test")
        self.assertEqual(body["candidate"]["action_type"], "send_new_email")
        self.assertFalse(body["send_enabled"])
        self.assertTrue(all(call[1] == "GET" for call in self.provider.calls))

    def test_auth_failure_happens_before_customer_data_read(self):
        client = self.app()
        response = client.get(f"/v1/operator/outbound/candidates/{self.review_event_id}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.provider.calls, [])
        self.assertNotIn("client@example.test", response.text)

    def test_wrong_signature_issuer_audience_expiry_and_missing_nbf_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tokens = [
            self.token(key=other),
            self.token(issuer="https://wrong.cloudflareaccess.com"),
            self.token(aud="b" * 64),
            self.token(expired=True),
            self.token(include_nbf=False),
        ]
        for token in tokens:
            with self.subTest(token=token[-16:]):
                self.provider.calls.clear()
                self.assertEqual(self.preview(token=token).status_code, 401)
                self.assertEqual(self.provider.calls, [])

    def test_service_token_shape_rejected(self):
        token = self.token(sub="", email=None)
        self.assertEqual(self.preview(token=token).status_code, 401)
        self.assertEqual(self.provider.calls, [])

    def test_authenticated_but_unauthorized_human_rejected(self):
        token = self.token(sub="other-human", email="other@opticable.ca")
        response = self.preview(token=token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.provider.calls, [])

    def test_request_cannot_override_actor(self):
        client = self.app()
        candidate = self.preview(client).json()["candidate"]
        response = self.issue(client, candidate, extra={"actor": "human:attacker"})
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.outbound_ledger.inspect("0" * 32))

    def test_issue_derives_human_actor_and_stores_no_jwt(self):
        client = self.app()
        candidate = self.preview(client).json()["candidate"]
        token = self.token()
        response = self.issue(client, candidate, token=token)
        self.assertEqual(response.status_code, 201)
        approval_id = response.json()["approval_id"]
        state = self.outbound_ledger.inspect(approval_id)
        self.assertEqual(state["approval"]["actor"], "human:" + self.subject)
        audit = json.dumps(self.store.recent_audit(limit=100))
        self.assertNotIn(token, audit)
        self.assertNotIn(candidate["content"], audit)
        self.assertNotIn(candidate["subject"], audit)

    def test_candidate_hash_prevents_source_change_between_preview_and_issue(self):
        client = self.app()
        candidate = self.preview(client).json()["candidate"]
        self.provider.lead["Email"] = "changed@example.test"
        response = self.issue(client, candidate)
        self.assertEqual(response.status_code, 409)

    def test_opt_out_and_version_drift_block_issue(self):
        for changes in (
            {"Email_Opt_Out": True},
            {"Email_Opt_Out": None},
            {"Modified_Time": "2026-09-28T18:01:00Z"},
            {"Converted__s": True},
            {"Lead_Status": "Junk Lead"},
        ):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.provider.lead)
                client = self.app()
                candidate = self.preview(client).json()["candidate"]
                self.provider.lead.update(changes)
                self.assertEqual(self.issue(client, candidate).status_code, 409)
                self.provider.lead = original

    def test_cross_origin_and_wrong_content_type_rejected(self):
        client = self.app()
        candidate = self.preview(client).json()["candidate"]
        body = {"review_event_id": candidate["review_event_id"], "candidate_hash": candidate["candidate_hash"]}
        cross = client.post(
            "/v1/operator/outbound/approvals",
            headers={**self.headers(), "Origin": "https://evil.example", "Content-Type": "application/json"},
            json=body,
        )
        self.assertEqual(cross.status_code, 403)
        wrong = client.post(
            "/v1/operator/outbound/approvals",
            headers={**self.headers(), "Origin": ORIGIN, "Content-Type": "text/plain"},
            content=json.dumps(body),
        )
        self.assertEqual(wrong.status_code, 415)

    def test_inspection_is_bound_to_issuing_operator(self):
        client = self.app()
        candidate = self.preview(client).json()["candidate"]
        approval_id = self.issue(client, candidate).json()["approval_id"]
        other_verifier = AccessIdentityVerifier(
            team_domain=TEAM,
            audience=AUD,
            allowed_subjects={"other-human"},
            key_resolver=lambda token: self.public_key,
        )
        other_client = self.app(verifier=other_verifier)
        token = self.token(sub="other-human", email="other@opticable.ca")
        response = other_client.get(
            f"/v1/operator/outbound/approvals/{approval_id}",
            headers=self.headers(token),
        )
        self.assertEqual(response.status_code, 403)

    def test_consume_without_registration_revalidates_then_blocks_send(self):
        client = self.app()
        candidate = self.preview(client).json()["candidate"]
        approval_id = self.issue(client, candidate).json()["approval_id"]
        calls_before = len(self.provider.calls)
        response = client.post(
            f"/v1/operator/outbound/approvals/{approval_id}/consume",
            headers=self.headers(origin=ORIGIN),
            json={},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "outbound_send_not_registered")
        self.assertGreater(len(self.provider.calls), calls_before)
        self.assertTrue(all(call[1] == "GET" for call in self.provider.calls))
        self.assertEqual(self.outbound_ledger.inspect(approval_id)["state"], "issued")

    def test_consume_blocks_contactability_or_content_drift_before_callback(self):
        def callback(value):
            self.callback_calls.append(value)
            return {"sent": True}

        client = self.app(callback=callback)
        candidate = self.preview(client).json()["candidate"]
        approval_id = self.issue(client, candidate).json()["approval_id"]
        self.provider.lead["Email_Opt_Out"] = True
        response = client.post(
            f"/v1/operator/outbound/approvals/{approval_id}/consume",
            headers=self.headers(origin=ORIGIN),
            json={},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.callback_calls, [])

        self.provider.lead["Email_Opt_Out"] = False
        with patch.dict("workflow.automation.providers.sales_drafts.TEMPLATES", {"fr": ("Changed", "Changed body")}):
            response = client.post(
                f"/v1/operator/outbound/approvals/{approval_id}/consume",
                headers=self.headers(origin=ORIGIN),
                json={},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.callback_calls, [])

    def test_authoritative_consume_callback_receives_server_reconstructed_request(self):
        def callback(value):
            self.callback_calls.append(copy.deepcopy(value))
            return {"sent": False, "reason": "fake-only"}

        client = self.app(callback=callback)
        candidate = self.preview(client).json()["candidate"]
        approval_id = self.issue(client, candidate).json()["approval_id"]
        response = client.post(
            f"/v1/operator/outbound/approvals/{approval_id}/consume",
            headers=self.headers(origin=ORIGIN),
            json={},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.callback_calls), 1)
        request = self.callback_calls[0]
        self.assertEqual(request["approval_id"], approval_id)
        self.assertEqual(request["to_address"], "client@example.test")
        self.assertEqual(request["content"], candidate["content"])

    def test_message_bound_reply_requires_live_details_and_internet_header(self):
        self.provider.calls.clear()
        review = self._capture_review(message=True)
        candidate = self.resolver.resolve(review)
        self.assertEqual(candidate.action_type, "reply_email")
        self.assertEqual(candidate.source_type, "message")
        self.assertEqual(candidate.message_id, "888")
        paths = [call[2] for call in self.provider.calls]
        self.assertTrue(any(path.endswith("/details") for path in paths))
        self.assertTrue(any(path.endswith("/header") for path in paths))

    def test_message_sender_or_header_drift_blocks(self):
        review = self._capture_review(message=True)
        self.provider.details_sender = "attacker@example.test"
        with self.assertRaises(ValueError):
            self.resolver.resolve(review)
        self.provider.details_sender = "client@example.test"
        self.provider.internet_id = "missing-brackets"
        with self.assertRaises(ValueError):
            self.resolver.resolve(review)

    def test_draft_source_is_not_trusted_from_opaque_id(self):
        with self.assertRaisesRegex(ValueError, "draft source readback"):
            self.resolver.resolve_approval_source(source_type="draft", source_id="draft:123")

    def test_expired_approval_is_blocked_at_consume_boundary(self):
        current = [datetime.now(timezone.utc)]
        client = self.app(clock=lambda: current[0])
        candidate = self.preview(client).json()["candidate"]
        approval_id = self.issue(client, candidate).json()["approval_id"]
        current[0] += timedelta(hours=2)
        response = client.post(
            f"/v1/operator/outbound/approvals/{approval_id}/consume",
            headers=self.headers(origin=ORIGIN),
            json={},
        )
        self.assertEqual(response.status_code, 409)

    def test_gate_f_modules_are_not_registered_by_production_startup(self):
        root = Path(__file__).resolve().parents[1]
        api = (root / "workflow/api.py").read_text()
        self.assertNotIn("operator_outbound_api", api)
        self.assertNotIn("register_outbound_mail_action", api)
        self.assertNotIn("install_operator_outbound_routes", api)

    def test_legacy_boolean_workflow_remains_disabled_and_single_attempt(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "config/automation/workflows/customer-lifecycle-approved-email-reply.yaml").read_text()
        self.assertIn("enabled: false", text)
        self.assertIn("max_attempts: 1", text)

    def test_gate_f_path_contains_no_books_or_crm_mutation_routes(self):
        root = Path(__file__).resolve().parents[1]
        paths = [
            root / "workflow/operator_access.py",
            root / "workflow/operator_outbound_api.py",
            root / "workflow/automation/operator_outbound.py",
        ]
        combined = "\n".join(path.read_text() for path in paths)
        for forbidden in ("/books/", '"POST", "/crm/', '"PUT", "/crm/', '"DELETE", "/crm/'):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
