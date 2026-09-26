from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.lifecycle import register_lifecycle_actions
from workflow.automation.store import AutomationStore
from workflow.customer_lifecycle import lead_event_idempotency_key, normalize_lead
from workflow.zoho_gateway import ZohoGatewayClient, is_books_api_path


class FakeZohoClient:
    def __init__(self, *, existing: dict | None = None) -> None:
        self.existing = existing
        self.calls: list[dict] = []
        self.next_id = 100

    def request(self, service, method, path, **kwargs):
        self.calls.append(
            {
                "service": service,
                "method": method,
                "path": path,
                **kwargs,
            }
        )
        if method == "GET" and path.endswith("/search"):
            return {"data": {"data": [self.existing] if self.existing else []}}
        if method in {"POST", "PUT"}:
            self.next_id += 1
            record_id = str(self.existing.get("id")) if method == "PUT" and self.existing else str(self.next_id)
            return {
                "data": {
                    "data": [
                        {
                            "code": "SUCCESS",
                            "details": {"id": record_id},
                        }
                    ]
                }
            }
        raise AssertionError(f"Unexpected fake request: {method} {path}")


class CustomerLifecycleTests(unittest.TestCase):
    def test_normalize_lead_preserves_attribution_and_identity(self) -> None:
        lead = normalize_lead(
            {
                "source": "website",
                "inquiry_id": "inq-123",
                "full_name": " Jane Doe ",
                "company": "Example Inc.",
                "email": " Jane.Doe@Example.COM ",
                "phone": "(514) 555-0100",
                "service_type": "Structured cabling",
                "attribution": {
                    "source": "google",
                    "medium": "cpc",
                    "campaign": "cabling-montreal",
                    "gclid": "abc123",
                },
            }
        )
        self.assertEqual(lead["first_name"], "Jane")
        self.assertEqual(lead["last_name"], "Doe")
        self.assertEqual(lead["email"], "jane.doe@example.com")
        self.assertEqual(lead["phone"], "5145550100")
        self.assertEqual(lead["attribution"]["campaign"], "cabling-montreal")
        self.assertEqual(len(lead["identity_hash"]), 64)

    def test_idempotency_prefers_inquiry_then_source_record(self) -> None:
        self.assertEqual(
            lead_event_idempotency_key(
                {"source": "website", "inquiry_id": "abc", "email": "a@example.com"}
            ),
            "lead:website:inquiry:abc",
        )
        self.assertEqual(
            lead_event_idempotency_key(
                {"source": "meta", "source_record_id": "42", "email": "a@example.com"}
            ),
            "lead:meta:record:42",
        )
        self.assertIsNone(
            lead_event_idempotency_key({"source": "manual", "email": "a@example.com"})
        )

    def test_lead_workflow_creates_crm_record_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "lead.yaml").write_text(
                """
id: test.lifecycle
name: Lifecycle
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.lead.received]
steps:
  - id: normalize
    action: lifecycle.normalize_lead
    with:
      lead: "{{ event.payload }}"
  - id: crm
    action: lifecycle.crm_upsert_lead
    with:
      lead: "{{ steps.normalize.lead }}"
  - id: task
    action: lifecycle.crm_create_followup_task
    with:
      lead_id: "{{ steps.crm.lead_id }}"
      lead: "{{ steps.normalize.lead }}"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            store = AutomationStore(root / "automation.db")
            engine = AutomationEngine(store, workflows)
            fake = FakeZohoClient()
            register_lifecycle_actions(engine, fake, store)
            engine.sync_definitions()

            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.lead.received",
                    source="unit-test",
                    payload={
                        "source": "website",
                        "inquiry_id": "inq-1",
                        "full_name": "Jane Doe",
                        "email": "jane@example.com",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            methods_paths = [(call["method"], call["path"]) for call in fake.calls]
            self.assertIn(("POST", "/crm/v8/Leads"), methods_paths)
            self.assertIn(("POST", "/crm/v8/Tasks"), methods_paths)

    def test_existing_lead_is_updated_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "lead.yaml").write_text(
                """
id: test.lifecycle.update
name: Lifecycle update
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.lead.received]
steps:
  - id: normalize
    action: lifecycle.normalize_lead
    with:
      lead: "{{ event.payload }}"
  - id: crm
    action: lifecycle.crm_upsert_lead
    with:
      lead: "{{ steps.normalize.lead }}"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            store = AutomationStore(root / "automation.db")
            engine = AutomationEngine(store, workflows)
            fake = FakeZohoClient(existing={"id": "9001", "Inquiry_ID": "inq-2"})
            register_lifecycle_actions(engine, fake, store)
            engine.sync_definitions()
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.lead.received",
                    source="unit-test",
                    payload={
                        "source": "website",
                        "inquiry_id": "inq-2",
                        "full_name": "John Smith",
                        "email": "john@example.com",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            methods_paths = [(call["method"], call["path"]) for call in fake.calls]
            self.assertIn(("PUT", "/crm/v8/Leads/9001"), methods_paths)
            self.assertNotIn(("POST", "/crm/v8/Leads"), methods_paths)

    def test_books_api_path_detection(self) -> None:
        self.assertTrue(is_books_api_path("zohoapis", "/books/v3/invoices"))
        self.assertTrue(is_books_api_path("zohoapis", "/BOOKS/v3/contacts"))
        self.assertFalse(is_books_api_path("zohoapis", "/crm/v8/Leads"))
        self.assertFalse(is_books_api_path("sign", "/books/v3/invoices"))

    def test_books_mutation_is_always_blocked(self) -> None:
        settings = SimpleNamespace(timeout_seconds=10, standby_enabled=False)
        oauth = SimpleNamespace()
        client = ZohoGatewayClient(settings, oauth)
        with self.assertRaisesRegex(Exception, "read-only by Opticable policy"):
            client._validate(
                "zohoapis", "POST", "/books/v3/invoices", None,
                "even an explicitly confirmed mutation remains blocked", True,
            )



if __name__ == "__main__":
    unittest.main()
