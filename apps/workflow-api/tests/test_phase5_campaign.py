import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("phase5_test_campaign", ROOT / "ops/phase5/production_campaign.py")
campaign = importlib.util.module_from_spec(spec); spec.loader.exec_module(campaign)
provider_spec = importlib.util.spec_from_file_location("phase5_test_provider", ROOT / "ops/phase5/production_provider.py")
provider = importlib.util.module_from_spec(provider_spec); provider_spec.loader.exec_module(provider)


class Phase5CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = campaign.Phase5Campaign("a" * 40, self.root)
        self.job.service_user = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())

    def test_failure_preserves_actual_state_without_legacy_rollback(self):
        self.job.result.update(production_checkout_advanced=True, notification_subscription_verified=True)
        with patch.object(self.job, "observe_failure_state") as observed, patch.object(self.job, "recover_baseline") as recover, patch.object(self.job, "run") as run:
            value = self.job.blocked(RuntimeError("fixture_postdeployment_restore_failure"), "postdeployment-backup")
        observed.assert_called_once(); recover.assert_not_called(); run.assert_not_called()
        self.assertEqual(value["result"], "BLOCKED")
        self.assertTrue(value["production_checkout_advanced"])
        self.assertTrue(value["notification_subscription_verified"])
        self.assertTrue(value["manual_recovery_required"])
        self.assertFalse(value["database_migration_required"])
        self.assertFalse(value["main_modified"])

    def test_provider_exception_message_is_not_reported(self):
        class ProviderError(RuntimeError): pass
        with patch.object(self.job, "observe_failure_state"):
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
            "OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY": (datetime.now(timezone.utc) + timedelta(days=6)).replace(microsecond=0).isoformat()}
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
        with self.assertRaisesRegex(RuntimeError, "manual_reconciliation"):
            self.provider_subscribe(fake)
        with self.assertRaisesRegex(RuntimeError, "manual_reconciliation"):
            self.provider_subscribe(fake)
        self.assertEqual(len(fake.writes), 1)


if __name__ == "__main__": unittest.main()
