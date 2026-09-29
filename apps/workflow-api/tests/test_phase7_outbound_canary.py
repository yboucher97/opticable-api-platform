"""Exact-approval outbound canary mode with fake Mail only."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import WorkflowStep
from workflow.automation.outbound_approval import OutboundApprovalLedger
from workflow.automation.providers.outbound_mail import register_outbound_mail_action
from workflow.automation.store import AutomationStore


class FakeMail:
    def __init__(self):
        self.calls = []

    def request(self, service, method, path, **kwargs):
        if (service, method, path) != ("mail", "POST", "/api/accounts/456/messages"):
            raise AssertionError("Unreviewed provider operation")
        self.calls.append(kwargs)
        return {"ok": True, "status": 200, "data": {
            "status": {"code": 200}, "data": {"messageId": "9001"}}}


class OutboundCanaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="phase7-outbound-canary-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.store = AutomationStore(root / "automation.db")
        self.ledger = OutboundApprovalLedger(self.store)
        self.mail = FakeMail()
        self.engine = AutomationEngine(self.store, root / "workflows")
        register_outbound_mail_action(self.engine, self.mail, self.store)
        now = datetime.now(timezone.utc)
        self.content = "Thank you for your inquiry."
        self.subject = "Your inquiry with Opticable"
        self.approval = self.ledger.issue(
            actor="human:owner", action_type="send_new_email", source_type="lead",
            source_id="lead:123:reviewed", source_version="2026-09-29T18:00:00+00:00",
            account_id="456", recipient="client@example.net", from_address="sales@opticable.ca",
            subject=self.subject, content=self.content,
            expires_at=(now + timedelta(minutes=30)).isoformat(), now=now)

    def send(self, approval):
        value = {"approval_id": approval.approval_id, "action_type": approval.action_type,
                 "source_type": approval.source_type, "source_id": approval.source_id,
                 "source_version": approval.source_version, "mailbox_account_id": approval.account_id,
                 "message_id": None, "from_address": approval.from_address,
                 "to_address": approval.recipient, "subject": self.subject,
                 "content": self.content, "mail_format": "plaintext"}
        return self.engine._actions["lifecycle.mail_send_approved_v2"](
            {"event": {}}, WorkflowStep(id="send", action="lifecycle.mail_send_approved_v2",
                                        inputs={"send": value}))

    def test_exact_pinned_approval_only_and_single_use(self):
        with patch.dict(os.environ, {"OPTIBRAIN_OUTBOUND_SENDS": "phase7-single-canary-v1",
                                     "OPTIBRAIN_OUTBOUND_CANARY_APPROVAL_ID": self.approval.approval_id}):
            self.assertTrue(self.send(self.approval)["sent"])
            with self.assertRaises(ValueError):
                self.send(self.approval)
        self.assertEqual(len(self.mail.calls), 1)

    def test_missing_or_different_pin_preserves_issued_state_and_zero_sends(self):
        for pin in ("", "f" * 32):
            with self.subTest(pin=pin), patch.dict(os.environ, {
                    "OPTIBRAIN_OUTBOUND_SENDS": "phase7-single-canary-v1",
                    "OPTIBRAIN_OUTBOUND_CANARY_APPROVAL_ID": pin}):
                self.assertEqual(self.send(self.approval)["reason"], "observe")
        self.assertEqual(self.ledger.inspect(self.approval.approval_id)["state"], "issued")
        self.assertEqual(self.mail.calls, [])

    def test_disabled_mode_and_unpinned_other_approval_never_send(self):
        now = datetime.now(timezone.utc)
        other = self.ledger.issue(
            actor="human:owner", action_type="send_new_email", source_type="lead",
            source_id="lead:999:reviewed", source_version="2026-09-29T18:00:00+00:00",
            account_id="456", recipient="client@example.net", from_address="sales@opticable.ca",
            subject=self.subject, content=self.content,
            expires_at=(now + timedelta(minutes=30)).isoformat(), now=now)
        with patch.dict(os.environ, {"OPTIBRAIN_OUTBOUND_SENDS": "phase7-single-canary-v1",
                                     "OPTIBRAIN_OUTBOUND_CANARY_APPROVAL_ID": self.approval.approval_id}):
            self.assertEqual(self.send(other)["reason"], "observe")
        with patch.dict(os.environ, {"OPTIBRAIN_OUTBOUND_SENDS": ""}):
            self.assertEqual(self.send(self.approval)["reason"], "observe")
        self.assertEqual(self.mail.calls, [])
