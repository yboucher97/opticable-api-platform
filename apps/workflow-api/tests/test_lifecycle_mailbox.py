from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.lifecycle_mailbox import register_lifecycle_mailbox_actions
from workflow.automation.store import AutomationStore


class FakeMailZoho:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply_count = 0

    def request(self, service, method, path, **kwargs):
        self.calls.append({"service": service, "method": method, "path": path, **kwargs})
        if service != "mail":
            raise AssertionError(f"Unexpected service {service}")
        if method == "GET" and path.endswith("/messages/search"):
            return {
                "data": [
                    {
                        "messageId": "external-1",
                        "folderId": "inbox-1",
                        "threadId": "thread-1",
                        "receivedTime": "1790400000000",
                        "fromAddress": "client@example.com",
                        "sender": "Client Example",
                        "subject": "Need cabling quote",
                        "summary": "Need 20 network drops",
                        "toAddress": "soumissions@opticable.ca",
                        "ccAddress": "",
                        "hasAttachment": "0",
                    },
                    {
                        "messageId": "internal-1",
                        "folderId": "inbox-1",
                        "receivedTime": "1790400000000",
                        "fromAddress": "support@opticable.ca",
                        "sender": "Support",
                        "subject": "Internal",
                        "summary": "Internal mail",
                    },
                    {
                        "messageId": "sent-1",
                        "folderId": "1083319000000008022",
                        "receivedTime": "1790400000000",
                        "fromAddress": "yboucher@opticable.ca",
                        "sender": "Yan",
                        "subject": "Sent",
                        "summary": "Sent mail",
                    },
                ]
            }
        if method == "GET" and path.endswith("/folders/inbox-1/messages/external-1/content"):
            return {"data": {"content": {"content": "<p>Hello, we need 20 network drops.</p>"}}}
        if method == "POST" and "/messages/" in path:
            self.reply_count += 1
            return {"status": 200, "data": {"messageId": "reply-1"}}
        raise AssertionError(f"Unexpected request: {service} {method} {path}")


class LifecycleMailboxTests(unittest.TestCase):
    def _engine(self, workflow_text: str):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(tmp.name)
        workflows = root / "workflows"
        workflows.mkdir()
        (workflows / "workflow.yaml").write_text(workflow_text.strip() + "\n", encoding="utf-8")
        store = AutomationStore(root / "automation.db")
        engine = AutomationEngine(store, workflows)
        zoho = FakeMailZoho()
        register_lifecycle_mailbox_actions(engine, zoho, store)
        engine.sync_definitions()
        return tmp, store, engine, zoho

    def test_mailbox_poll_is_read_only_and_child_email_is_idempotent(self) -> None:
        workflow = """
id: test.mailbox.poll
name: Mailbox poll
version: 1
enabled: true
trigger:
  event_types: [test.mailbox.poll]
steps:
  - id: poll
    action: lifecycle.mailbox_poll
    with:
      account_id: "1083319000000008002"
      mailbox_address: "yboucher@opticable.ca"
      window_days: 2
      limit: 100
"""
        tmp, store, engine, zoho = self._engine(workflow)
        try:
            first = engine.ingest(AutomationEvent(event_type="test.mailbox.poll", source="unit", idempotency_key="poll-1"))
            second = engine.ingest(AutomationEvent(event_type="test.mailbox.poll", source="unit", idempotency_key="poll-2"))
            first_run = store.get_run(first.run_ids[0])
            second_run = store.get_run(second.run_ids[0])
            self.assertEqual(first_run["status"], "completed")
            self.assertEqual(second_run["status"], "completed")
            first_result = first_run["steps"][0]["result"]
            second_result = second_run["steps"][0]["result"]
            self.assertEqual(first_result["accepted"], 1)
            self.assertEqual(first_result["skipped_internal"], 1)
            self.assertEqual(first_result["skipped_sent"], 1)
            self.assertEqual(first_result["mailbox_mutations"], 0)
            self.assertEqual(second_result["accepted"], 0)
            self.assertEqual(second_result["duplicates"], 1)
            self.assertTrue(all(call["method"] == "GET" for call in zoho.calls))
        finally:
            store.close()
            tmp.cleanup()

    def test_unapproved_reply_makes_zero_mail_calls(self) -> None:
        workflow = """
id: test.reply.blocked
name: Reply blocked
version: 1
enabled: true
trigger:
  event_types: [test.reply.blocked]
steps:
  - id: reply
    action: lifecycle.mail_reply_approved
    with:
      reply: "{{ event.payload }}"
"""
        tmp, store, engine, zoho = self._engine(workflow)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="test.reply.blocked",
                    source="unit",
                    payload={
                        "mailbox_account_id": "1083319000000008002",
                        "message_id": "m1",
                        "from_address": "yboucher@opticable.ca",
                        "to_address": "client@example.com",
                        "subject": "Re: Test",
                        "content": "Hello",
                        "approved_to_send": False,
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "failed")
            self.assertEqual(zoho.calls, [])
        finally:
            store.close()
            tmp.cleanup()

    def test_approved_reply_uses_reply_action(self) -> None:
        workflow = """
id: test.reply.send
name: Reply send
version: 1
enabled: true
trigger:
  event_types: [test.reply.send]
steps:
  - id: reply
    action: lifecycle.mail_reply_approved
    with:
      reply: "{{ event.payload }}"
"""
        tmp, store, engine, zoho = self._engine(workflow)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="test.reply.send",
                    source="unit",
                    payload={
                        "mailbox_account_id": "1083319000000008002",
                        "message_id": "m1",
                        "from_address": "soumissions@opticable.ca",
                        "to_address": "client@example.com",
                        "subject": "Re: Test",
                        "content": "Bonjour, merci.",
                        "approved_to_send": True,
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            self.assertEqual(zoho.reply_count, 1)
            call = zoho.calls[0]
            self.assertEqual(call["method"], "POST")
            self.assertEqual(call["path"], "/api/accounts/1083319000000008002/messages/m1")
            self.assertEqual(call["body"]["action"], "reply")
            self.assertEqual(call["body"]["fromAddress"], "soumissions@opticable.ca")
        finally:
            store.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
