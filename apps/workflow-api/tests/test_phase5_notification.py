import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from workflow.automation.crm_inventory import normalize
from workflow.automation.desired_drift import DesiredDriftObserver
from workflow.automation.desired_state import DesiredResource, DesiredStateController, DesiredStateDocument, DesiredStateRegistry
from workflow.automation.reconcilers.zoho_notification import ZohoCrmNotificationReconciler
from workflow.automation.store import AutomationStore


class NativeFake:
    def __init__(self):
        self.rows, self.calls = [], []
        self.lose, self.error, self.skip_verify = False, None, False

    def request(self, service, method, path, **kwargs):
        assert service == "zohoapis" and path == "/crm/v8/actions/watch"
        self.calls.append((method, copy.deepcopy(kwargs)))
        if method == "GET":
            if self.error: raise self.error
            return {"ok": True, "status": 200 if self.rows else 204, "data": {"watch": copy.deepcopy(self.rows)}}
        if method != "POST": raise AssertionError("Unapproved native method")
        row = kwargs["body"]["watch"][0]
        if not self.skip_verify:
            # Zoho may return an equivalent time in its configured timezone.
            self.rows = [{**row, "channel_expiry": datetime.fromisoformat(row["channel_expiry"]).astimezone(timezone(timedelta(hours=-4))).isoformat()}]
        if self.lose: raise httpx.ReadTimeout("fixture lost accepted response")
        return {"ok": True, "status": 200, "request_id": "native-evidence-only", "data": {"watch": [{"status": "success"}]}}

    @property
    def writes(self): return [c for c in self.calls if c[0] != "GET"]


class NativeSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "state.db")
        self.fake = NativeFake()
        self.registry = DesiredStateRegistry()
        self.registry.register("zoho_crm", "notification", ZohoCrmNotificationReconciler(self.fake))
        self.controller = DesiredStateController(self.registry, self.store)
        self.resource = DesiredResource(id="fixture.crm.notification", provider="zoho_crm", kind="notification", name="Lead notification",
            identity={"channel_id": "5062683202609281"}, desired={"events": ["Leads.create", "Leads.edit"]},
            metadata={"authentication": {"destination_env": "OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT", "credential_env": "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL", "expiry_env": "OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY"}})
        self.document = DesiredStateDocument(name="fixture-native", resources=[self.resource])
        self.env = patch.dict(os.environ, {"OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT": "https://example.test/crm/notify",
            "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL": "native-fixture-credential-32bytes-long", "OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY": (datetime.now(timezone.utc) + timedelta(days=6)).replace(microsecond=0).isoformat()})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_additive_native_subscription_is_verified_and_duplicate_is_noop(self):
        plan = self.controller.plan(self.document)
        self.assertEqual(plan.summary, {"create": 1})
        result = self.controller.apply(self.document, plan, low_risk_additive_only=True)
        self.assertEqual(result[0].status, "completed")
        self.assertEqual(self.controller.plan(self.document).summary, {"noop": 1})
        self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(len(self.fake.writes), 1)
        saved = json.dumps(self.store.recent_audit())
        self.assertNotIn(os.environ["OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"], saved)
        self.assertNotIn(os.environ["OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT"], saved)
        self.assertIn("native-evidence-only", saved)

    def test_secret_env_references_are_allowed_but_plain_credentials_are_rejected(self):
        self.assertEqual(normalize(self.document.model_dump()), self.document.model_dump())
        self.assertEqual(DesiredStateController.validate_document(self.document), self.controller.plan(self.document).document_hash)
        self.resource.metadata["authentication"]["credential_env"] = "actual-credential-material"
        with self.assertRaisesRegex(ValueError, "secret/URL"):
            DesiredStateController.validate_document(self.document)
        self.assertFalse(self.fake.writes)

    def test_changed_environment_authentication_invalidates_reviewed_plan(self):
        before = self.controller.plan(self.document)
        with patch.dict(os.environ, {"OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL": "changed-fixture-credential-32bytes-long"}):
            self.assertNotEqual(before.plan_hash, self.controller.plan(self.document).plan_hash)
            with self.assertRaisesRegex(ValueError, "Stale plan"):
                self.controller.apply(self.document, before)
        self.assertFalse(self.fake.writes)
        self.assertNotIn(os.environ["OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"], before.model_dump_json())

    def test_unrelated_environment_credentials_and_unconfigured_channels_are_denied(self):
        self.resource.metadata["authentication"]["credential_env"] = "SITE_WORKFLOW_API_KEY"
        with patch.dict(os.environ, {"SITE_WORKFLOW_API_KEY": "unrelated-fixture-inspection-key-32bytes"}):
            self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.assertFalse(self.fake.calls)
        self.resource.metadata["authentication"]["credential_env"] = "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"
        self.resource.identity["channel_id"] = "999"
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.assertFalse(self.fake.calls)

    def test_bad_destination_token_expiry_channel_and_module_fail_closed(self):
        for key, value in (("OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT", "http://example.test"), ("OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT", "https://user:password@example.test"),
                           ("OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT", "https://example.test?token=secret"), ("OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL", "short"),
                           ("OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL", "x" * 51), ("OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY", "2026-01-01T00:00:00Z"),
                           ("OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY", (datetime.now(timezone.utc) + timedelta(days=8)).isoformat())):
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.resource.identity["channel_id"] = "9" * 30
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.resource.identity["channel_id"] = "5062683202609281"
        self.resource.desired["events"] = ["Deals.create"]
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.assertFalse(self.fake.writes)

    def test_accepted_native_response_lost_never_repeats_across_restart(self):
        self.fake.lose = True
        result = self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(result[0].status, "manual")
        self.assertEqual(len(self.fake.rows), 1)
        restarted = DesiredStateController(self.registry, AutomationStore(self.store.db_path))
        self.assertEqual(restarted.plan(self.document).summary, {"noop": 1})
        self.assertEqual(restarted.apply(self.document, restarted.plan(self.document))[0].status, "manual")
        self.assertEqual(len(self.fake.writes), 1)

    def test_failed_native_verification_blocks_retry(self):
        self.fake.skip_verify = True
        result = self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(result[0].status, "manual")
        self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(len(self.fake.writes), 1)

    def test_existing_channel_collision_never_overwritten_or_deleted(self):
        self.controller.apply(self.document, self.controller.plan(self.document))
        self.fake.rows[0]["token"] = "different-existing-private-credential"
        self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
        self.resource.lifecycle["ensure"] = "absent"
        self.assertEqual(self.controller.plan(self.document).changes[0].risk, "destructive")
        self.controller.apply(self.document, self.controller.plan(self.document))
        self.assertEqual(len(self.fake.writes), 1)

    def test_provider_read_errors_never_assume_missing_subscription(self):
        for error in (httpx.ReadTimeout("fixture"), ValueError("fixture unavailable")):
            with self.subTest(error=type(error).__name__):
                self.fake.error = error
                self.assertEqual(self.controller.plan(self.document).summary, {"blocked": 1})
                self.assertFalse(self.fake.writes)

    def test_periodic_drift_is_read_only_bounded_and_durable(self):
        root = Path(self.tmp.name) / "desired"; root.mkdir()
        (root / "opticable-fixture.json").write_text(self.document.model_dump_json())
        native = self.document.model_copy(deep=True)
        native.name = "fixture-native-template"
        (root / "zoho-crm-notification.template.json").write_text(native.model_dump_json())
        observer = DesiredDriftObserver(self.controller, root, interval=300)
        observer.poll(); calls = len(self.fake.calls)
        observer.poll()
        self.assertEqual(len(self.fake.calls), calls)
        self.assertEqual(self.controller.journal.last(self.document.name, ("drift",))["metadata"]["summary"], {"create": 1})
        self.assertEqual(self.controller.journal.last(native.name, ("drift",))["metadata"]["summary"], {"create": 1})
        self.assertFalse(self.fake.writes)
        observer.next_scan = 0
        with self.controller.journal.lock(): observer.poll()
        self.assertEqual(len(self.fake.calls), calls)
        with self.assertRaises(ValueError): DesiredDriftObserver(self.controller, root, interval=1)


if __name__ == "__main__": unittest.main()
