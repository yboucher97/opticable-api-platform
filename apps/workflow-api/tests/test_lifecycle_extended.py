from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.lifecycle_extended import register_lifecycle_extended_actions
from workflow.automation.store import AutomationStore


class FakeAi:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return {"provider": "openai", "model": "test-model", "text": json.dumps(self.payload)}


class FakeZoho:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.counter = 1000

    def request(self, service, method, path, **kwargs):
        self.calls.append({"service": service, "method": method, "path": path, **kwargs})
        if method == "GET" and path.endswith("/search"):
            return {"data": {"data": []}}
        if method in {"POST", "PUT"}:
            self.counter += 1
            return {
                "status": 201 if method == "POST" else 200,
                "data": {"data": [{"code": "SUCCESS", "details": {"id": str(self.counter)}}]},
            }
        raise AssertionError(f"Unexpected request {service} {method} {path}")


class LifecycleExtendedTests(unittest.TestCase):
    def _engine(self, workflow_text: str, ai_payload: dict):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        workflows = root / "workflows"
        workflows.mkdir()
        (workflows / "workflow.yaml").write_text(workflow_text.strip() + "\n", encoding="utf-8")
        store = AutomationStore(root / "automation.db")
        engine = AutomationEngine(store, workflows)
        zoho = FakeZoho()
        ai = FakeAi(ai_payload)
        register_lifecycle_extended_actions(engine, zoho, ai, store)
        engine.sync_definitions()
        return tmp, store, engine, zoho, ai

    def test_qualified_lead_promotes_to_account_contact_deal(self) -> None:
        workflow = """
id: test.promote
name: Promote
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.lead.synced]
steps:
  - id: qualify
    action: lifecycle.qualify_lead
    with:
      lead: "{{ event.payload.lead }}"
  - id: promote
    action: lifecycle.crm_promote_lead
    with:
      lead: "{{ event.payload.lead }}"
      qualification: "{{ steps.qualify }}"
"""
        ai_payload = {
            "qualified": True,
            "confidence": 0.94,
            "summary": "Commercial cabling inquiry.",
            "service_type": "Structured cabling",
            "language": "en",
            "priority": "normal",
            "recommended_next_action": "reply",
            "missing_information": ["site address"],
            "reason": "Clear service request.",
        }
        tmp, store, engine, zoho, _ = self._engine(workflow, ai_payload)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.lead.synced",
                    source="unit-test",
                    payload={
                        "lead": {
                            "source": "website",
                            "inquiry_id": "inq-123",
                            "first_name": "Jane",
                            "last_name": "Doe",
                            "company": "Example Inc.",
                            "email": "jane@example.com",
                            "phone": "5145550100",
                            "service_type": "Structured cabling",
                            "occurred_at": "2026-09-25T12:00:00Z",
                            "attribution": {},
                            "address": {},
                        }
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            posts = [(c["service"], c["method"], c["path"]) for c in zoho.calls if c["method"] == "POST"]
            self.assertIn(("zohoapis", "POST", "/crm/v8/Accounts"), posts)
            self.assertIn(("zohoapis", "POST", "/crm/v8/Contacts"), posts)
            self.assertIn(("zohoapis", "POST", "/crm/v8/Deals"), posts)
            deal_call = next(c for c in zoho.calls if c["method"] == "POST" and c["path"] == "/crm/v8/Deals")
            self.assertEqual(deal_call["body"]["data"][0]["Stage"], "Qualification")
        finally:
            tmp.cleanup()

    def test_unqualified_lead_does_not_promote(self) -> None:
        workflow = """
id: test.no-promote
name: No promote
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.lead.synced]
steps:
  - id: qualify
    action: lifecycle.qualify_lead
    with:
      lead: "{{ event.payload.lead }}"
  - id: promote
    action: lifecycle.crm_promote_lead
    with:
      lead: "{{ event.payload.lead }}"
      qualification: "{{ steps.qualify }}"
"""
        ai_payload = {
            "qualified": False,
            "confidence": 0.99,
            "summary": "Vendor solicitation.",
            "service_type": None,
            "language": "en",
            "priority": "low",
            "recommended_next_action": "manual_review",
            "missing_information": [],
            "reason": "Not a customer inquiry.",
        }
        tmp, store, engine, zoho, _ = self._engine(workflow, ai_payload)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.lead.synced",
                    source="unit-test",
                    payload={"lead": {"source": "email", "email": "sales@vendor.example", "last_name": "Vendor"}},
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            self.assertFalse(run["steps"][1]["result"]["promoted"])
            self.assertFalse(any(c["method"] != "GET" for c in zoho.calls))
        finally:
            tmp.cleanup()

    def test_email_analysis_saves_draft_not_send(self) -> None:
        workflow = """
id: test.email
name: Email
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.email.received]
steps:
  - id: resolve
    action: lifecycle.crm_resolve_email_party
    with:
      email: "{{ event.payload.sender_email }}"
  - id: analyze
    action: lifecycle.analyze_email
    with:
      email: "{{ event.payload }}"
  - id: draft
    action: lifecycle.mail_save_draft
    with:
      email: "{{ event.payload }}"
      analysis: "{{ steps.analyze }}"
"""
        ai_payload = {
            "category": "lead",
            "urgency": "normal",
            "summary": "Customer asks about cameras.",
            "requires_reply": True,
            "suggested_subject": "Re: Camera installation",
            "suggested_reply": "Bonjour, merci pour votre message.",
            "language": "fr",
            "service_type": "Cameras",
            "extracted_address": None,
            "requested_dates": [],
            "action_items": ["Reply"],
            "confidence": 0.9,
        }
        tmp, store, engine, zoho, _ = self._engine(workflow, ai_payload)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.email.received",
                    source="unit-test",
                    payload={
                        "mailbox_account_id": "1083319000000008002",
                        "mailbox_address": "info@opticable.ca",
                        "message_id": "m1",
                        "sender_email": "client@example.com",
                        "subject": "Camera installation",
                        "body": "Bonjour, pouvez-vous installer des caméras?",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            mail_call = next(c for c in zoho.calls if c["service"] == "mail" and c["method"] == "POST")
            self.assertEqual(mail_call["body"]["mode"], "draft")
            self.assertEqual(mail_call["body"]["fromAddress"], "info@opticable.ca")
            self.assertEqual(mail_call["body"]["toAddress"], "client@example.com")
        finally:
            tmp.cleanup()

    def test_meeting_requires_valid_window_and_creates_event(self) -> None:
        workflow = """
id: test.meeting
name: Meeting
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.meeting.requested]
steps:
  - id: create
    action: lifecycle.crm_create_meeting
    with:
      meeting: "{{ event.payload }}"
"""
        tmp, store, engine, zoho, _ = self._engine(workflow, {})
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.meeting.requested",
                    source="unit-test",
                    payload={
                        "title": "Site visit",
                        "start_datetime": "2026-10-01T13:00:00-04:00",
                        "end_datetime": "2026-10-01T14:00:00-04:00",
                        "contact_id": "123",
                        "deal_id": "456",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            event_call = next(c for c in zoho.calls if c["path"] == "/crm/v8/Events")
            record = event_call["body"]["data"][0]
            self.assertEqual(record["Who_Id"], "123")
            self.assertEqual(record["What_Id"], "456")
            self.assertEqual(record["$se_module"], "Deals")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
