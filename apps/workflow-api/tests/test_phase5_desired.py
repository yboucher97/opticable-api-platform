from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from workflow.automation.crm_inventory import CrmInventoryCollector, drift, entry, normalize, snapshot
from workflow.automation.desired_journal import ApplyConflict, resource_key
from workflow.automation.desired_state import DesiredResource, DesiredStateController, DesiredStateDocument, DesiredStateRegistry
from workflow.automation.reconcilers.zoho_crm import ZohoCrmFieldReconciler
from workflow.automation.reconcilers.zoho_metadata import ZohoCrmMetadataReconciler, register_crm_metadata
from workflow.automation.store import AutomationStore


class CrmFake:
    def __init__(self):
        self.fields, self.metadata, self.calls = [], [], []
        self.error = None
        self.accept_then_lose = False
        self.verify_wrong = False
        self.on_read = None

    def request(self, service, method, path, **kwargs):
        self.calls.append((method, path, copy.deepcopy(kwargs)))
        collection = "fields" if "/fields" in path else ("layouts" if "/layouts" in path else "workflow_rules")
        if method == "GET":
            if self.on_read:
                self.on_read()
            return {"ok": True, "status": 200, "data": {collection: copy.deepcopy(self.fields if collection == "fields" else self.metadata)}}
        if self.error:
            raise self.error
        if not self.verify_wrong:
            if collection == "fields":
                self.fields.append({"id": "123", "custom_field": True, **kwargs["body"]["fields"][0]})
            elif method == "PATCH":
                self.metadata[0]["sections"].extend(kwargs["body"][collection][0]["sections"])
            elif method == "PUT":
                self.metadata[0].update(kwargs["body"][collection][0])
            else:
                self.metadata.append({"id": "123", **kwargs["body"][collection][0]})
        if self.accept_then_lose:
            raise httpx.ReadTimeout("lost response")
        return {"ok": True, "status": 200, "request_id": "request-evidence-only", "data": {collection: [{"status": "success", "details": {"id": "123"}}]}}

    @property
    def writes(self):
        return [x for x in self.calls if x[0] != "GET"]


def field_doc():
    return DesiredStateDocument(name="fixture", resources=[DesiredResource(id="lead.next", provider="zoho_crm", kind="field", name="Next Followup At",
        identity={"module": "Leads", "api_name": "Next_Followup_At"},
        desired={"module": "Leads", "api_name": "Next_Followup_At", "field_label": "Next Followup At", "data_type": "datetime"})])


class DesiredHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.client = CrmFake()
        self.registry = DesiredStateRegistry()
        self.registry.register("zoho_crm", "field", ZohoCrmFieldReconciler(self.client))
        self.controller = DesiredStateController(self.registry, self.store)
        self.document = field_doc()

    def test_additive_creation_verified_and_durable_duplicate_noop(self):
        plan = self.controller.plan(self.document)
        results = self.controller.apply(self.document, plan, low_risk_additive_only=True)
        self.assertEqual(results[0].status, "completed")
        self.assertTrue(results[0].result["verification"])
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.controller.plan(self.document).summary, {"noop": 1})
        restarted = DesiredStateController(self.registry, AutomationStore(self.store.db_path))
        restarted.apply(self.document, restarted.plan(self.document))
        self.assertEqual(len(self.client.writes), 1)
        audit = self.store.recent_audit()
        started = next(a["metadata"] for a in audit if a["action"] == "started")
        for key in ("document_hash", "plan_hash", "before_hash", "desired_hash", "risk", "provider", "kind"):
            self.assertIn(key, started)
        self.assertEqual(self.store._connect().execute("PRAGMA user_version").fetchone()[0], 2)

    def test_stable_hash_dictionary_order_and_version_sensitivity(self):
        first = self.controller.plan(self.document)
        raw = self.document.model_dump()
        raw["resources"][0]["desired"] = dict(reversed(list(raw["resources"][0]["desired"].items())))
        second = self.controller.plan(DesiredStateDocument.model_validate(raw))
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.document.version += 1
        with self.assertRaisesRegex(ValueError, "document changed"):
            self.controller.apply(self.document, first)
        self.assertFalse(self.client.writes)

    def test_tampered_plan_rejected(self):
        plan = self.controller.plan(self.document)
        plan.changes[0].risk = "high"
        with self.assertRaisesRegex(ValueError, "digest"):
            self.controller.apply(self.document, plan)
        self.assertFalse(self.client.writes)

    def test_stale_plan_rejected_before_any_write(self):
        plan = self.controller.plan(self.document)
        self.client.fields = [{"id": "123", "custom_field": True, **self.document.resources[0].desired}]
        with self.assertRaisesRegex(ValueError, "Stale plan"):
            self.controller.apply(self.document, plan)
        self.assertFalse(self.client.writes)

    def test_drift_immediately_before_mutation_rejected(self):
        plan = self.controller.plan(self.document)
        count = 0
        def drift_on_second_read():
            nonlocal count
            count += 1
            if count == 2:
                self.client.fields.append({"id": "123", "api_name": "Next_Followup_At", "field_label": "Next Followup At", "data_type": "text"})
        self.client.on_read = drift_on_second_read
        with self.assertRaisesRegex(ValueError, "immediately"):
            self.controller.apply(self.document, plan)
        self.assertFalse(self.client.writes)

    def test_provider_accepted_response_lost_remains_manual_across_restart(self):
        self.client.accept_then_lose = True
        first = self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(first[0].status, "manual")
        self.assertEqual(len(self.client.writes), 1)
        self.client.accept_then_lose = False
        restarted = DesiredStateController(self.registry, AutomationStore(self.store.db_path))
        second = restarted.apply(self.document, restarted.plan(self.document))
        self.assertEqual(second[0].status, "manual")
        self.assertEqual(len(self.client.writes), 1)

    def test_all_provider_failures_are_never_blindly_repeated(self):
        for exc in (httpx.ConnectTimeout("before send"), httpx.ReadTimeout("possible send"),
                    httpx.ConnectError("connection"), RuntimeError("request-evidence-only")):
            with self.subTest(exception=type(exc).__name__):
                controller = DesiredStateController(self.registry)
                self.client.error = exc
                result = controller.apply(self.document, controller.plan(self.document))
                self.assertEqual(result[0].status, "manual")
                before = len(self.client.writes)
                controller.apply(self.document, controller.plan(self.document))
                self.assertEqual(len(self.client.writes), before)

    def test_provider_401_429_5xx_remain_manual_without_retry(self):
        for status in (401, 429, 500, 503):
            with self.subTest(status=status):
                self.client.error = httpx.HTTPStatusError("provider error", request=httpx.Request("POST", "https://example.test"),
                    response=httpx.Response(status, headers={"Retry-After": "10"}))
                c = DesiredStateController(self.registry)
                result = c.apply(self.document, c.plan(self.document))
                self.assertEqual(result[0].status, "manual")
                before = len(self.client.writes)
                c.apply(self.document, c.plan(self.document))
                self.assertEqual(len(self.client.writes), before)

    def test_verification_failure_request_id_is_no_retry_permission(self):
        self.client.verify_wrong = True
        result = self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(result[0].status, "manual")
        self.assertEqual(result[0].result["request_id"], "request-evidence-only")
        self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(len(self.client.writes), 1)

    def test_restart_between_intent_and_provider_call_fails_closed(self):
        self.controller.journal.record("started", resource_key(self.document.resources[0]), {}, "fixture")
        restarted = DesiredStateController(self.registry, AutomationStore(self.store.db_path))
        self.assertEqual(restarted.apply(self.document, restarted.plan(self.document))[0].status, "manual")
        self.assertFalse(self.client.writes)

    def test_concurrent_controllers_are_serialized_by_process_lock(self):
        other = DesiredStateController(self.registry, AutomationStore(self.store.db_path))
        with self.controller.journal.lock():
            with self.assertRaises(ApplyConflict):
                other.apply(self.document, other.plan(self.document))
        self.assertFalse(self.client.writes)

    def test_duplicate_semantic_field_blocks_creation(self):
        self.client.fields = [{"id": "5", "api_name": "NextAction", "field_label": "next-followup_at", "data_type": "datetime"}]
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.assertFalse(self.client.writes)

    def test_field_collision_between_api_and_label(self):
        self.client.fields = [{"id": "5", "api_name": "Next_Followup_At", "field_label": "Other"},
                              {"id": "6", "api_name": "Other", "field_label": "Next Followup At"}]
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})

    def test_failed_field_read_does_not_mean_absent(self):
        with patch.object(self.client, "request", return_value={"ok": False, "status": 401, "data": {}}):
            self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})

    def test_field_limit_incomplete_read_is_blocked(self):
        with patch.object(self.client, "request", return_value={"ok": True, "status": 200, "data": {"fields": [], "info": {"more_records": True}}}):
            self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})

    def test_duplicate_document_identity_and_invalid_version(self):
        raw = self.document.model_dump()
        raw["api_version"] = "unrecognized"
        with self.assertRaises(ValueError):
            DesiredStateDocument.model_validate(raw)
        self.document.resources.append(self.document.resources[0].model_copy(update={"id": "alias"}))
        with self.assertRaisesRegex(ValueError, "identities"):
            self.controller.plan(self.document)

    def test_unknown_custom_field_deletion_is_blocked(self):
        self.client.fields = [{"id": "123", "api_name": "Next_Followup_At", "field_label": "Next Followup At"}]
        self.document.resources[0].lifecycle = {"ensure": "absent"}
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})

    def test_required_creation_and_reduced_length_are_high_risk(self):
        self.document.resources[0].desired["required"] = True
        self.assertEqual(self.controller.plan(self.document).changes[0].risk, "high")
        result = self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(result[0].status, "blocked")

    def test_secret_material_refused_before_plan(self):
        self.document.resources[0].desired["password"] = "do-not-persist"
        with self.assertRaises(ValueError):
            self.controller.plan(self.document)


class MetadataTests(unittest.TestCase):
    def resource(self, kind="workflow", **overrides):
        return DesiredResource(id="fixture." + kind, provider="zoho_crm", kind=kind, name="Fixture",
                               desired=overrides.pop("desired", {"name": "Fixture", "status": {"active": False}}), **overrides)

    def test_disabled_workflow_create_verify_and_noop(self):
        fake = CrmFake()
        adapter = ZohoCrmMetadataReconciler(fake, "workflow")
        r = self.resource()
        self.assertEqual(adapter.plan(r).risk, "low")
        self.assertEqual(adapter.apply(r, adapter.plan(r)).status, "completed")
        self.assertEqual(adapter.plan(r).action, "noop")

    def test_active_workflow_update_is_high_risk_and_preserved(self):
        fake = CrmFake()
        fake.metadata = [{"id": "123", "name": "Fixture", "status": {"active": True}, "conditions": [{"action": "existing"}]}]
        adapter = ZohoCrmMetadataReconciler(fake, "workflow")
        registry = DesiredStateRegistry(); registry.register("zoho_crm", "workflow", adapter)
        controller = DesiredStateController(registry)
        doc = DesiredStateDocument(name="existing", resources=[self.resource()])
        self.assertEqual(controller.plan(doc).changes[0].risk, "high")
        self.assertEqual(controller.apply(doc, controller.plan(doc))[0].status, "blocked")
        self.assertFalse(fake.writes)

    def test_approved_disabled_workflow_update_and_verify(self):
        fake = CrmFake(); fake.metadata = [{"id": "123", "name": "Fixture", "status": {"active": False}, "description": "old"}]
        registry = DesiredStateRegistry(); registry.register("zoho_crm", "workflow", ZohoCrmMetadataReconciler(fake, "workflow"))
        c = DesiredStateController(registry)
        doc = DesiredStateDocument(name="fixture", resources=[self.resource(desired={"name": "Fixture", "status": {"active": False}, "description": "new"})])
        self.assertEqual(c.apply(doc, c.plan(doc), allow_high_risk=True)[0].status, "completed")
        self.assertEqual(fake.writes[0][0], "PUT")

    def test_layout_noop_and_bounded_empty_section_additions(self):
        fake = CrmFake(); fake.metadata = [{"id": "123", "name": "Fixture", "generated_type": "custom", "sections": [{"id": "1", "display_label": "Existing", "fields": []}]}]
        adapter = ZohoCrmMetadataReconciler(fake, "layout")
        r = self.resource("layout", identity={"module": "Leads", "id": "123"}, desired={"name": "Fixture", "sections": copy.deepcopy(fake.metadata[0]["sections"])})
        self.assertEqual(adapter.plan(r).action, "noop")
        r.desired["sections"].append({"display_label": "Followup", "fields": []})
        self.assertEqual(adapter.plan(r).risk, "medium")
        self.assertEqual(adapter.apply(r, adapter.plan(r)).status, "completed")
        self.assertEqual(fake.writes[0][0], "PATCH")

    def test_layout_removal_and_large_additions_are_manual(self):
        fake = CrmFake(); fake.metadata = [{"id": "123", "name": "Fixture", "generated_type": "custom", "sections": [{"id": "1", "display_label": "Existing", "fields": []}]}]
        adapter = ZohoCrmMetadataReconciler(fake, "layout")
        r = self.resource("layout", desired={"sections": []})
        self.assertEqual(adapter.plan(r).action, "manual")
        r.desired["sections"] = fake.metadata[0]["sections"] + [{"display_label": str(i), "fields": []} for i in range(6)]
        self.assertEqual(adapter.plan(r).action, "manual")

    def test_webhook_secret_url_redaction_and_authentication_fail_closed(self):
        raw = {"url": "https://flow.test/private-secret", "headers": {"Authorization": "secret"}, "description": "governed", "parameters": {"value": "secret"}}
        redacted = normalize(raw)
        self.assertNotIn("private-secret", json.dumps(redacted)); self.assertNotIn('"secret"', json.dumps(redacted))
        self.assertEqual(redacted["description"], "governed")
        adapter = ZohoCrmMetadataReconciler(CrmFake(), "webhook")
        with patch.object(adapter, "read", return_value=None):
            self.assertEqual(adapter.plan(self.resource("webhook")).action, "blocked")
            r = self.resource("webhook", metadata={"authentication": {"destination_env": "TEST_CRM_DEST", "credential_env": "TEST_CRM_AUTH"}})
            with patch.dict(os.environ, {"TEST_CRM_DEST": "https://example.test/webhook", "TEST_CRM_AUTH": "x" * 32}):
                self.assertEqual(adapter.plan(r).action, "manual")  # No invented native signature contract.

    def test_every_metadata_kind_denies_deletion(self):
        registry = DesiredStateRegistry(); register_crm_metadata(registry, CrmFake())
        for kind in ("layout", "workflow", "webhook", "field_update", "assignment_rule", "scoring_rule", "validation_rule"):
            with self.subTest(kind=kind):
                adapter = ZohoCrmMetadataReconciler(CrmFake(), kind)
                with patch.object(adapter, "read", return_value={"id": "123", "name": "Fixture"}):
                    self.assertEqual(adapter.plan(self.resource(kind, lifecycle={"ensure": "absent"})).action, "blocked")

    def test_inventory_drift_bounds_and_unavailable_is_not_empty(self):
        first = snapshot({"fields": entry({"ok": True, "status": 200, "data": {"fields": [{"id": "1", "api_name": "Email", "data_type": "email"}]}}, "fields")})
        second = snapshot({"fields": entry({"ok": False, "status": 401, "data": {"code": "NO_PERMISSION"}}, "fields")})
        self.assertEqual(len(drift(first, second)["changes"]), 1)
        self.assertEqual(drift(first, second)["unknown"], ["fields"])
        self.assertFalse(second["complete"])
        self.assertEqual(first["content_hash"], snapshot(first["entries"])["content_hash"])
        collector = CrmInventoryCollector(CrmFake(), max_calls=1)
        with self.assertRaisesRegex(ValueError, "budget"):
            collector.collect(("Leads",))


class DesiredApiTests(unittest.TestCase):
    def setUp(self):
        from workflow import api
        self.api = api
        self.client = TestClient(api.app)
        self.key = api.settings.api.api_key_env

    def test_every_endpoint_fails_closed_with_unset_server_key(self):
        for value in (None, "", "   "):
            with patch.dict(os.environ, {}, clear=False):
                if value is None: os.environ.pop(self.key, None)
                else: os.environ[self.key] = value
                for action in ("plan", "validate", "drift", "apply"):
                    body = field_doc().model_dump() if action != "apply" else {"document": field_doc().model_dump(), "plan_hash": "0" * 64, "reason": "fixture"}
                    with self.subTest(value=value, action=action):
                        self.assertEqual(self.client.post("/v1/automation/desired-state/" + action, json=body).status_code, 503)

    def test_api_stale_plan_rejected_and_high_risk_flags_forbidden(self):
        fake = CrmFake(); registry = DesiredStateRegistry(); registry.register("zoho_crm", "field", ZohoCrmFieldReconciler(fake))
        controller = DesiredStateController(registry)
        with patch.object(self.api, "desired_state_controller", controller), patch.dict(os.environ, {self.key: "fixture-key"}):
            headers = {"X-API-Key": "fixture-key"}
            self.assertEqual(self.client.post("/v1/automation/desired-state/plan", json=field_doc().model_dump()).status_code, 401)
            result = self.client.post("/v1/automation/desired-state/apply", headers=headers,
                json={"document": field_doc().model_dump(), "plan_hash": "0" * 64, "reason": "reviewed fixture"})
            self.assertEqual(result.status_code, 409); self.assertFalse(fake.writes)
            self.assertEqual(self.client.post("/v1/automation/desired-state/apply", headers=headers,
                json={"document": field_doc().model_dump(), "plan_hash": "0" * 64, "reason": "fixture", "allow_high_risk": True}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
