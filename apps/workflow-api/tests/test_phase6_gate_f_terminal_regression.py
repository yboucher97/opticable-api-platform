from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.operator_outbound_api import install_operator_outbound_routes


ORIGIN = "https://approvals.opticable.ca"
APPROVAL_ID = "a" * 32


class FakeVerifier:
    def verify(self, token):
        if token != "human-token":
            raise ValueError("missing identity")
        return SimpleNamespace(
            subject="owner-123",
            email="owner@opticable.ca",
            actor="human:owner-123",
        )


class FakeLedger:
    def __init__(self, state):
        self.state = state

    def inspect(self, approval_id):
        if approval_id != APPROVAL_ID:
            return None
        return self.state


class FakeStore:
    def audit(self, **kwargs):
        raise AssertionError("terminal-state inspection must not write audit records")


class ForbiddenResolver:
    def resolve(self, review_event_id):
        raise AssertionError("terminal-state inspection must not resolve customer data")

    def resolve_approval_source(self, **kwargs):
        raise AssertionError("terminal approval must be blocked before provider/source reads")


def approval_metadata():
    return {
        "approval_id": APPROVAL_ID,
        "actor": "human:owner-123",
        "approved_at": "2026-09-28T18:00:00+00:00",
        "expires_at": "2026-09-28T19:00:00+00:00",
        "action_type": "send_new_email",
        "source_type": "lead",
        "source_id": "123",
        "source_version": "2026-09-28T18:00:00+00:00",
        "account_id": "456",
        "message_id": None,
        "recipient": "client@example.test",
        "from_address": "info@opticable.ca",
        "subject_hash": "b" * 64,
        "content_hash": "c" * 64,
        "policy_version": "phase6-sales-v1",
    }


class GateFTerminalApprovalRegressionTests(unittest.TestCase):
    def client(self, state):
        app = FastAPI()
        install_operator_outbound_routes(
            app,
            verifier=FakeVerifier(),
            resolver=ForbiddenResolver(),
            ledger=FakeLedger(state),
            store=FakeStore(),
            allowed_origin=ORIGIN,
        )
        return TestClient(app)

    def headers(self):
        return {
            "Cf-Access-Jwt-Assertion": "human-token",
            "Origin": ORIGIN,
            "Content-Type": "application/json",
            "Sec-Fetch-Site": "same-origin",
        }

    def test_consumed_terminal_metadata_is_inspectable_and_not_reusable(self):
        metadata = approval_metadata()
        metadata.update({"provider_operation_id": "9001", "request_id_hash": "d" * 64})
        client = self.client({"state": "consumed", "at": "2026-09-28T18:10:00+00:00", "approval": metadata})

        inspected = client.get(
            f"/v1/operator/outbound/approvals/{APPROVAL_ID}",
            headers={"Cf-Access-Jwt-Assertion": "human-token"},
        )
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(inspected.json()["state"], "consumed")
        self.assertNotIn("provider_operation_id", inspected.json()["approval"])

        consumed = client.post(
            f"/v1/operator/outbound/approvals/{APPROVAL_ID}/consume",
            headers=self.headers(),
            json={},
        )
        self.assertEqual(consumed.status_code, 409)

    def test_manual_terminal_metadata_is_inspectable_and_not_reusable(self):
        metadata = approval_metadata()
        metadata.update({"error": "preflight_changed"})
        client = self.client({"state": "manual", "at": "2026-09-28T18:10:00+00:00", "approval": metadata})

        inspected = client.get(
            f"/v1/operator/outbound/approvals/{APPROVAL_ID}",
            headers={"Cf-Access-Jwt-Assertion": "human-token"},
        )
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(inspected.json()["state"], "manual")
        self.assertNotIn("error", inspected.json()["approval"])

        consumed = client.post(
            f"/v1/operator/outbound/approvals/{APPROVAL_ID}/consume",
            headers=self.headers(),
            json={},
        )
        self.assertEqual(consumed.status_code, 409)


if __name__ == "__main__":
    unittest.main()
