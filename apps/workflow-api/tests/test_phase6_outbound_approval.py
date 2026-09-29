from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import yaml

from workflow.automation.engine import AutomationEngine
from workflow.automation.event_schema import digest
from workflow.automation.models import AutomationEvent, WorkflowDefinition, WorkflowStep
from workflow.automation.outbound_approval import (
    BINDING_FIELDS, CATEGORY, OutboundApproval, OutboundApprovalLedger, POLICY_VERSION,
)
from workflow.automation.providers.outbound_mail import register_outbound_mail_action
from workflow.automation.providers.lifecycle_mailbox import register_lifecycle_mailbox_actions
from workflow.automation.store import AutomationStore
from workflow.zoho_gateway import ZohoWriteUnconfirmedError

APP = Path(__file__).resolve().parents[1]
ACTION = "lifecycle.mail_send_approved_v2"


class MailFake:
    def __init__(self):
        self.calls = []
        self.error = None
        self.response = {"ok": True, "status": 200, "data": {
            "status": {"code": 200}, "data": {"messageId": "9001"}}, "request_id": "fixture-request"}
        self.on_call = None

    def request(self, service, method, path, **kwargs):
        if service != "mail" or method != "POST" or path not in {
                "/api/accounts/456/messages", "/api/accounts/456/messages/789"}:
            raise AssertionError("Outbound path escaped Mail send/reply allowlist")
        if set(kwargs["body"]) - {"fromAddress", "toAddress", "subject", "content", "mailFormat", "action"}:
            raise AssertionError("Unexpected outbound payload fields")
        self.calls.append((service, method, path, copy.deepcopy(kwargs)))
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        return self.response


class OutboundApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = AutomationStore(self.root / "automation.db")
        self.fake = MailFake()
        self.restart()
        self.clock = datetime.now(timezone.utc)
        self.kwargs = dict(actor="human:reviewer-42", action_type="send_new_email",
            source_type="lead", source_id="123", source_version="2026-09-28T18:00:00+00:00",
            account_id="456", recipient="Client@example.test", from_address="info@opticable.ca",
            subject="Private approved subject", content="Private approved body.\nExact whitespace. ",
            now=self.clock, expires_at=(self.clock + timedelta(hours=1)).isoformat())
        self.env = patch.dict(os.environ, {"OPTIBRAIN_OUTBOUND_SENDS": POLICY_VERSION})
        self.env.start()
        self.addCleanup(self.env.stop)

    def restart(self):
        self.store = AutomationStore(self.store.db_path)
        self.ledger = OutboundApprovalLedger(self.store)
        self.engine = AutomationEngine(self.store, self.root / "workflows")
        register_outbound_mail_action(self.engine, self.fake, self.store)

    def issue(self, **changes):
        return self.ledger.issue(**{**self.kwargs, **changes})

    def request(self, approval, **changes):
        return {"approval_id": approval.approval_id, "action_type": approval.action_type,
            "source_type": approval.source_type, "source_id": approval.source_id,
            "source_version": approval.source_version, "mailbox_account_id": approval.account_id,
            "message_id": approval.message_id, "from_address": approval.from_address,
            "to_address": approval.recipient, "subject": self.kwargs["subject"],
            "content": self.kwargs["content"], **changes}

    def send(self, approval, **changes):
        return self.engine._actions[ACTION]({"event": {}}, WorkflowStep(
            id="send", action=ACTION, inputs={"send": self.request(approval, **changes)}))

    def binding(self, approval):
        return {key: approval.model_dump()[key] for key in BINDING_FIELDS}

    def state(self, approval):
        return self.ledger.inspect(approval.approval_id)["state"]

    def assert_blocked(self, **changes):
        approval = self.issue()
        with self.assertRaises(ValueError):
            self.send(approval, **changes)
        self.assertFalse(self.fake.calls)
        self.assertEqual(self.state(approval), "issued")

    def test_explicit_human_issuance_is_durable(self):
        approval = self.issue()
        value = self.ledger.inspect(approval.approval_id)
        self.assertEqual(value["state"], "issued")
        self.assertEqual(value["actor"], "human:reviewer-42")
        self.assertEqual(value["approval"], approval.model_dump())
        self.assertEqual(approval.source_version, "2026-09-28T18:00:00+00:00")

    def test_machine_actor_cannot_issue(self):
        for actor in ("", "system", "automation-engine", "optibrain", "ai", "agent", "human:system",
                      "human:automation-engine", "human:agent-7", "human:service-account", " human:reviewer-42"):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                self.issue(actor=actor)
        self.assertFalse(self.store.recent_audit())

    def test_inspection_survives_restart(self):
        approval = self.issue()
        self.restart()
        self.assertEqual(self.ledger.inspect(approval.approval_id)["approval"], approval.model_dump())

    def test_duplicate_approval_id_rejected_even_after_consumption(self):
        approval = self.issue()
        with self.assertRaises(ValueError):
            self.issue(approval_id=approval.approval_id)
        self.send(approval)
        with self.assertRaises(ValueError):
            self.issue(approval_id=approval.approval_id)

    def test_approval_id_validation_at_issue_model_and_inspect(self):
        good = self.issue().model_dump()
        for bad in ("", "g" * 32, "A" * 32, "1" * 31, "1" * 33, "../" + "1" * 32, "1" * 32 + "\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.issue(approval_id=bad)
                with self.assertRaises(ValueError):
                    OutboundApproval.model_validate({**good, "approval_id": bad})
                with self.assertRaises(ValueError):
                    self.ledger.inspect(bad)

    def test_expired_approval_rejected(self):
        approval = self.issue(now=self.clock - timedelta(hours=2), expires_at=(self.clock - timedelta(hours=1)).isoformat())
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertFalse(self.fake.calls)

    def test_lifetime_exceeding_24_hours_rejected(self):
        with self.assertRaises(ValueError):
            self.issue(expires_at=(self.clock + timedelta(hours=24, microseconds=1)).isoformat())
        approval = self.issue(expires_at=(self.clock + timedelta(hours=24)).isoformat())
        with self.assertRaises(ValueError):
            OutboundApproval.model_validate({**approval.model_dump(), "expires_at": (self.clock + timedelta(days=2)).isoformat()})

    def test_naive_clock_and_approval_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            self.issue(now=self.clock.replace(tzinfo=None))
        good = self.issue().model_dump()
        for field in ("approved_at", "expires_at"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                OutboundApproval.model_validate({**good, field: "2026-09-28T18:00:00"})

    def test_future_approved_timestamp_cannot_send(self):
        approval = self.issue(now=self.clock + timedelta(minutes=10))
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertFalse(self.fake.calls)

    def test_policy_version_is_exact_and_revalidated_on_consume(self):
        approval = self.issue()
        with self.assertRaises(ValueError):
            OutboundApproval.model_validate({**approval.model_dump(), "policy_version": "phase5-lead-v1"})
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_audit SET metadata_json=? WHERE category=? AND target=?",
                (json.dumps({**approval.model_dump(), "policy_version": "wrong"}), CATEGORY, approval.approval_id))
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertFalse(self.fake.calls)

    def test_source_timestamp_canonicalization_preserves_instant(self):
        approval = self.issue(source_version="2026-09-28T14:00:00-04:00")
        self.assertEqual(approval.source_version, "2026-09-28T18:00:00+00:00")
        self.assertTrue(self.send(approval, source_version="2026-09-28T18:00:00Z")["sent"])

    def test_invalid_source_timestamps_and_id_injection_rejected(self):
        for value in ("2026-09-28T18:00:00", "2026-09-28T18:00:00+00:99", "v1", "../version", "2026-09-28T18:00:00+00:00\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.issue(source_version=value)
        with self.assertRaises(ValueError):
            self.issue(source_id="123/elsewhere")
        self.assertEqual(self.issue(source_type="draft", source_version="v1").source_version, "v1")

    def test_recipient_mismatch_blocks(self):
        self.assert_blocked(to_address="other@example.test")

    def test_sender_mismatch_blocks(self):
        self.assert_blocked(from_address="sales@opticable.ca")

    def test_subject_change_blocks(self):
        self.assert_blocked(subject="Changed subject")

    def test_content_change_blocks(self):
        self.assert_blocked(content="Changed content")

    def test_whitespace_change_invalidates_exact_content(self):
        self.assert_blocked(content=self.kwargs["content"].strip())

    def test_source_id_change_blocks(self):
        self.assert_blocked(source_id="124")

    def test_source_version_change_blocks(self):
        self.assert_blocked(source_version="2026-09-28T18:00:01+00:00")

    def test_source_type_change_blocks(self):
        self.assert_blocked(source_type="message")

    def test_action_type_change_blocks(self):
        self.assert_blocked(action_type="reply_email", message_id="789")

    def test_mailbox_account_change_blocks(self):
        self.assert_blocked(mailbox_account_id="457")

    def test_reply_message_id_change_blocks(self):
        approval = self.issue(action_type="reply_email", message_id="789")
        with self.assertRaises(ValueError):
            self.send(approval, message_id="790")
        self.assertFalse(self.fake.calls)

    def test_new_email_cannot_be_converted_to_reply(self):
        self.assert_blocked(message_id="789")

    def test_reply_cannot_be_converted_to_new_email(self):
        approval = self.issue(action_type="reply_email", message_id="789")
        with self.assertRaises(ValueError):
            self.send(approval, action_type="send_new_email", message_id=None)
        self.assertFalse(self.fake.calls)

    def test_reply_requires_message_id_and_new_email_forbids_it_at_issuance(self):
        for changes in ({"action_type": "reply_email"}, {"message_id": "789"},
                        {"action_type": "reply_email", "message_id": "789/path"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.issue(**changes)

    def test_successful_new_email_is_single_use(self):
        approval = self.issue()
        result = self.send(approval)
        self.assertTrue(result["sent"])
        self.assertEqual(self.state(approval), "consumed")
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.fake.calls[0][2], "/api/accounts/456/messages")
        self.assertEqual(self.fake.calls[0][3]["body"]["content"], self.kwargs["content"])
        self.assertEqual(self.fake.calls[0][3]["body"]["mailFormat"], "plaintext")

    def test_successful_reply_is_single_use(self):
        approval = self.issue(action_type="reply_email", message_id="789")
        self.send(approval)
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.fake.calls[0][2], "/api/accounts/456/messages/789")
        self.assertEqual(self.fake.calls[0][3]["body"]["action"], "reply")

    def test_restart_after_consumption_cannot_resend(self):
        approval = self.issue()
        self.send(approval)
        self.restart()
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertEqual(len(self.fake.calls), 1)

    def test_process_exit_after_durable_consuming_cannot_resend(self):
        approval = self.issue()
        original = OutboundApprovalLedger.mark_consuming
        def crash(ledger, envelope):
            original(ledger, envelope)
            os._exit(17)
        def child():
            self.restart()
            with patch.object(OutboundApprovalLedger, "mark_consuming", crash):
                self.send(approval)
        process = multiprocessing.get_context("fork").Process(target=child)
        process.start()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
        self.assertEqual(process.exitcode, 17)
        self.restart()
        self.assertEqual(self.state(approval), "consuming")
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertFalse(self.fake.calls)

    def test_response_loss_after_acceptance_is_manual_and_never_retries(self):
        approval = self.issue()
        self.fake.error = httpx.ReadTimeout("Private approved body. Authorization: secret")
        with self.assertRaises(ZohoWriteUnconfirmedError):
            self.send(approval)
        self.assertEqual(self.state(approval), "manual")
        self.restart()
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertNotIn("Authorization", json.dumps(self.store.recent_audit()))

    def test_process_exit_after_provider_acceptance_keeps_consuming_fence(self):
        approval = self.issue()
        marker = self.root / "accepted"
        def child():
            self.restart()
            def accepted():
                marker.write_text("fake provider accepted once")
                os._exit(18)
            self.fake.on_call = accepted
            self.send(approval)
        process = multiprocessing.get_context("fork").Process(target=child)
        process.start()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
        self.assertEqual(process.exitcode, 18)
        self.assertEqual(marker.read_text(), "fake provider accepted once")
        self.restart()
        self.assertEqual(self.state(approval), "consuming")
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertFalse(self.fake.calls)

    def test_failed_intent_journal_prevents_provider_call(self):
        approval = self.issue()
        original = OutboundApprovalLedger._record
        def fail(ledger, action, *args, **kwargs):
            if action == "consuming":
                raise OSError("disk unavailable")
            return original(ledger, action, *args, **kwargs)
        with patch.object(OutboundApprovalLedger, "_record", fail), self.assertRaises(OSError):
            self.send(approval)
        self.assertFalse(self.fake.calls)
        self.assertEqual(self.state(approval), "issued")

    def test_failed_finalization_journal_keeps_human_required_fence(self):
        approval = self.issue()
        original = OutboundApprovalLedger._record
        def fail(ledger, action, *args, **kwargs):
            if action in {"consumed", "manual"}:
                raise OSError("disk unavailable")
            return original(ledger, action, *args, **kwargs)
        with patch.object(OutboundApprovalLedger, "_record", fail), self.assertRaises(ZohoWriteUnconfirmedError):
            self.send(approval)
        self.assertEqual(self.state(approval), "consuming")
        self.restart()
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertEqual(len(self.fake.calls), 1)

    def test_expiry_after_consuming_prevents_provider_call(self):
        approval = self.issue()
        original = OutboundApprovalLedger.mark_consuming
        def expire(ledger, envelope):
            original(ledger, envelope)
            patcher = patch("workflow.automation.outbound_approval._clock", return_value=self.clock + timedelta(hours=2))
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.object(OutboundApprovalLedger, "mark_consuming", expire), self.assertRaises(ZohoWriteUnconfirmedError):
            self.send(approval)
        self.assertEqual(self.state(approval), "manual")
        self.assertFalse(self.fake.calls)

    def test_symlink_lock_path_cannot_be_used(self):
        approval = self.issue()
        self.ledger._lock_path.unlink()
        self.ledger._lock_path.symlink_to(self.root / "elsewhere")
        with self.assertRaises(OSError):
            self.send(approval)
        self.assertFalse(self.fake.calls)

    def assert_ambiguous(self, response):
        approval = self.issue()
        self.fake.response = response
        previous = len(self.fake.calls)
        with self.assertRaises(ZohoWriteUnconfirmedError):
            self.send(approval)
        self.assertEqual(self.state(approval), "manual")
        self.restart()
        with self.assertRaises(ValueError):
            self.send(approval)
        self.assertEqual(len(self.fake.calls), previous + 1)

    def test_malformed_acknowledgements_are_manual(self):
        for response in (None, "html", [], {}, {"ok": True, "status": 200, "data": "html"},
                         {"ok": True, "status": 200, "data": {"data": {"messageId": "9001"}}},
                         {"ok": True, "status": 200, "data": {"status": {"code": 500}, "data": {"messageId": "9001"}}}):
            with self.subTest(response=response):
                self.assert_ambiguous(response)

    def test_missing_or_generic_provider_id_is_manual(self):
        for data in ({}, {"id": "9001"}, {"messageId": "bad/id"}, {"messageId": True}):
            with self.subTest(data=data):
                self.assert_ambiguous({"ok": True, "status": 200, "data": {"status": {"code": 200}, "data": data}})

    def test_4xx_5xx_and_unknown_status_never_retry(self):
        for status in (400, 401, 403, 404, 408, 409, 429, 500, 502, 503, 202):
            with self.subTest(status=status):
                self.assert_ambiguous({"ok": status == 202, "status": status, "data": self.fake.response["data"]})

    def test_concurrent_process_consumers_send_at_most_once(self):
        approval = self.issue()
        ctx = multiprocessing.get_context("fork")
        accepted, release = ctx.Event(), ctx.Event()
        marker = self.root / "provider-calls"
        def on_call():
            marker.write_text("one fake send")
            accepted.set()
            if not release.wait(8):
                raise RuntimeError("test synchronization timeout")
        def child():
            self.restart()
            self.fake.on_call = on_call
            self.send(approval)
        process = ctx.Process(target=child)
        process.start()
        try:
            self.assertTrue(accepted.wait(5))
            with self.assertRaises(ValueError):
                self.send(approval)
            self.assertFalse(self.fake.calls)
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.kill()
                process.join()
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(marker.read_text(), "one fake send")
        self.assertEqual(self.state(approval), "consumed")

    def test_disabled_policy_has_zero_provider_calls(self):
        approval = self.issue()
        for policy in ("", "observe", "phase5-lead-v1"):
            with self.subTest(policy=policy), patch.dict(os.environ, {"OPTIBRAIN_OUTBOUND_SENDS": policy}):
                self.assertFalse(self.send(approval)["sent"])
        self.assertFalse(self.fake.calls)
        self.assertEqual(self.state(approval), "issued")

    def test_policy_change_before_consuming_prevents_send(self):
        approval = self.issue()
        original = OutboundApprovalLedger.require_issued
        def disable(ledger, *args, **kwargs):
            result = original(ledger, *args, **kwargs)
            os.environ["OPTIBRAIN_OUTBOUND_SENDS"] = "observe"
            return result
        with patch.object(OutboundApprovalLedger, "require_issued", disable):
            self.assertFalse(self.send(approval)["sent"])
        self.assertEqual(self.state(approval), "issued")
        self.assertFalse(self.fake.calls)

    def test_policy_change_after_consuming_prevents_send_and_is_terminal(self):
        approval = self.issue()
        original = OutboundApprovalLedger.require_consuming
        def disable(ledger, envelope):
            original(ledger, envelope)
            os.environ["OPTIBRAIN_OUTBOUND_SENDS"] = "observe"
        with patch.object(OutboundApprovalLedger, "require_consuming", disable):
            self.assertFalse(self.send(approval)["sent"])
        self.assertEqual(self.state(approval), "manual")
        self.assertFalse(self.fake.calls)
        os.environ["OPTIBRAIN_OUTBOUND_SENDS"] = POLICY_VERSION
        with self.assertRaises(ValueError):
            self.send(approval)

    def test_audit_contains_hashes_not_subject_body_or_provider_secrets(self):
        approval = self.issue()
        self.fake.response["request_id"] = "Bearer sensitive-provider-data"
        self.send(approval)
        evidence = json.dumps(self.store.recent_audit(limit=100))
        for raw in (self.kwargs["subject"], self.kwargs["content"], "sensitive-provider-data"):
            self.assertNotIn(raw, evidence)
        self.assertIn(digest(self.kwargs["subject"]), evidence)
        self.assertIn(digest(self.kwargs["content"]), evidence)
        self.assertIn("9001", evidence)

    def test_sender_and_customer_address_restrictions(self):
        for field, value in (("from_address", "sender@example.test"), ("recipient", "person@opticable.ca"),
                             ("recipient", "person@sub.opti-plex.ca"), ("recipient", "a@example.test,b@example.test"),
                             ("recipient", "a@example.test\r\nBcc: x@elsewhere.test"),
                             ("recipient", "a..b@example.test"), ("recipient", "a@-bad.test")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.issue(**{field: value})

    def test_subject_content_bounds_and_header_controls(self):
        for field, value in (("subject", ""), ("subject", "x" * 501), ("subject", "Header\nBcc: x"),
                             ("content", " "), ("content", "x" * 12001), ("content", "body\x00")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.issue(**{field: value})

    def test_plaintext_only_no_cc_bcc_attachments_or_scheduling(self):
        approval = self.issue()
        for change in ({"mail_format": "html"}, {"ccAddress": "copy@example.test"}, {"bcc": []},
                       {"attachments": []}, {"isSchedule": True}, {"approved_to_send": True}, {"policy_version": "wrong"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.send(approval, **change)
        self.assertFalse(self.fake.calls)

    def test_partial_binding_cannot_be_used_to_consume(self):
        approval = self.issue()
        with self.assertRaises(ValueError):
            self.ledger.require_issued({"approval_id": approval.approval_id})

    def test_transitions_require_lock_and_exact_stored_envelope(self):
        approval = self.issue()
        with self.assertRaises(ValueError):
            self.ledger.mark_consuming(approval)
        with self.ledger.lock(), self.assertRaises(ValueError):
            self.ledger.mark_consuming(approval.model_copy(update={"recipient": "changed@example.test"}))
        self.assertEqual(self.state(approval), "issued")

    def test_manual_and_consumed_states_cannot_be_reset(self):
        for terminal in ("manual", "consumed"):
            with self.subTest(terminal=terminal):
                approval = self.issue()
                with self.ledger.lock():
                    if terminal == "manual":
                        self.ledger.mark_manual(approval, error="preflight_changed")
                    else:
                        self.ledger.mark_consuming(approval)
                        self.ledger.mark_consumed(approval, provider_operation_id="9001")
                    with self.assertRaises(ValueError):
                        self.ledger.mark_consuming(approval)
                self.assertEqual(self.state(approval), terminal)

    def test_no_approval_issuance_action_and_send_is_not_retry_safe(self):
        self.assertEqual([a for a in self.engine.action_names() if "mail" in a or "approval" in a], [ACTION])
        self.assertNotIn(ACTION, self.engine._retry_safe_actions)

    def test_engine_never_retries_even_if_workflow_requests_multiple_attempts(self):
        approval = self.issue()
        definition = WorkflowDefinition.model_validate({"id": "test.send", "name": "test", "version": 1,
            "enabled": True, "trigger": {"event_types": ["test.send"]}, "steps": [{"id": "send", "action": ACTION,
            "with": {"send": self.request(approval)}, "retry": {"max_attempts": 5, "backoff_seconds": 0}}]})
        self.store.upsert_workflow(definition)
        self.fake.error = httpx.ReadTimeout("accepted, response lost")
        result = self.engine.ingest(AutomationEvent(event_type="test.send", source="unit"))
        self.assertEqual(self.store.get_run(result.run_ids[0])["status"], "human_action_required")
        self.engine.recover_pending(limit=20)
        self.restart()
        self.engine.recover_pending(limit=20)
        self.assertEqual(len(self.fake.calls), 1)

    def test_legacy_workflow_disabled_and_no_new_action_startup_registration(self):
        raw = yaml.safe_load((APP / "config/automation/workflows/customer-lifecycle-approved-email-reply.yaml").read_text())
        self.assertFalse(raw["enabled"])
        self.assertEqual(raw["steps"][0]["retry"]["max_attempts"], 1)
        self.store.upsert_workflow(WorkflowDefinition.model_validate(raw))
        result = self.engine.ingest(AutomationEvent(event_type="customer.lifecycle.email.reply.approved_to_send", source="unit",
                                                   payload={"approved_to_send": True}))
        self.assertFalse(result.run_ids)
        for path in (APP / "workflow").rglob("*.py"):
            if path.name in {"outbound_mail.py", "outbound_approval.py"}:
                continue
            source = path.read_text()
            if path.name == "phase7_registration.py":
                # Phase 7 introduces a separate exact-SHA, root-manifest and
                # single-approval-pin gate. The default startup still cannot
                # register this send action or a retryable workflow.
                self.assertIn('if plan["outbound"]:', source)
                self.assertIn('OPTIBRAIN_OUTBOUND_CANARY_APPROVAL_ID', source)
                self.assertIn('validate_registration(manifest', source)
            else:
                self.assertNotIn("register_outbound_mail_action", source, str(path))
            self.assertNotIn("allow_legacy_reply=True", source, str(path))
        for path in (APP / "config/automation/workflows").glob("*.yaml"):
            definition = yaml.safe_load(path.read_text())
            if definition.get("enabled"):
                self.assertFalse(any(s["action"] in {ACTION, "lifecycle.mail_reply_approved"} for s in definition["steps"]), str(path))

    def test_queued_legacy_boolean_snapshot_cannot_send_with_default_registration(self):
        register_lifecycle_mailbox_actions(self.engine, self.fake, self.store)
        raw = yaml.safe_load((APP / "config/automation/workflows/customer-lifecycle-approved-email-reply.yaml").read_text())
        raw.update(enabled=True, version=1)
        raw["steps"][0]["retry"]["max_attempts"] = 2
        self.store.upsert_workflow(WorkflowDefinition.model_validate(raw))
        result = self.engine.ingest(AutomationEvent(event_type="customer.lifecycle.email.reply.approved_to_send", source="unit",
            payload={"approved_to_send": True, "mailbox_account_id": "456", "message_id": "789",
                     "from_address": "info@opticable.ca", "to_address": "Client@example.test", "subject": "hello", "content": "body"}))
        self.assertEqual(self.store.get_run(result.run_ids[0])["status"], "failed")
        self.assertFalse(self.fake.calls)

    def test_static_provider_boundary_is_mail_post_only(self):
        tree = ast.parse((APP / "workflow/automation/providers/outbound_mail.py").read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "request"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([ast.literal_eval(v) for v in calls[0].args[:2]], ["mail", "POST"])
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/"):
                self.assertIn(node.value, {"/api/accounts/", "/messages", "/messages/"})
