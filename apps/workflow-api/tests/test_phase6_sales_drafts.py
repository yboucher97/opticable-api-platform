from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import yaml

from workflow.automation.desired_journal import DesiredJournal
from workflow.automation.engine import AutomationEngine
from workflow.automation.event_schema import digest
from workflow.automation.events import EventLedger
from workflow.automation.models import AutomationEvent, WorkflowDefinition, WorkflowStep
from workflow.automation.providers.lifecycle_extended import register_lifecycle_extended_actions
from workflow.automation.providers.mail_drafts import save_mail_draft
from workflow.automation.providers.sales_drafts import TEMPLATES
from workflow.automation.sales_decision import build_sales_decision
from workflow.automation.store import AutomationStore
from workflow.zoho_gateway import ZohoWriteUnconfirmedError


class FakeMail:
    def __init__(self):
        self.lead = {"id": "123", "Email": "client@example.test", "Email_Opt_Out": False,
                     "Converted__s": False, "Lead_Status": "Not Contacted",
                     "Modified_Time": "2026-09-28T13:00:00Z", "Language": "fr"}
        self.calls = []
        self.drafts = []
        self.lose = False
        self.response = None
        self.before_second_read = None
        self.reads = 0

    def request(self, service, method, path, **kwargs):
        self.calls.append((service, method, path, copy.deepcopy(kwargs)))
        if (service, method, path) == ("zohoapis", "GET", "/crm/v8/Leads/123"):
            self.reads += 1
            if self.reads == 2 and self.before_second_read:
                self.before_second_read()
            return {"ok": True, "status": 200, "data": {"data": [copy.deepcopy(self.lead)]}}
        if (service, method, path) != ("mail", "POST", "/api/accounts/456/messages"):
            raise AssertionError("Forbidden provider operation")
        payload = kwargs["body"]
        if payload["mode"] != "draft" or set(payload) - {"mode", "fromAddress", "toAddress", "subject", "content", "mailFormat", "inReplyTo"}:
            raise AssertionError("Forbidden mail operation")
        self.drafts.append(copy.deepcopy(payload))
        if self.lose:
            raise httpx.ReadTimeout("customer body client@example.test must not persist")
        return self.response if self.response is not None else {
            "ok": True, "status": 200,
            "data": {"status": {"code": 200, "description": "success"},
                     "data": {"messageId": str(700 + len(self.drafts))}},
        }


class SalesDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = AutomationStore(self.root / "automation.db")
        self.definitions = Path(__file__).resolve().parents[1] / "config/automation/workflows"
        definition = WorkflowDefinition.model_validate(yaml.safe_load(
            (self.definitions / "opticable-sales-draft.yaml").read_text()))
        self.store.upsert_workflow(definition)
        self.fake = FakeMail()
        self.restart()
        self.env = patch.dict(os.environ, {"OPTIBRAIN_SALES_DRAFTS": "phase6-sales-v1",
            "OPTIBRAIN_SALES_DRAFT_ACCOUNT_ID": "456", "OPTIBRAIN_SALES_DRAFT_FROM": "info@opticable.ca"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def restart(self):
        self.store = AutomationStore(self.store.db_path)
        self.engine = AutomationEngine(self.store, self.definitions)
        register_lifecycle_extended_actions(self.engine, self.fake, None, self.store)

    def event(self, *, extra=None):
        decision = build_sales_decision(self.fake.lead, now=datetime(2026, 9, 28, 14, tzinfo=timezone.utc))
        return AutomationEvent(event_type="opticable.crm.lead.reviewed", source="crm-lead-observer",
            source_account="org-fixture", occurred_at="2026-09-28T14:00:00Z",
            payload={"lead_id": "123", "version": decision.version, "sales_decision": decision.model_dump(), **(extra or {})})

    def run_event(self, event=None):
        result = self.engine.ingest(event or self.event())
        self.engine.recover_pending(limit=20)
        return self.store.get_run(result.run_ids[0]) if result.run_ids else None

    def invoke(self, event=None):
        return self.engine._actions["lifecycle.sales_draft"](
            {"event": (event or self.event()).model_dump()}, WorkflowStep(id="draft", action="lifecycle.sales_draft"))

    def test_french_draft_uses_exact_lead_recipient_and_safe_evidence(self):
        result = self.run_event(self.event(extra={"recipient": "invented@example.test", "content": "ignored"}))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.fake.drafts), 1)
        self.assertEqual(self.fake.drafts[0]["toAddress"], "client@example.test")
        self.assertEqual(self.fake.drafts[0]["content"], TEMPLATES["fr"][1])
        audit = json.dumps(self.store.recent_audit(limit=100))
        self.assertNotIn("client@example.test", audit)
        self.assertNotIn(TEMPLATES["fr"][1], audit)
        proof = next(r["metadata"] for r in self.store.recent_audit() if r["action"] == "verified")
        self.assertEqual(proof["draft_id"], "701")
        self.assertEqual(proof["content_hash"], digest(self.fake.drafts[0]))

    def test_english_template_is_bounded(self):
        self.fake.lead["Language"] = "en"
        self.run_event()
        self.assertEqual(self.fake.drafts[0]["content"], TEMPLATES["en"][1])

    def test_unknown_language_has_zero_mutations(self):
        self.fake.lead["Language"] = "es"
        self.run_event()
        self.assertFalse(self.fake.drafts)

    def test_opt_out_and_missing_recipient_have_zero_mutations(self):
        for changes in ({"Email_Opt_Out": True}, {"Email_Opt_Out": None},
                        {"Email": ""}, {"Email": "a@example.test,b@example.test"},
                        {"Email": "a@example.test\r\nBcc: bad@example.test"},
                        {"Email": "internal@opticable.ca"}, {"Converted__s": True},
                        {"Converted__s": None}, {"Lead_Status": "Junk Lead"}):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.fake.lead)
                self.fake.lead.update(changes)
                self.invoke()
                self.assertFalse(self.fake.drafts)
                self.fake.lead = original

    def test_observe_is_first_rollback_and_performs_no_provider_call(self):
        for policy in ("", "observe", "disabled", "phase5-lead-v1"):
            with self.subTest(policy=policy), patch.dict(os.environ, {"OPTIBRAIN_SALES_DRAFTS": policy}):
                self.assertEqual(self.invoke()["reason"], "observe")
        self.assertFalse(self.fake.calls)

    def test_same_version_is_deduplicated_after_restart_and_different_event_id(self):
        event = self.event()
        self.invoke(event)
        self.restart()
        result = self.invoke(self.event())
        self.assertTrue(result["deduplicated"])
        self.assertEqual(result["draft_id"], "701")
        self.assertEqual(len(self.fake.drafts), 1)

    def test_changed_content_same_version_requires_human(self):
        self.invoke()
        with patch.dict(TEMPLATES, {"fr": ("Changed", "Different body")}):
            with self.assertRaises(ZohoWriteUnconfirmedError):
                self.invoke()
        self.assertEqual(len(self.fake.drafts), 1)

    def test_newer_version_supersedes_and_old_review_does_not_create(self):
        old = self.event()
        self.invoke(old)
        self.fake.lead["Modified_Time"] = "2026-09-28T14:01:00Z"
        self.fake.lead["Language"] = "en"
        self.invoke()
        self.assertEqual(len(self.fake.drafts), 2)
        proof = next(r["metadata"] for r in self.store.recent_audit() if r["action"] == "verified")
        self.assertEqual(proof["supersedes_draft_id"], "701")
        self.assertEqual(self.invoke(old)["reason"], "superseded")
        self.assertEqual(len(self.fake.drafts), 2)

    def test_lost_response_fences_same_and_newer_versions_after_restart(self):
        self.fake.lose = True
        result = self.run_event()
        self.assertEqual(result["status"], "human_action_required")
        self.restart()
        for version in ("2026-09-28T13:00:00Z", "2026-09-28T14:01:00Z"):
            with self.subTest(version=version):
                self.fake.lead["Modified_Time"] = version
                with self.assertRaises(ZohoWriteUnconfirmedError):
                    self.invoke()
        self.assertEqual(len(self.fake.drafts), 1)
        self.assertNotIn("client@example.test", json.dumps(self.store.recent_audit(limit=100)))

    def test_missing_provider_id_is_ambiguous_and_not_retried(self):
        self.fake.response = {"ok": True, "status": 200, "data": {"status": {"code": 200}, "data": {}}}
        self.assertEqual(self.run_event()["status"], "human_action_required")
        self.restart()
        with self.assertRaises(ZohoWriteUnconfirmedError):
            self.invoke()
        self.assertEqual(len(self.fake.drafts), 1)

    def test_provider_error_or_malformed_ack_remains_ambiguous(self):
        responses = (
            {"ok": False, "status": 500, "data": {}},
            {"ok": True, "status": 202, "data": {}},
            {"ok": True, "status": 200, "data": {"status": {"code": 500}, "data": {"messageId": "701"}}},
            {"ok": True, "status": 200, "data": "not-json"},
            {"ok": True, "status": 200, "data": {"status": {"code": 200}, "data": {"messageId": "bad/id"}}},
        )
        for index, response in enumerate(responses):
            with self.subTest(index=index):
                self.store = AutomationStore(self.root / f"response-{index}.db")
                self.restart()
                self.fake.response = response
                with self.assertRaises(ZohoWriteUnconfirmedError):
                    self.invoke()
                with self.assertRaises(ZohoWriteUnconfirmedError):
                    self.invoke()
                self.assertEqual(len(self.fake.drafts), index + 1)

    def test_changed_notification_account_cannot_bypass_ambiguity(self):
        self.fake.lose = True
        with self.assertRaises(ZohoWriteUnconfirmedError):
            self.invoke()
        event = self.event().model_copy(update={"source_account": "different-notification-metadata"})
        with self.assertRaises(ZohoWriteUnconfirmedError):
            self.invoke(event)
        self.assertEqual(len(self.fake.drafts), 1)

    def test_second_read_changed_recipient_cancels_even_without_version_change(self):
        self.fake.before_second_read = lambda: self.fake.lead.update(Email="changed@example.test")
        self.assertEqual(self.invoke()["reason"], "recipient_changed")
        self.assertFalse(self.fake.drafts)

    def test_crash_after_accept_before_verified_journal_never_reposts(self):
        original = DesiredJournal.record
        def record(journal, action, *args):
            if action == "verified":
                raise SystemExit("simulated process loss")
            return original(journal, action, *args)
        with patch.object(DesiredJournal, "record", record), self.assertRaises(SystemExit):
            self.invoke()
        self.restart()
        with self.assertRaises(ZohoWriteUnconfirmedError):
            self.invoke()
        self.assertEqual(len(self.fake.drafts), 1)

    def test_stale_version_and_second_read_drift_have_zero_mutations(self):
        event = self.event()
        self.fake.lead["Modified_Time"] = "2026-09-28T14:01:00Z"
        self.assertEqual(self.invoke(event)["reason"], "superseded")
        self.fake.reads = 0
        self.fake.before_second_read = lambda: self.fake.lead.update(Email_Opt_Out=True)
        self.assertEqual(self.invoke()["reason"], "email_opt_out_or_unknown")
        self.assertFalse(self.fake.drafts)

    def test_disable_during_read_prevents_post(self):
        self.fake.before_second_read = lambda: os.environ.update(OPTIBRAIN_SALES_DRAFTS="observe")
        self.assertEqual(self.invoke()["reason"], "observe")
        self.assertFalse(self.fake.drafts)

    def test_tampered_decision_and_wrong_source_fail_closed(self):
        event = self.event()
        event.payload["sales_decision"]["language"] = "en"
        with self.assertRaises(ValueError):
            self.invoke(event)
        event = self.event().model_copy(update={"source": "ai"})
        with self.assertRaises(ValueError):
            self.invoke(event)
        self.assertFalse(self.fake.calls)

    def test_journal_lock_prevents_concurrent_second_writer(self):
        with DesiredJournal(self.store).lock():
            with self.assertRaises(ValueError):
                self.invoke()
        self.assertFalse(self.fake.calls)

    def captured_message(self, **changes):
        email = {"mailbox_account_id": "456", "mailbox_address": "info@opticable.ca",
                 "sender_email": "client@example.test", "message_id": "888",
                 "internet_message_id": "<source@example.test>", "body": "private inbound content", **changes}
        event = AutomationEvent(event_type="customer.lifecycle.email.received", source="zoho-mail-poller", payload=email)
        self.engine.ingest(event)
        captured = EventLedger(self.store).inspect(event.event_id)
        return {"message_event_id": event.event_id, "message_content_hash": captured["content_hash"]}

    def test_message_recipient_comes_from_exact_captured_source(self):
        extra = self.captured_message()
        event = self.event(extra=extra)
        self.invoke(event)
        self.restart()
        self.assertTrue(self.invoke(event)["deduplicated"])
        self.assertEqual(len(self.fake.drafts), 1)
        self.assertEqual(self.fake.drafts[0]["inReplyTo"], "<source@example.test>")
        self.assertNotIn("private inbound content", json.dumps(self.store.recent_audit(limit=100)))

    def test_message_hash_or_recipient_mismatch_cannot_draft(self):
        extra = self.captured_message()
        with self.assertRaises(ValueError):
            self.invoke(self.event(extra={**extra, "message_content_hash": "bad"}))
        extra = self.captured_message(sender_email="invented@example.test")
        with self.assertRaises(ValueError):
            self.invoke(self.event(extra=extra))
        self.assertFalse(self.fake.drafts)

    def test_missing_reply_header_requires_review_without_post(self):
        extra = self.captured_message(internet_message_id="")
        self.assertEqual(self.invoke(self.event(extra=extra))["reason"], "message_identity_requires_review")
        self.assertFalse(self.fake.drafts)

    def test_unconfigured_or_unapproved_sender_has_zero_provider_calls(self):
        for config in ({"OPTIBRAIN_SALES_DRAFT_ACCOUNT_ID": ""},
                       {"OPTIBRAIN_SALES_DRAFT_ACCOUNT_ID": "456/elsewhere"},
                       {"OPTIBRAIN_SALES_DRAFT_FROM": "bad@example.test"}):
            with self.subTest(config=config), patch.dict(os.environ, config):
                self.invoke()
        self.assertFalse(self.fake.calls)

    def test_shared_transport_rejects_send_schedule_and_path_injection(self):
        for account, payload in (("456", {"mode": "send"}),
                                 ("456", {"mode": "draft", "isSchedule": True}),
                                 ("456/elsewhere", {"mode": "draft"})):
            with self.subTest(account=account, payload=payload), self.assertRaises(ValueError):
                save_mail_draft(self.fake, account, payload)
        self.assertFalse(self.fake.calls)
