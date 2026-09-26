from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.lifecycle_phase2 import register_lifecycle_phase2_actions
from workflow.automation.store import AutomationStore
from workflow.zoho_gateway import ZohoGatewayClient, ZohoGatewayError, is_books_synced_crm_path


class FakeAi:
    def __init__(self, text: str = "Digest summary") -> None:
        self.text = text
        self.calls: list[dict] = []

    def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return {"provider": "openai", "model": "test-model", "text": self.text}


class FakeZoho:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.counter = 1000

    def request(self, service, method, path, **kwargs):
        self.calls.append({"service": service, "method": method, "path": path, **kwargs})
        if path.startswith("/books/") and method != "GET":
            raise AssertionError("Books mutation attempted")
        if method == "GET" and path == "/books/v3/invoices":
            return {"data": {"invoices": [{"status": "overdue", "total": 500, "balance": 200}], "page_context": {"has_more_page": False}}}
        if method == "GET" and path == "/books/v3/estimates":
            return {"data": {"estimates": [{"status": "sent", "total": 1000}], "page_context": {"has_more_page": False}}}
        if method == "GET" and path == "/books/v3/customerpayments":
            return {"data": {"customerpayments": [{"status": "paid", "amount": 300}], "page_context": {"has_more_page": False}}}
        if method == "GET" and path.startswith("/crm/v8/"):
            return {"data": {"data": []}}
        if method == "GET" and path == "/templates/325018000000115116":
            return {
                "data": {
                    "templates": {
                        "template_name": "02-contrat-installation",
                        "actions": [{"role": "Signataire", "action_type": "SIGN", "action_id": "a1", "signing_order": 1}],
                        "document_fields": [
                            {
                                "fields": [
                                    {"field_category": "textfield", "field_label": "Numero Service", "is_mandatory": True},
                                    {"field_category": "datefield", "field_label": "Date", "is_mandatory": True},
                                ]
                            }
                        ],
                    }
                }
            }
        if method == "GET" and path == "/templates/325018000000115001":
            return {"data": {"templates": {"template_name": "01-conditions-generales", "actions": [{"role": "Signataire", "action_type": "SIGN", "action_id": "a2", "signing_order": 1}], "document_fields": []}}}
        if method == "POST" and path == "/crm/v8/Tasks":
            self.counter += 1
            return {"data": {"data": [{"code": "SUCCESS", "details": {"id": str(self.counter)}}]}}
        if method == "POST" and path.endswith("/createdocument"):
            return {"data": {"requests": {"request_id": "sig-1", "request_status": "inprogress"}}}
        if method == "POST" and service == "mail":
            return {"status": 201, "data": {"message": "draft saved"}}
        raise AssertionError(f"Unexpected fake request: {service} {method} {path}")


class LifecyclePhase2Tests(unittest.TestCase):
    def _run(self, workflow: str, event: AutomationEvent, *, ai_text: str = "Digest summary"):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        workflows = root / "workflows"
        workflows.mkdir()
        (workflows / "workflow.yaml").write_text(workflow.strip() + "\n", encoding="utf-8")
        store = AutomationStore(root / "automation.db")
        engine = AutomationEngine(store, workflows)
        zoho = FakeZoho()
        ai = FakeAi(ai_text)
        register_lifecycle_phase2_actions(engine, zoho, ai, store)
        engine.sync_definitions()
        response = engine.ingest(event)
        run = store.get_run(response.run_ids[0])
        return tmp, run, zoho, ai

    def test_books_synced_crm_modules_are_recognized_and_blocked(self) -> None:
        self.assertTrue(is_books_synced_crm_path("zohoapis", "/crm/v8/CustomModule5001/123"))
        self.assertTrue(is_books_synced_crm_path("zohoapis", "/crm/v8/CustomModule5002"))
        self.assertFalse(is_books_synced_crm_path("zohoapis", "/crm/v8/Quotes"))
        client = ZohoGatewayClient(SimpleNamespace(timeout_seconds=10, standby_enabled=False), SimpleNamespace())
        with self.assertRaisesRegex(ZohoGatewayError, "read-only"):
            client._validate("zohoapis", "PUT", "/crm/v8/CustomModule5001/123", None, "test", True)

    def test_books_observation_uses_get_only(self) -> None:
        workflow = """
id: test.books
name: Books observe
version: 1
enabled: true
trigger:
  event_types: [test.books]
steps:
  - id: observe
    action: lifecycle.books_observe
    with:
      request: "{{ event.payload }}"
"""
        tmp, run, zoho, _ = self._run(workflow, AutomationEvent(event_type="test.books", source="unit", payload={"organization_id": "802337532"}))
        try:
            self.assertEqual(run["status"], "completed")
            result = run["steps"][0]["result"]
            self.assertEqual(result["access"], "read_only")
            self.assertEqual(result["mutations_performed"], 0)
            self.assertEqual(result["invoices"]["balance"], 200.0)
            self.assertTrue(all(c["method"] == "GET" for c in zoho.calls if c["path"].startswith("/books/")))
        finally:
            tmp.cleanup()

    def test_quote_request_creates_crm_task_without_books_write(self) -> None:
        workflow = """
id: test.quote
name: Quote review
version: 1
enabled: true
trigger:
  event_types: [test.quote]
steps:
  - id: quote
    action: lifecycle.crm_create_quote_review_task
    with:
      quote: "{{ event.payload }}"
"""
        tmp, run, zoho, _ = self._run(workflow, AutomationEvent(event_type="test.quote", source="unit", payload={"deal_id": "d1", "service_summary": "Cabling"}))
        try:
            self.assertEqual(run["status"], "completed")
            self.assertTrue(any(c["path"] == "/crm/v8/Tasks" and c["method"] == "POST" for c in zoho.calls))
            self.assertFalse(any(c["path"].startswith("/books/") and c["method"] != "GET" for c in zoho.calls))
        finally:
            tmp.cleanup()

    def test_contract_send_requires_approval_before_network(self) -> None:
        workflow = """
id: test.contract.block
name: Contract blocked
version: 1
enabled: true
trigger:
  event_types: [test.contract]
steps:
  - id: contract
    action: lifecycle.sign_send_contract
    with:
      contract: "{{ event.payload }}"
"""
        event = AutomationEvent(event_type="test.contract", source="unit", payload={"template": "installation", "recipient_name": "Jane Doe", "recipient_email": "jane@example.com", "request_name": "Install", "approved_to_send": False})
        tmp, run, zoho, _ = self._run(workflow, event)
        try:
            self.assertEqual(run["status"], "failed")
            self.assertEqual(zoho.calls, [])
        finally:
            tmp.cleanup()

    def test_contract_send_validates_prefill_and_quicksends_after_approval(self) -> None:
        workflow = """
id: test.contract.send
name: Contract send
version: 1
enabled: true
trigger:
  event_types: [test.contract.send]
steps:
  - id: contract
    action: lifecycle.sign_send_contract
    with:
      contract: "{{ event.payload }}"
"""
        payload = {"template": "installation", "recipient_name": "Jane Doe", "recipient_email": "jane@example.com", "request_name": "Installation agreement", "approved_to_send": True, "field_text_data": {"Numero Service": "S-100"}, "field_date_data": {"Date": "2026-09-26"}}
        tmp, run, zoho, _ = self._run(workflow, AutomationEvent(event_type="test.contract.send", source="unit", payload=payload))
        try:
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["steps"][0]["result"]["request_id"], "sig-1")
            post = next(c for c in zoho.calls if c["method"] == "POST" and c["path"].endswith("/createdocument"))
            self.assertEqual(post["content_type"], "application/x-www-form-urlencoded")
            self.assertEqual(post["body"]["is_quicksend"], "true")
            decoded = json.loads(post["body"]["data"])
            self.assertEqual(decoded["templates"]["actions"][0]["recipient_email"], "jane@example.com")
        finally:
            tmp.cleanup()

    def test_digest_reads_finance_and_saves_draft_only(self) -> None:
        workflow = """
id: test.digest
name: Digest
version: 1
enabled: true
trigger:
  event_types: [test.digest]
steps:
  - id: digest
    action: lifecycle.build_digest
    with:
      request: "{{ event.payload }}"
"""
        payload = {"period": "daily", "organization_id": "802337532", "mailbox_account_id": "1083319000000008002", "from_address": "yboucher@opticable.ca", "recipient": "yboucher@opticable.ca", "create_mail_draft": True}
        tmp, run, zoho, _ = self._run(workflow, AutomationEvent(event_type="test.digest", source="unit", payload=payload), ai_text="Priorities\n- Review overdue invoice")
        try:
            self.assertEqual(run["status"], "completed")
            result = run["steps"][0]["result"]
            self.assertTrue(result["drafted"])
            self.assertEqual(result["books_access"], "read_only")
            self.assertTrue(all(c["method"] == "GET" for c in zoho.calls if c["path"].startswith("/books/")))
            mail = next(c for c in zoho.calls if c["service"] == "mail")
            self.assertEqual(mail["body"]["mode"], "draft")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
