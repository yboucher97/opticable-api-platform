from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.lifecycle_sign import register_lifecycle_sign_actions
from workflow.automation.store import AutomationStore


class FakeSignZoho:
    def __init__(self, *, existing_request_id: str | None = None, sign_status: str = "inprogress") -> None:
        self.existing_request_id = existing_request_id
        self.sign_status = sign_status
        self.calls: list[dict] = []

    def request(self, service, method, path, **kwargs):
        self.calls.append({"service": service, "method": method, "path": path, **kwargs})

        if service == "zohoapis" and method == "GET" and path.startswith("/crm/v8/Services/"):
            return {
                "data": {
                    "data": [
                        {
                            "id": path.rsplit("/", 1)[-1],
                            "Sign_Request_ID": self.existing_request_id,
                        }
                    ]
                }
            }

        if service == "sign" and method == "GET" and path.startswith("/templates/"):
            template_id = path.rsplit("/", 1)[-1]
            return {
                "data": {
                    "code": 0,
                    "templates": {
                        "template_id": template_id,
                        "template_name": "approved",
                        "actions": [
                            {
                                "action_id": "action-1",
                                "role": "Signataire",
                                "action_type": "SIGN",
                                "signing_order": 1,
                                "recipient_email": "",
                                "recipient_name": "",
                                "verify_recipient": False,
                            }
                        ],
                    },
                }
            }

        if service == "sign" and method == "POST" and path.endswith("/createdocument"):
            return {
                "status": 200,
                "data": {
                    "code": 0,
                    "requests": {
                        "request_id": "request-123",
                        "request_status": "inprogress",
                    },
                },
            }

        if service == "sign" and method == "GET" and path.startswith("/requests/"):
            return {
                "data": {
                    "code": 0,
                    "requests": {
                        "request_id": path.rsplit("/", 1)[-1],
                        "request_status": self.sign_status,
                        "sign_submitted_time": 1790370000000,
                    },
                }
            }

        if service == "zohoapis" and method == "PUT":
            return {
                "status": 200,
                "data": {"data": [{"code": "SUCCESS", "details": {"id": path.rsplit("/", 1)[-1]}}]},
            }

        raise AssertionError(f"Unexpected request: {service} {method} {path}")


class LifecycleSignTests(unittest.TestCase):
    def _engine(self, workflow: str, fake: FakeSignZoho):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        workflows = root / "workflows"
        workflows.mkdir()
        (workflows / "workflow.yaml").write_text(workflow.strip() + "\n", encoding="utf-8")
        store = AutomationStore(root / "automation.db")
        engine = AutomationEngine(store, workflows)
        register_lifecycle_sign_actions(engine, fake, store)
        engine.sync_definitions()
        return tmp, store, engine

    def test_installation_contract_send_links_service_and_advances_deal(self) -> None:
        workflow = """
id: test.contract-send
name: Contract send
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.contract.requested]
steps:
  - id: send
    action: lifecycle.sign_send_contract
    with:
      contract: "{{ event.payload }}"
"""
        fake = FakeSignZoho()
        tmp, store, engine = self._engine(workflow, fake)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.contract.requested",
                    source="unit-test",
                    payload={
                        "contract_type": "installation",
                        "recipient_name": "Jane Doe",
                        "recipient_email": "jane@example.com",
                        "service_id": "svc-1",
                        "deal_id": "deal-1",
                        "field_text_data": {
                            "Numero Service": "S-100",
                            "reference soumission": "Q-100",
                            "Nom du site": "Example",
                            "Adresse du site": "123 Main",
                            "Nom Authorisé Opticable": "Jane Doe",
                        },
                        "field_date_data": {"Date": "25 September 2026"},
                        "field_boolean_data": {},
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            sign_post = next(c for c in fake.calls if c["service"] == "sign" and c["method"] == "POST")
            self.assertEqual(sign_post["content_type"], "application/x-www-form-urlencoded")
            service_update = next(c for c in fake.calls if c["path"] == "/crm/v8/Services/svc-1" and c["method"] == "PUT")
            self.assertEqual(service_update["body"]["data"][0]["Service_Stage"], "Contract Sent")
            self.assertEqual(service_update["body"]["data"][0]["Sign_Request_ID"], "request-123")
            deal_update = next(c for c in fake.calls if c["path"] == "/crm/v8/Deals/deal-1")
            self.assertEqual(deal_update["body"]["data"][0]["Stage"], "Contracts In Progress")
        finally:
            tmp.cleanup()

    def test_existing_service_sign_request_prevents_duplicate_send(self) -> None:
        workflow = """
id: test.contract-dedupe
name: Contract dedupe
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.contract.requested]
steps:
  - id: send
    action: lifecycle.sign_send_contract
    with:
      contract: "{{ event.payload }}"
"""
        fake = FakeSignZoho(existing_request_id="existing-999")
        tmp, store, engine = self._engine(workflow, fake)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.contract.requested",
                    source="unit-test",
                    payload={
                        "contract_type": "installation",
                        "recipient_name": "Jane Doe",
                        "recipient_email": "jane@example.com",
                        "service_id": "svc-1",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["steps"][0]["result"]["request_id"], "existing-999")
            self.assertFalse(any(c["service"] == "sign" and c["method"] == "POST" for c in fake.calls))
        finally:
            tmp.cleanup()

    def test_completed_installation_contract_updates_service_and_deal_and_emits_signed(self) -> None:
        workflow = """
id: test.contract-status
name: Contract status
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.contract.status_check]
steps:
  - id: sync
    action: lifecycle.sign_sync_status
    with:
      status: "{{ event.payload }}"
"""
        fake = FakeSignZoho(sign_status="completed")
        tmp, store, engine = self._engine(workflow, fake)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.contract.status_check",
                    source="unit-test",
                    payload={
                        "request_id": "request-123",
                        "contract_type": "installation",
                        "service_id": "svc-1",
                        "deal_id": "deal-1",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            service_update = next(c for c in fake.calls if c["path"] == "/crm/v8/Services/svc-1")
            self.assertEqual(service_update["body"]["data"][0]["Service_Stage"], "Contract Signed")
            deal_update = next(c for c in fake.calls if c["path"] == "/crm/v8/Deals/deal-1")
            self.assertEqual(deal_update["body"]["data"][0]["Stage"], "Contracts Signed")
            events = store.recent_audit(50)
            self.assertTrue(any(item["action"] == "contract_status_synced" for item in events))
        finally:
            tmp.cleanup()

    def test_completed_general_terms_updates_account(self) -> None:
        workflow = """
id: test.general-terms-status
name: General terms status
version: 1
enabled: true
trigger:
  event_types: [customer.lifecycle.contract.status_check]
steps:
  - id: sync
    action: lifecycle.sign_sync_status
    with:
      status: "{{ event.payload }}"
"""
        fake = FakeSignZoho(sign_status="completed")
        tmp, store, engine = self._engine(workflow, fake)
        try:
            response = engine.ingest(
                AutomationEvent(
                    event_type="customer.lifecycle.contract.status_check",
                    source="unit-test",
                    payload={
                        "request_id": "request-gt",
                        "contract_type": "general_terms",
                        "account_id": "acct-1",
                        "contact_id": "contact-1",
                    },
                )
            )
            run = store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")
            account_update = next(c for c in fake.calls if c["path"] == "/crm/v8/Accounts/acct-1")
            record = account_update["body"]["data"][0]
            self.assertIn("General_Terms_Signed", record)
            self.assertEqual(record["General_Terms_Signer"], {"id": "contact-1"})
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
