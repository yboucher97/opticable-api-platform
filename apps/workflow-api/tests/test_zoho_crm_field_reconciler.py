from __future__ import annotations

import unittest

from workflow.automation.desired_state import DesiredResource
from workflow.automation.reconcilers.zoho_crm import ZohoCrmFieldReconciler


class FakeGateway:
    def __init__(self, fields=None):
        self.fields = list(fields or [])
        self.calls = []

    def request(self, service, method, path, **kwargs):
        self.calls.append((service, method, path, kwargs))
        if method == "GET":
            return {"ok": True, "status": 200, "data": {"fields": self.fields}}
        return {"ok": True, "status": 200, "request_id": "req-1", "data": {}}


class ZohoCrmFieldReconcilerTests(unittest.TestCase):
    def resource(self, **overrides):
        data = {
            "id": "zoho.crm.field.leads.service_interest",
            "provider": "zoho_crm",
            "kind": "field",
            "name": "Service Interest",
            "desired": {
                "module": "Leads",
                "api_name": "Service_Interest",
                "field_label": "Service Interest",
                "data_type": "picklist",
                "pick_list_values": ["Cabling", "Wi-Fi"],
            },
        }
        data.update(overrides)
        return DesiredResource(**data)

    def test_missing_field_plans_create(self):
        reconciler = ZohoCrmFieldReconciler(FakeGateway())
        change = reconciler.plan(self.resource())
        self.assertEqual(change.action, "create")
        self.assertEqual(change.risk, "low")

    def test_matching_field_is_noop(self):
        gateway = FakeGateway([
            {
                "id": "123",
                "api_name": "Service_Interest",
                "field_label": "Service Interest",
                "data_type": "picklist",
                "pick_list_values": [
                    {"display_value": "Cabling"},
                    {"display_value": "Wi-Fi"},
                ],
                "custom_field": True,
            }
        ])
        reconciler = ZohoCrmFieldReconciler(gateway)
        change = reconciler.plan(self.resource())
        self.assertEqual(change.action, "noop")

    def test_picklist_drift_plans_update(self):
        gateway = FakeGateway([
            {
                "id": "123",
                "api_name": "Service_Interest",
                "field_label": "Service Interest",
                "data_type": "picklist",
                "pick_list_values": [{"display_value": "Cabling"}],
                "custom_field": True,
            }
        ])
        reconciler = ZohoCrmFieldReconciler(gateway)
        change = reconciler.plan(self.resource())
        self.assertEqual(change.action, "update")
        self.assertEqual(change.risk, "medium")

    def test_data_type_change_is_high_risk(self):
        gateway = FakeGateway([
            {
                "id": "123",
                "api_name": "Service_Interest",
                "field_label": "Service Interest",
                "data_type": "text",
                "pick_list_values": [],
                "custom_field": True,
            }
        ])
        reconciler = ZohoCrmFieldReconciler(gateway)
        change = reconciler.plan(self.resource())
        self.assertEqual(change.action, "update")
        self.assertEqual(change.risk, "high")
        self.assertTrue(change.requires_confirmation)

    def test_absent_custom_field_plans_destructive_delete(self):
        gateway = FakeGateway([
            {
                "id": "123",
                "api_name": "Service_Interest",
                "field_label": "Service Interest",
                "data_type": "picklist",
                "custom_field": True,
            }
        ])
        reconciler = ZohoCrmFieldReconciler(gateway)
        resource = self.resource(lifecycle={"ensure": "absent"})
        change = reconciler.plan(resource)
        self.assertEqual(change.action, "delete")
        self.assertEqual(change.risk, "destructive")

    def test_standard_field_delete_is_blocked(self):
        gateway = FakeGateway([
            {
                "id": "123",
                "api_name": "Company",
                "field_label": "Company",
                "data_type": "text",
                "custom_field": False,
            }
        ])
        reconciler = ZohoCrmFieldReconciler(gateway)
        resource = DesiredResource(
            id="zoho.crm.field.leads.company",
            provider="zoho_crm",
            kind="field",
            name="Company",
            desired={"module": "Leads", "api_name": "Company", "field_label": "Company"},
            lifecycle={"ensure": "absent"},
        )
        change = reconciler.plan(resource)
        self.assertEqual(change.action, "blocked")

    def test_create_apply_uses_settings_fields_endpoint(self):
        gateway = FakeGateway()
        reconciler = ZohoCrmFieldReconciler(gateway)
        resource = self.resource()
        change = reconciler.plan(resource)
        result = reconciler.apply(resource, change)
        self.assertTrue(result.changed)
        service, method, path, kwargs = gateway.calls[-1]
        self.assertEqual((service, method, path), ("zohoapis", "POST", "/crm/v8/settings/fields"))
        self.assertEqual(kwargs["query"]["module"], "Leads")
        self.assertTrue(kwargs["confirm"])


if __name__ == "__main__":
    unittest.main()
