"""Offline ordered campaign and health-only hook failure checks."""
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path
import unittest

from test_phase8_static_release_gates import NOW, fixtures, gates, iso


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


campaign = load("phase8_campaign", ROOT / "ops/phase8/production_campaign.py")
hook = load("phase8_health_hook", ROOT / "deploy/phase8-production-root-command.py")


class Backend:
    def __init__(self, packets):
        self.packets = packets
        self.calls = []

    def observe(self, stage):
        self.calls.append(stage)
        return deepcopy(self.packets[stage])


def campaign_fixture():
    authority, prestage = fixtures()
    _, staged = fixtures("prepromotion")
    packets = {}
    for index, stage in enumerate(campaign.STAGES):
        packet = deepcopy(prestage if index < 2 else staged)
        packet["observed_at"] = iso(NOW - timedelta(minutes=8-index))
        packets[stage] = packet
    return authority, Backend(packets)


def live_fixture():
    return dict(observed_at=iso(NOW - timedelta(seconds=15)),
                repository=gates.REPOSITORY, branch=gates.BRANCH,
                remote_main=gates.CANDIDATE, remote_branch=gates.CANDIDATE,
                production_sha=gates.CANDIDATE,
                production_status="?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh",
                diagnostic_sha256=gates.DIAGNOSTIC_SHA256, service_active=True,
                local_health={"status": "ok", "version": "1.11.0"},
                public_health={"status": "ok", "version": "1.11.0"},
                external_actions_disabled=True)


class CampaignTest(unittest.TestCase):
    def test_ordered_campaign_and_health_only(self):
        authority, backend = campaign_fixture()
        result = campaign.run_campaign(authority, backend, NOW)
        self.assertEqual(backend.calls, list(campaign.STAGES))
        self.assertEqual(result["completed_gates"], list(campaign.STAGES))
        self.assertFalse(result["deployment_authorized"])
        self.assertFalse(result["main_promotion_authorized"])
        checked = hook.verify_health_only(authority, result, live_fixture(), NOW)
        self.assertEqual(checked["production_mutations"], 0)
        self.assertFalse(checked["provider_actions_authorized"])

    def test_first_failed_gate_stops_observation(self):
        authority, backend = campaign_fixture()
        backend.packets["baseline_recovery"]["public_health"] = "failed"
        with self.assertRaises(campaign.gates.GateError):
            campaign.run_campaign(authority, backend, NOW)
        self.assertEqual(backend.calls, list(campaign.STAGES[:2]))

    def test_snapshot_identity_and_order_fail_closed(self):
        changes = (
            ("prepromotion_identity", lambda p: p.update(production_sha=gates.BASELINE)),
            ("prepromotion_identity", lambda p: p.update(remote_main=gates.CANDIDATE)),
            ("prepromotion_identity", lambda p: p["candidate_backup"].update(restore_isolated=False)),
            ("baseline_recovery", lambda p: p.update(observed_at=iso(NOW - timedelta(minutes=8)))),
        )
        for stage, change in changes:
            with self.subTest(stage=stage):
                authority, backend = campaign_fixture()
                change(backend.packets[stage])
                with self.assertRaises(campaign.gates.GateError):
                    campaign.run_campaign(authority, backend, NOW)
                self.assertEqual(backend.calls[-1], stage)

    def test_hook_rejects_wrong_identity_and_health(self):
        authority, backend = campaign_fixture()
        result = campaign.run_campaign(authority, backend, NOW)
        changes = (
            lambda v: v.update(remote_main=gates.BASELINE),
            lambda v: v.update(production_sha=gates.BASELINE),
            lambda v: v["local_health"].update(version="1.10.0"),
            lambda v: v.update(external_actions_disabled=False),
            lambda v: v.update(observed_at=iso(NOW - timedelta(minutes=3))),
        )
        for change in changes:
            live = live_fixture()
            change(live)
            with self.assertRaises(hook.gates.GateError):
                hook.verify_health_only(authority, result, live, NOW)

    def test_malformed_static_fields_raise_gate_error(self):
        authority, packet = fixtures()
        authority["ci_jobs"] = [{"name": "workflow-api"}, "control-plane-worker"]
        with self.assertRaisesRegex(gates.GateError, "authority_identity"):
            gates.validate_packet(authority, packet, NOW)
        authority, packet = fixtures()
        packet["ci"]["jobs"][0]["name"] = []
        with self.assertRaisesRegex(gates.GateError, "ci_job_name"):
            gates.validate_packet(authority, packet, NOW)
        authority, packet = fixtures()
        packet["stage"] = []
        with self.assertRaisesRegex(gates.GateError, "unknown_stage"):
            gates.validate_packet(authority, packet, NOW)


if __name__ == "__main__":
    unittest.main()
