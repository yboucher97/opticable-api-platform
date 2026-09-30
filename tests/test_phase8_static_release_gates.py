"""Offline failure checks for the data-only Phase 8 release packet validator."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "deploy/phase8-static-release-gates.py"
spec = importlib.util.spec_from_file_location("phase8_static_gates", PATH)
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)
NOW = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def iso(at):
    return at.isoformat().replace("+00:00", "Z")


def backup(sha, generation):
    return {"generation": generation, "manifest_production_sha": sha,
            "archive_sha256": HASH, "sidecar_sha256": HASH,
            "offhost_generation": generation, "offhost_sha256": HASH,
            "offhost_status": "download_hash_verified", "created_at": iso(NOW - timedelta(minutes=30)),
            "restore_at": iso(NOW - timedelta(minutes=20)), "restore_result": "PASS",
            "restore_isolated": True, "journal_dedupe_result": "PASS",
            "preserve_existing": True, "retention_hold": True, "capacity_verified": True}


def fixtures(stage="prestage"):
    artifacts = {key: HASH for key in ("loader_sha256", "campaign_sha256",
                                      "wrapper_sha256", "hook_sha256")}
    authority = dict(repository=gates.REPOSITORY, branch=gates.BRANCH,
                     candidate=gates.CANDIDATE, validated_sha=gates.CANDIDATE,
                     baseline=gates.BASELINE, ci_run_id=gates.CI_RUN,
                     ci_jobs=sorted(gates.JOBS), release_id="phase8-20260930-abcdefgh",
                     approved_by="human:owner", issued_at=iso(NOW - timedelta(minutes=40)),
                     expires_at=iso(NOW + timedelta(minutes=40)), **artifacts)
    packet = dict(release_id=authority["release_id"], observed_at=iso(NOW - timedelta(minutes=2)),
                  repository=gates.REPOSITORY, branch=gates.BRANCH,
                  remote_main=gates.BASELINE, remote_branch=gates.CANDIDATE,
                  baseline_ancestor=True, production_sha=gates.BASELINE,
                  production_status="?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh",
                  diagnostic_sha256=gates.DIAGNOSTIC_SHA256, service_health="ok",
                  public_health="ok", api_version="1.11.0",
                  external_actions_disabled=True, workflow_hashes_verified=True,
                  registration_pins_verified=True, inflight_provider_operation=False,
                  prior_release_reconciled=True,
                  ci=dict(run_id=gates.CI_RUN, repository=gates.REPOSITORY,
                          name="Validate API Platform", event="push", head_branch=gates.BRANCH,
                          head_sha=gates.CANDIDATE, status="completed", conclusion="success",
                          jobs=[dict(name=name, status="completed", conclusion="success")
                                for name in sorted(gates.JOBS)]), artifacts=artifacts,
                  baseline_backup=backup(gates.BASELINE, "20260930T003000Z"),
                  stage=stage, candidate_backup=None, forward_recovery_result=None)
    if stage == "prepromotion":
        packet["production_sha"] = gates.CANDIDATE
        packet["candidate_backup"] = backup(gates.CANDIDATE, "20260930T004000Z")
        packet["forward_recovery_result"] = "PASS"
    return authority, packet


class StaticGatesTest(unittest.TestCase):
    def test_valid_packets_are_data_only(self):
        for stage in ("prestage", "prepromotion"):
            authority, packet = fixtures(stage)
            result = gates.validate_packet(authority, packet, NOW)
            self.assertEqual(result["result"], "PASS")
            self.assertFalse(result["deployment_authorized"])
            self.assertFalse(result["provider_actions_authorized"])

    def test_fail_closed_changes(self):
        cases = [
            ("authority_candidate", lambda a, p: a.update(candidate=gates.BASELINE), "authority_identity"),
            ("extra_authority", lambda a, p: a.update(model_approved=True), "authority_fields"),
            ("stale_authority", lambda a, p: a.update(expires_at=iso(NOW)), "authority_expired_or_stale"),
            ("old_observation", lambda a, p: p.update(observed_at=iso(NOW - timedelta(minutes=16))), "stale_observation"),
            ("main_changed", lambda a, p: p.update(remote_main=gates.CANDIDATE), "main_changed"),
            ("production_changed", lambda a, p: p.update(production_sha=gates.CANDIDATE), "prestage_identity"),
            ("ci_sha", lambda a, p: p["ci"].update(head_sha=gates.BASELINE), "ci_identity"),
            ("ci_job", lambda a, p: p["ci"]["jobs"][0].update(conclusion="failure"), "ci_jobs_failed"),
            ("artifact", lambda a, p: p["artifacts"].update(wrapper_sha256="b" * 64), "artifact_changed"),
            ("old_backup", lambda a, p: p["baseline_backup"].update(created_at=iso(NOW - timedelta(hours=3))), "baseline_stale_or_unrestored"),
            ("offhost", lambda a, p: p["baseline_backup"].update(offhost_sha256="b" * 64), "baseline_recovery_mismatch"),
            ("restore", lambda a, p: p["baseline_backup"].update(restore_isolated=False), "baseline_recovery_unproven"),
            ("external", lambda a, p: p.update(external_actions_disabled=False), "operational_safety"),
        ]
        for name, mutate, gate in cases:
            with self.subTest(name=name):
                authority, packet = fixtures()
                mutate(authority, packet)
                with self.assertRaisesRegex(gates.GateError, gate):
                    gates.validate_packet(authority, packet, NOW)

    def test_candidate_recovery_is_distinct(self):
        authority, packet = fixtures("prepromotion")
        packet["candidate_backup"]["generation"] = packet["baseline_backup"]["generation"]
        packet["candidate_backup"]["offhost_generation"] = packet["baseline_backup"]["generation"]
        with self.assertRaisesRegex(gates.GateError, "backup_generation_reused"):
            gates.validate_packet(authority, packet, NOW)

    def test_duplicate_json_authority_field_rejected(self):
        with self.assertRaisesRegex(gates.GateError, "duplicate_json_field"):
            json.loads('{"release_id":"first","release_id":"second"}',
                       object_pairs_hook=gates.unique_object)


if __name__ == "__main__":
    unittest.main()
