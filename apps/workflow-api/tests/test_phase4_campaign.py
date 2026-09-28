from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[3] / "ops/phase4/production_campaign.py"
spec = importlib.util.spec_from_file_location("phase4_failure_campaign", SCRIPT)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
CANDIDATE = "b" * 40


class FakeCampaign(campaign.Campaign):
    """Only fixture files and fake process/Git/DB state; no production operations."""

    def __init__(self, root: Path):
        super().__init__(CANDIDATE, root)
        self.calls = []
        self.head, self.remote = campaign.BASELINE, campaign.BASELINE
        self.service, self.version = "active", 1
        self.sample_id = 7
        self.partial = 0
        self.other_status = None
        self.fail_stage = None
        self.fail_migration = False
        self.ambiguous_migration = False
        self.stop_timeout = False
        self.ready_failure = False
        self.reporting_failure = False
        self.private = root / "staging"
        self.private.mkdir()
        self.backup = root / "predeployment.tar.gz"
        self.backup.write_bytes(b"V1 backup fixture")
        self.mark(production_service_active_before_campaign=True,
                  predeployment_backup={"archive": str(self.backup), "archive_sha256": campaign.sha(self.backup)})

    def stage_start(self, name):
        super().stage_start(name)
        if name == self.fail_stage:
            self.fail_stage = None
            raise RuntimeError("fixture_original_failure")

    def execute(self):
        return self.promote(self.private, campaign.PROTECTED.stat(), "fixture-pretag", "fixture-posttag")

    def checkout_permissions(self, candidate=None, *, normalize=True):
        self.calls.append(("checkout_permissions", candidate, normalize))
        return {"result": "PASS"}

    def service_source_readability(self):
        self.calls.append(("service_source_readability",))
        return {"result": "PASS"}

    def git(self, repository, *args, timeout=900):
        self.calls.append(("git", *args))
        if args[0] == "rev-parse":
            return self.head
        if args[0] == "status":
            return campaign.EXPECTED_STATUS
        if args[0] == "ls-remote":
            return self.remote + "\trefs/heads/main"
        if args[0] == "merge":
            self.head = self.candidate
            return "fixture fast-forward"
        if args[0] == "push":
            if args[-1].endswith(":refs/heads/main"):
                self.remote = self.candidate
            return "fixture push"
        raise AssertionError("unexpected fixture git command")

    def run(self, argv, **kwargs):
        self.calls.append(tuple(argv))
        if argv[0] == "/usr/bin/systemctl":
            if argv[1] == "show":
                return self.service
            if argv[1] == "stop":
                self.service = "inactive"
                if self.stop_timeout:
                    self.stop_timeout = False
                    raise TimeoutError("fixture stop outcome lost")
                return ""
            if argv[1] == "start":
                if argv[2] == campaign.SERVICE:
                    self.service = "active"
                    self.sample_id += 1
                return ""
            if argv[1] == "--failed":
                return ""
        if "--snapshot-to" in argv:
            Path(argv[-1]).write_bytes(b"frozen V1 fixture")
            return json.dumps({"result": "PASS"})
        if "migrate_db.py" in argv[1]:
            if self.fail_migration:
                self.fail_migration = False
                raise RuntimeError("fixture_transactional_migration_failure")
            if self.ambiguous_migration:
                self.ambiguous_migration = False
                self.version = 2
                self.reporting_failure = True
                raise TimeoutError("fixture migration outcome lost")
            self.version = 2
            return json.dumps({"result": "PASS", "previous_version": 1, "new_version": 2})
        raise AssertionError("unexpected fixture process command")

    def inspect_database(self, path=None):
        self.calls.append(("inspect", str(path) if path else "production"))
        if self.reporting_failure:
            raise OSError("fixture unreadable state")
        statuses = {"completed": 3}
        if self.other_status:
            statuses[self.other_status] = 1
        return {"version": 1 if path else self.version, "counts": {"fixture": 3}, "hashes": {"fixture": "fixed"},
                "run_status_counts": statuses, "smoke_policy": {"safe": True},
                "watchdog_sample_at": datetime.now(timezone.utc).isoformat(),
                "watchdog_sample_id": self.sample_id, "watchdog_sample_healthy": True}

    def ready(self, version):
        self.calls.append(("ready", version))
        if self.ready_failure:
            raise RuntimeError("fixture_readiness_failure")
        expected = "1.8.0" if self.version == 1 else "1.9.0"
        campaign.check(self.service == "active" and version == expected, "fixture_incompatible_service")

    def api(self, path, body=None):
        if path == "/health":
            return {"version": "1.8.0" if self.version == 1 else "1.9.0"}
        if path.endswith("execution-health"):
            return {"recovery_worker": {"healthy": True}, "partial": self.partial}
        if path.endswith("health-alerts"):
            return {"status": "ok"}
        if path.endswith("event-health"):
            return {"backlog": 0, "quarantined": 0}
        if path.endswith("/runs/fixture-run"):
            return {"status": "completed", "workflow_id": "platform.smoke-test", "event_id": "fixture-event",
                    "steps": [{"action": "core.set"}, {"action": "event.emit"}]}
        if path.endswith("/events/fixture-event"):
            return {"status": "routed", "duplicate_count": getattr(self, "duplicate_count", 0)}
        if path.endswith("/events"):
            if getattr(self, "event_seen", False):
                self.duplicate_count = getattr(self, "duplicate_count", 0) + 1
                return {"duplicate": True, "event_id": "fixture-event"}
            self.event_seen = True
            return {"accepted": True, "run_ids": ["fixture-run"], "event_id": "fixture-event"}
        raise AssertionError("unexpected fixture API request")

    def archive(self, expected_commit, label):
        self.stage_start(label + "-backup")
        archive = self.root / (label + ".tar.gz")
        archive.write_bytes(b"V2 backup fixture")
        generation = "20260928T000000Z"
        self.result[label + "_backup"] = {"archive": str(archive), "generation": generation}
        campaign.OFFHOST_STATE.write_text(json.dumps({"generation": generation, "source_sha256": campaign.sha(archive),
                                                     "verification_status": "download_hash_verified"}))
        return archive, generation, {}

    def recovery_tag(self, name, commit):
        self.calls.append(("tag", name, commit))


class CampaignFailureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        protected = root / "protected-fixture"
        protected.write_bytes(b"protected fixture")
        for name, value in {"PROD": root / "production", "PROTECTED": protected,
                            "PROTECTED_SHA": campaign.sha(protected), "OFFHOST_STATE": root / "offhost.json"}.items():
            patcher = patch.object(campaign, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.driver = FakeCampaign(root)

    def run_failure(self, stage):
        self.driver.fail_stage = stage
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocking_stage"], stage)
        self.assertEqual(result["category"], "fixture_original_failure")
        return result

    def starts(self):
        return [call for call in self.driver.calls if call[:3] == ("/usr/bin/systemctl", "start", campaign.SERVICE)]

    def test_failure_before_stop_never_restarts(self):
        result = self.run_failure("pre-stop-health")
        self.assertFalse(result["production_service_stop_attempted"])
        self.assertFalse(result["manual_recovery_required"])
        self.assertEqual(result["recovery_category"], "before_service_stop_no_recovery")
        self.assertEqual(result["production_database_version"], 1)
        self.assertEqual(self.starts(), [])

    def test_before_stop_unknown_db_requires_review_without_restart(self):
        self.driver.reporting_failure = True
        result = self.run_failure("pre-stop-health")
        self.assertEqual(result["production_database_version"], "unknown")
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(result["recovery_category"], "before_service_stop_unverified_manual_review")
        self.assertFalse(result["production_service_stop_attempted"])
        self.assertEqual(self.starts(), [])

    def test_before_stop_already_inactive_service_requires_review_without_restart(self):
        self.driver.service = "inactive"
        result = self.run_failure("pre-stop-health")
        self.assertFalse(result["production_service_active"])
        self.assertTrue(result["manual_recovery_required"])
        self.assertFalse(result["production_service_stop_attempted"])
        self.assertEqual(self.starts(), [])

    def test_failure_after_stop_recovers_proven_baseline_v1(self):
        result = self.run_failure("inspect-stopped-production")
        self.assertEqual(len(self.starts()), 1)
        self.assertTrue(result["production_service_restart_attempted"])
        self.assertTrue(result["production_service_ready"])
        self.assertTrue(result["production_service_active"])
        self.assertFalse(result["manual_recovery_required"])
        self.assertEqual(result["production_git_sha"], campaign.BASELINE)
        self.assertEqual(result["production_database_version"], 1)
        self.assertFalse(result["production_migration_started"])
        self.assertIn(("ready", "1.8.0"), self.driver.calls)

    def test_stop_timeout_with_observed_inactive_baseline_can_recover(self):
        self.driver.stop_timeout = True
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "stop-production-service")
        self.assertEqual(result["category"], "TimeoutError")
        self.assertEqual(len(self.starts()), 1)
        self.assertFalse(result["manual_recovery_required"])

    def test_advanced_checkout_v1_never_starts_candidate(self):
        result = self.run_failure("migrate-production-database")
        self.assertTrue(result["production_checkout_advanced"])
        self.assertFalse(result["production_migration_started"])
        self.assertEqual(result["production_database_version"], 1)
        self.assertEqual(result["production_service_state"], "inactive")
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(self.starts(), [])

    def test_lost_checkout_result_observes_advanced_v1_without_starting_it(self):
        original = self.driver.git
        def lost(repository, *args, **kwargs):
            value = original(repository, *args, **kwargs)
            if args[0] == "merge":
                raise TimeoutError("fixture fast-forward response lost")
            return value
        self.driver.git = lost
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "advance-production-checkout")
        self.assertTrue(result["production_checkout_advanced"])
        self.assertEqual(result["production_database_version"], 1)
        self.assertFalse(result["production_migration_started"])
        self.assertEqual(self.starts(), [])

    def test_transactional_migration_failure_reports_v1(self):
        self.driver.fail_migration = True
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "migrate-production-database")
        self.assertEqual(result["production_database_version"], 1)
        self.assertTrue(result["production_migration_started"])
        self.assertFalse(result["production_migration_completed"])
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(self.starts(), [])

    def test_completed_migration_readiness_failure_reports_v2_and_retains_v1_evidence(self):
        self.driver.ready_failure = True
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "candidate-api-readiness")
        self.assertEqual(result["production_database_version"], 2)
        self.assertTrue(result["production_migration_completed"])
        self.assertEqual(result["production_git_sha"], CANDIDATE)
        self.assertTrue(result["production_service_active"])
        self.assertFalse(result["production_service_ready"])
        self.assertNotIn("production_database_overwritten", result)
        snapshot = result["frozen_v1_snapshot"]
        self.assertTrue(snapshot["verified"])
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(Path(snapshot["path"]).read_bytes(), b"frozen V1 fixture")
        self.assertEqual(Path(result["predeployment_backup"]["archive"]).read_bytes(), b"V1 backup fixture")
        self.assertEqual(len(self.starts()), 1)

    def test_postdeployment_backup_failure_reports_completed_gates(self):
        result = self.run_failure("postdeployment-backup")
        self.assertEqual(result["production_git_sha"], CANDIDATE)
        self.assertEqual(result["production_database_version"], 2)
        for name in ("production_migration_completed", "production_service_active", "production_service_ready", "production_smoke_completed"):
            self.assertTrue(result[name], name)
        self.assertFalse(result["postdeployment_backup_completed"])
        self.assertFalse(result["offhost_verification_completed"])
        self.assertFalse(result["remote_main_promoted"])

    def test_offhost_failure_retains_all_earlier_gate_evidence(self):
        result = self.run_failure("encrypted-offhost-download-verification")
        self.assertTrue(result["production_smoke_completed"])
        self.assertTrue(result["postdeployment_backup_completed"])
        self.assertFalse(result["offhost_verification_completed"])
        self.assertEqual(result["production_database_version"], 2)
        self.assertEqual(result["remote_main_sha"], campaign.BASELINE)

    def test_partial_blocks_before_any_stop(self):
        self.driver.partial = 1
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "pre-stop-health")
        self.assertEqual(result["category"], "unresolved_execution_work")
        self.assertFalse(result["production_service_stop_attempted"])
        self.assertEqual(self.starts(), [])
        self.assertFalse(any(call[:2] == ("/usr/bin/systemctl", "stop") for call in self.driver.calls))

    def test_unknown_database_run_status_blocks_before_stop(self):
        self.driver.other_status = "future-unresolved"
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "pre-stop-health")
        self.assertFalse(result["production_service_stop_attempted"])

    def test_failed_probe_keeps_original_failure_and_unknown_database(self):
        self.driver.fail_stage = "inspect-stopped-production"
        original = self.driver.stage_start
        def failed_stage(name):
            try:
                original(name)
            except RuntimeError:
                self.driver.reporting_failure = True
                raise
        self.driver.stage_start = failed_stage
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "inspect-stopped-production")
        self.assertEqual(result["category"], "fixture_original_failure")
        self.assertEqual(result["production_database_version"], "unknown")
        self.assertIn("production_database_version", result["failure_reporting_errors"])
        self.assertEqual(self.starts(), [])

    def test_lost_migration_result_uninspectable_db_is_unknown_not_false(self):
        self.driver.ambiguous_migration = True
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "migrate-production-database")
        self.assertEqual(result["category"], "TimeoutError")
        self.assertEqual(result["production_database_version"], "unknown")
        self.assertEqual(result["production_migration_completed"], "unknown")
        self.assertTrue(result["production_migration_started"])
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(self.starts(), [])

    def test_lost_migration_result_observed_v2_stays_unverified_and_stopped(self):
        original = self.driver.run
        def lost(argv, **kwargs):
            value = original(argv, **kwargs)
            if len(argv) > 1 and "migrate_db.py" in argv[1] and "--snapshot-to" not in argv:
                raise TimeoutError("fixture verified migration response lost")
            return value
        self.driver.run = lost
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["production_database_version"], 2)
        self.assertEqual(result["production_migration_completed"], "unknown")
        self.assertEqual(result["recovery_category"], "unverified_v2_migration_preserved_manual_review")
        self.assertEqual(self.starts(), [])

    def test_reporting_handler_exception_cannot_mask_original_stage(self):
        self.driver.fail_stage = "inspect-stopped-production"
        def broken(exc, stage):
            self.driver.stage = "unrelated-reporting-stage"
            raise OSError("fixture report failed")
        self.driver.blocked = broken
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "inspect-stopped-production")
        self.assertEqual(result["category"], "fixture_original_failure")
        self.assertEqual(result["production_database_version"], "unknown")
        self.assertEqual(result["failure_reporting_errors"]["handler"], "OSError")

    def test_reporting_failure_after_recovery_keeps_latest_restart_marker(self):
        self.driver.fail_stage = "inspect-stopped-production"
        original = self.driver.blocked
        def broken(exc, stage):
            original(exc, stage)
            raise OSError("fixture final observation failed")
        self.driver.blocked = broken
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "inspect-stopped-production")
        self.assertEqual(result["category"], "fixture_original_failure")
        self.assertTrue(result["production_service_restart_attempted"])
        self.assertEqual(result["production_service_active"], "unknown")
        self.assertEqual(len(self.starts()), 1)

    def test_baseline_recovery_failure_preserves_original_stage_and_observed_service(self):
        self.driver.fail_stage = "inspect-stopped-production"
        self.driver.ready_failure = True
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["blocking_stage"], "inspect-stopped-production")
        self.assertEqual(result["category"], "fixture_original_failure")
        self.assertTrue(result["production_service_active"])
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(result["recovery_category"], "baseline_recovery_failed_manual_review")

    def test_baseline_recovery_requires_originally_active_service(self):
        self.driver.result["production_service_active_before_campaign"] = False
        result = self.run_failure("inspect-stopped-production")
        self.assertEqual(self.starts(), [])
        self.assertTrue(result["manual_recovery_required"])

    def test_uninspectable_service_does_not_trigger_recovery_start(self):
        self.driver.fail_stage = "inspect-stopped-production"
        self.driver.service_state = Mock(side_effect=["inactive", OSError("fixture service probe unavailable")])
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["production_service_active"], "unknown")
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(self.starts(), [])

    def test_recovery_rechecks_checkout_and_never_starts_changed_code(self):
        self.driver.fail_stage = "inspect-stopped-production"
        original = self.driver.git
        reads = 0
        def changing(repository, *args, **kwargs):
            nonlocal reads
            if args[0] == "rev-parse" and self.driver.result["production_service_stop_completed"]:
                reads += 1
                if reads >= 2:
                    self.driver.head = CANDIDATE
            return original(repository, *args, **kwargs)
        self.driver.git = changing
        result = campaign.execute_with_evidence(self.driver)
        self.assertTrue(result["manual_recovery_required"])
        self.assertEqual(self.starts(), [])
        self.assertEqual(result["production_git_sha"], CANDIDATE)

    def test_failure_recovery_never_changes_remote_main(self):
        result = self.run_failure("inspect-stopped-production")
        self.assertEqual(self.driver.remote, campaign.BASELINE)
        self.assertEqual(result["remote_main_sha"], campaign.BASELINE)
        self.assertFalse(any(call[:2] == ("git", "push") for call in self.driver.calls))
        self.assertFalse(any(call[:2] == ("git", "merge") for call in self.driver.calls))

    def test_failure_after_main_promotion_reports_actual_remote_without_recovery_push(self):
        result = self.run_failure("postdeployment-recovery-tag")
        self.assertTrue(result["remote_main_promoted"])
        self.assertEqual(result["remote_main_sha"], CANDIDATE)
        self.assertTrue(result["offhost_verification_completed"])
        pushes = [call for call in self.driver.calls if call[:2] == ("git", "push")]
        self.assertEqual(len(pushes), 1)

    def test_progress_survives_failure_with_snapshot_and_migration_milestones(self):
        self.run_failure("start-candidate-service")
        progress = json.loads((self.driver.root / "progress.json").read_text())
        self.assertEqual(progress["current_stage"], "start-candidate-service")
        self.assertTrue(progress["production_migration_completed"])
        self.assertTrue(progress["frozen_v1_snapshot"]["verified"])

    def test_blocked_result_has_all_required_recovery_facts(self):
        result = self.run_failure("candidate-health")
        for name in ("blocking_stage", "production_git_sha", "remote_main_sha", "production_service_active",
                     "production_database_version", "production_migration_started", "production_migration_completed",
                     "production_checkout_advanced", "production_service_restart_attempted", "production_service_ready",
                     "production_smoke_completed", "postdeployment_backup_completed", "offhost_verification_completed",
                     "remote_main_promoted", "recovery_workspace", "manual_recovery_required"):
            self.assertIn(name, result)

    def test_every_post_stop_boundary_reports_state_and_recovery_never_pushes(self):
        stages = (
            ("inspect-stopped-production", campaign.BASELINE, 1),
            ("freeze-v1-snapshot", campaign.BASELINE, 1),
            ("advance-production-checkout", campaign.BASELINE, 1),
            ("production-source-permissions", CANDIDATE, 1),
            ("migrate-production-database", CANDIDATE, 1),
            ("start-candidate-service", CANDIDATE, 2),
            ("candidate-api-readiness", CANDIDATE, 2),
            ("candidate-watchdog-readiness", CANDIDATE, 2),
            ("candidate-health", CANDIDATE, 2),
            ("safe-production-smoke", CANDIDATE, 2),
            ("post-smoke-health", CANDIDATE, 2),
            ("postdeployment-backup", CANDIDATE, 2),
            ("encrypted-offhost-download-verification", CANDIDATE, 2),
            ("final-health", CANDIDATE, 2),
            ("remote-main-preflight", CANDIDATE, 2),
            ("promote-remote-main", CANDIDATE, 2),
            ("verify-remote-main", CANDIDATE, 2),
            ("postdeployment-recovery-tag", CANDIDATE, 2),
            ("publish-production-recovery-tags", CANDIDATE, 2),
        )
        for stage, head, version in stages:
            with self.subTest(stage=stage):
                root = self.driver.root / stage
                root.mkdir()
                driver = FakeCampaign(root)
                driver.fail_stage = stage
                result = campaign.execute_with_evidence(driver)
                self.assertEqual(result["blocking_stage"], stage)
                self.assertEqual(result["production_git_sha"], head)
                self.assertEqual(result["production_database_version"], version)
                expected_remote = CANDIDATE if stage in {"verify-remote-main", "postdeployment-recovery-tag",
                                                        "publish-production-recovery-tags"} else campaign.BASELINE
                self.assertEqual(result["remote_main_sha"], expected_remote)
                expected_active = stage not in {"production-source-permissions", "migrate-production-database", "start-candidate-service"}
                self.assertEqual(result["production_service_active"], expected_active)
                self.assertEqual(result["manual_recovery_required"], head != campaign.BASELINE)
                pushes = [call for call in driver.calls if call[:2] == ("git", "push")]
                self.assertEqual(len(pushes), 1 if expected_remote == CANDIDATE else 0)

    def test_successful_fake_campaign_completes_all_gates(self):
        result = campaign.execute_with_evidence(self.driver)
        self.assertEqual(result["result"], "PASS")
        self.assertTrue(result["production_migration_completed"])
        self.assertTrue(result["postdeployment_backup_completed"])
        self.assertTrue(result["offhost_verification_completed"])
        self.assertTrue(result["remote_main_promoted"])

    def test_final_result_persistence_failure_observes_completed_production_state(self):
        self.assertEqual(campaign.execute_with_evidence(self.driver)["result"], "PASS")
        result = campaign.blocked_with_evidence(self.driver, RuntimeError("result_persistence_failed"), "final-result-persistence")
        self.assertEqual(result["blocking_stage"], "final-result-persistence")
        self.assertEqual(result["production_database_version"], 2)
        self.assertEqual(result["production_git_sha"], CANDIDATE)
        self.assertTrue(result["production_service_active"])
        self.assertTrue(result["remote_main_promoted"])
        self.assertTrue(result["offhost_verification_completed"])
        self.assertEqual(len(self.starts()), 1)

    def test_watchdog_waits_for_new_healthy_sample_after_long_downtime(self):
        old = self.driver.inspect_database()
        old.update(version=2, watchdog_sample_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
        new = dict(old, watchdog_sample_id=8, watchdog_sample_at=datetime.now(timezone.utc).isoformat())
        self.driver.inspect_database = Mock(side_effect=[old, dict(new, watchdog_sample_healthy=False), new])
        with patch.object(campaign.time, "sleep") as slept:
            self.driver.wait_watchdog(7, 2)
        self.assertEqual(slept.call_count, 2)
        self.assertEqual(self.driver.result["fresh_watchdog_sample_id"], 8)

    def test_recent_pre_restart_sample_is_insufficient(self):
        old = self.driver.inspect_database()
        old["version"] = 2
        self.driver.inspect_database = Mock(return_value=old)
        with patch.object(campaign.time, "monotonic", side_effect=[0, 0, 90]), patch.object(campaign.time, "sleep"), \
                self.assertRaisesRegex(RuntimeError, "fresh_watchdog_readiness_timeout"):
            self.driver.wait_watchdog(7, 2)

    def test_watchdog_wait_cannot_accept_wrong_database_version(self):
        with self.assertRaisesRegex(RuntimeError, "watchdog_database_version"):
            self.driver.wait_watchdog(7, 2)

    def test_watchdog_stale_policy_remains_strict(self):
        now = datetime.now(timezone.utc)
        for sample in (None, "invalid", now.replace(tzinfo=None).isoformat(), (now + timedelta(hours=1)).isoformat(),
                       (now - timedelta(seconds=600)).isoformat(), (now - timedelta(hours=1)).isoformat()):
            with self.subTest(sample=sample):
                self.assertFalse(self.driver.watchdog_fresh({"watchdog_sample_at": sample}))
        self.assertTrue(self.driver.watchdog_fresh({"watchdog_sample_at": now.isoformat()}))
