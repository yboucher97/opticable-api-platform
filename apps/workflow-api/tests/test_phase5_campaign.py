import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from campaign_identity_fixture import campaign_identities

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("phase5_test_campaign", ROOT / "ops/phase5/production_campaign.py")
campaign = importlib.util.module_from_spec(spec); spec.loader.exec_module(campaign)
provider_spec = importlib.util.spec_from_file_location("phase5_test_provider", ROOT / "ops/phase5/production_provider.py")
provider = importlib.util.module_from_spec(provider_spec); provider_spec.loader.exec_module(provider)


class Phase5CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.subscription_expiry = (datetime.now(timezone.utc) + timedelta(days=6)).replace(microsecond=0).isoformat()
        with campaign_identities(campaign.base):
            self.job = campaign.Phase5Campaign("a" * 40, self.root)
        self.job.service_user = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())

    def test_failure_preserves_actual_state_without_legacy_rollback(self):
        self.job.result.update(production_checkout_advanced=True, notification_subscription_verified=True)
        with patch.object(self.job, "observe_failure_state") as observed, patch.object(self.job, "recover_baseline") as recover, patch.object(self.job, "run") as run, patch.object(self.job, "checkout_permissions", return_value={"result": "PASS"}) as permissions, patch.object(campaign, "CONFIG_DIRECTORY", self.root / "private-config"):
            value = self.job.blocked(RuntimeError("fixture_postdeployment_restore_failure"), "postdeployment-backup")
        observed.assert_called_once(); recover.assert_not_called(); run.assert_not_called()
        permissions.assert_called_once_with(self.job.candidate, normalize=False)
        self.assertEqual(value["result"], "BLOCKED")
        self.assertTrue(value["production_checkout_advanced"])
        self.assertTrue(value["notification_subscription_verified"])
        self.assertTrue(value["manual_recovery_required"])
        self.assertFalse(value["database_migration_required"])
        self.assertEqual(value["main_modified"], "unknown")

    def test_provider_exception_message_is_not_reported(self):
        class ProviderError(RuntimeError): pass
        with patch.object(self.job, "observe_failure_state"), patch.object(self.job, "checkout_permissions", return_value={"result": "PASS"}), patch.object(campaign, "CONFIG_DIRECTORY", self.root / "private-config"):
            value = self.job.blocked(ProviderError("credential=private-fixture"), "provider")
        self.assertNotIn("private-fixture", json.dumps(value))
        self.assertEqual(value["category"], "ProviderError")

    def fixture_configuration(self, existing=None):
        webhook = self.root / "old-webhooks.json"; sync = self.root / "old-sync.json"
        webhook.write_text(json.dumps(existing or {"preserved-channel": {"enabled": False}}))
        sync.write_text(json.dumps([{"provider": "google_calendar", "enabled": False}]))
        environment = self.root / "service.env"
        self.job.environment = {"SITE_WORKFLOW_API_KEY": "private-fixture-key", "OPTIBRAIN_WEBHOOK_CONFIG": str(webhook), "OPTIBRAIN_SYNC_CONFIG": str(sync)}
        original = "\n".join(k + "=" + v for k, v in self.job.environment.items()) + "\n"
        environment.write_text(original); environment.chmod(0o600)
        return environment, original

    def test_private_configuration_preserves_channels_and_uses_backed_up_tree(self):
        environment, original = self.fixture_configuration()
        directory = self.root / "phase5-config"
        previous = os.umask(0o077)
        try:
            with patch.object(campaign, "CONFIG_DIRECTORY", directory), patch.object(campaign.base, "ENV", environment), patch.object(campaign.os, "chown"):
                self.job.configuration()
        finally: os.umask(previous)
        webhooks = json.loads((directory / "webhooks.yaml").read_text())
        jobs = json.loads((directory / "delta-sync.yaml").read_text())
        self.assertEqual(webhooks["preserved-channel"], {"enabled": False})
        self.assertTrue(webhooks["phase5-crm-leads"]["enabled"])
        self.assertEqual(jobs[0]["provider"], "google_calendar")
        self.assertEqual(jobs[1]["provider"], "zoho_crm")
        self.assertEqual(jobs[1]["page_limit"], 100)
        parsed = campaign.base.parse_env(environment.read_text())
        self.assertEqual(parsed["SITE_WORKFLOW_API_KEY"], "private-fixture-key")
        self.assertGreaterEqual(len(parsed["OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"]), 32)
        self.assertNotEqual(parsed.get("OPTIBRAIN_CRM_LEAD_WRITES"), "phase5-lead-v1")
        self.assertEqual((self.root / "pre-phase5-service-environment").read_text(), original)
        self.assertEqual(environment.stat().st_mode & 0o777, 0o600)
        self.assertEqual((directory / "webhooks.yaml").stat().st_mode & 0o777, 0o640)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o750)
        self.assertNotIn(parsed["OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"], (self.root / "progress.json").read_text())
        self.assertTrue(str(campaign.CONFIG_DIRECTORY).startswith("/etc/optibrain/"))

    def test_existing_native_channel_configuration_is_not_overwritten(self):
        environment, original = self.fixture_configuration({"phase5-crm-leads": {"enabled": True}})
        with patch.object(campaign, "CONFIG_DIRECTORY", self.root / "phase5-config"), patch.object(campaign.base, "ENV", environment), patch.object(campaign.os, "chown"), self.assertRaisesRegex(RuntimeError, "collision"):
            self.job.configuration()
        self.assertEqual(environment.read_text(), original)

    def provider_subscribe(self, fake, apply=None):
        settings = types.SimpleNamespace(zoho_gateway=None, zoho_oauth=None,
            automation=types.SimpleNamespace(db_path=self.root / "provider-evidence.db"))
        environment = {"OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT": "https://example.test/fixture",
            "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL": "native-fixture-credential-32bytes-long",
            "OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY": self.subscription_expiry}
        with patch.object(provider, "load_settings", return_value=settings), patch.object(provider, "ZohoOAuthManager"), patch.object(provider, "ZohoGatewayClient", return_value=fake), patch.dict(os.environ, environment):
            if apply:
                with patch.object(provider.DesiredStateController, "apply", apply), patch.object(provider.time, "sleep"):
                    return provider.run("subscribe")
            return provider.run("subscribe")

    def test_subscription_waits_only_for_prewrite_lock_contention(self):
        from test_phase5_notification import NativeFake
        fake = NativeFake()
        original = provider.DesiredStateController.apply
        calls = []
        def one_conflict(controller, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1: raise provider.ApplyConflict("fixture_prewrite_lock")
            return original(controller, *args, **kwargs)
        result = self.provider_subscribe(fake, one_conflict)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(len(calls), 2); self.assertEqual(len(fake.writes), 1)

    def test_root_subscription_lost_response_is_not_retried(self):
        from test_phase5_notification import NativeFake
        fake = NativeFake(); fake.lose = True
        for _ in range(2):
            result = self.provider_subscribe(fake)
            self.assertEqual(result["result"], "BLOCKED")
            self.assertEqual(result["category"], "native_subscription_manual_reconciliation")
            self.assertEqual(result["results"][0]["status"], "manual")
        self.assertEqual(len(fake.writes), 1)


    def test_notification_proof_accepts_public_202_contract(self):
        """The FastAPI webhook contract is 202 Accepted, not 200 OK."""

        class FakeClient:
            def request(inner, service, method, path, **kwargs):
                self.assertEqual(service, "zohoapis")
                self.assertEqual(method, "GET")
                self.assertEqual(path, "/crm/v8/Leads")
                return {
                    "ok": True,
                    "data": {
                        "data": [{
                            "id": "5062683000000000001",
                            "Modified_Time": "2026-09-28T12:00:00-04:00",
                        }]
                    },
                }

        class FakeStore:
            def __init__(inner):
                inner.db_path = self.root / "notification-proof.db"

            def get_run(inner, run_id):
                return {
                    "run_id": run_id,
                    "status": "completed",
                }

        class Response:
            def __init__(inner, status_code, payload):
                inner.status_code = status_code
                inner._payload = payload

            def json(inner):
                return inner._payload

        store = FakeStore()

        settings = types.SimpleNamespace(
            zoho_gateway=None,
            zoho_oauth=None,
            automation=types.SimpleNamespace(
                db_path=store.db_path,
            ),
            api=types.SimpleNamespace(
                api_key_env="SITE_WORKFLOW_API_KEY",
            ),
        )

        posts = [
            Response(
                202,
                {
                    "accepted": True,
                    "duplicate": False,
                    "event_id": "event-fixture",
                },
            ),
            Response(
                202,
                {
                    "accepted": False,
                    "duplicate": True,
                    "event_id": "event-fixture",
                },
            ),
        ]

        routed = Response(
            200,
            {
                "status": "routed",
                "routes": [{"run_id": "run-fixture"}],
            },
        )

        environment = {
            "SITE_WORKFLOW_API_KEY": "phase5-fixture-api-key",
            "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL":
                "phase5-fixture-channel-credential-32bytes",
            "OPTIBRAIN_CRM_LEAD_WRITES": "",
        }

        with (
            patch.object(
                provider,
                "load_settings",
                return_value=settings,
            ),
            patch.object(provider, "ZohoOAuthManager"),
            patch.object(
                provider,
                "ZohoGatewayClient",
                return_value=FakeClient(),
            ),
            patch.object(
                provider,
                "AutomationStore",
                return_value=store,
            ),
            patch.object(
                provider,
                "mark_synthetic",
            ) as synthetic,
            patch.object(
                provider.httpx,
                "post",
                side_effect=posts,
            ) as post,
            patch.object(
                provider.httpx,
                "get",
                return_value=routed,
            ),
            patch.dict(
                os.environ,
                environment,
                clear=False,
            ),
        ):
            result = provider.run("notification-proof")

        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["delivery_class"], "synthetic")
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["provider_emitted_event_proven"])
        self.assertEqual(result["crm_record_writes"], 0)
        self.assertEqual(post.call_count, 2)
        synthetic.assert_called_once()



if __name__ == "__main__": unittest.main()
