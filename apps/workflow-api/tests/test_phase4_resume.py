from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
from campaign_identity_fixture import campaign_identities


REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "ops/phase4/resume_production_closeout.py"
spec = importlib.util.spec_from_file_location("phase4_resume_tests", SCRIPT)
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)
campaign = resume.campaign
CANDIDATE = "c" * 40


class SourcePermissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "source.py").write_text("raise RuntimeError('must not execute source')\n")
        (self.repo / "deleted.txt").write_text("old\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline fixture")
        self.baseline = self.git("rev-parse", "HEAD").strip()
        (self.repo / "source.py").write_text("raise RuntimeError('compile without import')\n")
        (self.repo / "run.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.repo / "run.sh").chmod(0o755)
        (self.repo / "deleted.txt").unlink()
        directory = self.repo / "new-directory"
        directory.mkdir()
        (directory / "module.py").write_text("value = 1\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "candidate fixture")
        self.candidate = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "--detach", "-q", self.baseline)
        self.protected = self.repo / "ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
        self.protected.parent.mkdir(parents=True)
        self.protected.write_bytes(b"do not touch protected untracked content")
        self.protected.chmod(0o750)
        self.protected_before = self.identity(self.protected)

    @staticmethod
    def identity(path):
        metadata = path.stat()
        return (campaign.sha(path), metadata.st_mode, metadata.st_uid, metadata.st_gid,
                metadata.st_ino, metadata.st_mtime_ns, metadata.st_ctime_ns)

    def git(self, *args, umask=None, binary=False):
        kwargs = {} if umask is None else {"umask": umask}
        value = subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, **kwargs).stdout
        return value if binary else value.decode()

    def scope(self):
        paths = campaign.git_paths(self.git("diff", "--name-only", "--no-renames", "-z", self.baseline, self.candidate, binary=True))
        entries = campaign.index_entries(self.git("ls-files", "--stage", "-z", binary=True))
        return paths, entries

    def normalize(self, **kwargs):
        paths, entries = self.scope()
        return campaign.normalize_tracked_modes(self.repo, paths, entries, owner_uid=os.getuid(), **kwargs)

    def test_real_077_checkout_defect_is_reproduced_and_only_indexed_modes_are_repaired(self):
        previous = os.umask(0o077)
        try:
            self.git("merge", "--ff-only", "-q", self.candidate)
            self.assertEqual(stat.S_IMODE((self.repo / "source.py").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((self.repo / "run.sh").stat().st_mode), 0o700)
            # The real production repair addressed files, not arbitrary directories.
            # Directory materialization is prevented separately by the child umask.
            (self.repo / "new-directory").chmod(0o755)
            deleted_replacement = self.repo / "deleted.txt"
            deleted_replacement.write_bytes(b"untracked replacement must remain private")
            deleted_replacement.chmod(0o600)
            deleted_before = self.identity(deleted_replacement)
            result = self.normalize()
            self.assertEqual(result, {"result": "PASS", "verified_files": 3, "normalized_files": 3, "deleted_files_ignored": 1})
            for relative, expected in (("source.py", 0o644), ("run.sh", 0o755), ("new-directory/module.py", 0o644)):
                with self.subTest(relative=relative):
                    self.assertEqual(stat.S_IMODE((self.repo / relative).stat().st_mode), expected)
                    self.assertEqual(expected & 0o022, 0)
            proof = json.loads(subprocess.check_output(["python3", "-I", "-c", campaign.SOURCE_READ_PROBE,
                                  str(self.repo), json.dumps(["source.py", "new-directory/module.py"])], text=True))
            self.assertEqual(proof["readable_files"], 2)
            self.assertFalse(proof["application_import_executed"])
            self.assertTrue((self.repo / "source.py").stat().st_mode & stat.S_IROTH)
            self.assertTrue((self.repo / "new-directory").stat().st_mode & stat.S_IXOTH)
            campaign.write_record(self.root / "private.json", {"fixture": "private"})
            self.assertEqual(stat.S_IMODE((self.root / "private.json").stat().st_mode), 0o600)
            observed = os.umask(0o077)
            self.assertEqual(observed, 0o077)
            self.assertEqual(self.identity(self.protected), self.protected_before)
            self.assertEqual(self.identity(deleted_replacement), deleted_before)
        finally:
            os.umask(previous)

    def test_child_022_materializes_readable_source_and_traversable_directories_under_parent_077(self):
        previous = os.umask(0o077)
        try:
            self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
            self.assertEqual(self.normalize(normalize=False)["normalized_files"], 0)
            self.assertEqual(stat.S_IMODE((self.repo / "new-directory").stat().st_mode), 0o755)
            self.assertEqual(os.umask(0o077), 0o077)
            self.assertEqual(self.identity(self.protected), self.protected_before)
        finally:
            os.umask(previous)

    def test_campaign_git_applies_child_umask_only_to_production_materialization(self):
        driver = object.__new__(campaign.Campaign)
        driver.run = Mock(return_value="")
        driver.git(campaign.PROD, "merge", "--ff-only", CANDIDATE)
        self.assertEqual(driver.run.call_args.kwargs["umask"], 0o022)
        driver.git(campaign.PROD, "rev-parse", "HEAD")
        self.assertNotIn("umask", driver.run.call_args.kwargs)
        driver.git(REPO, "merge", "--ff-only", CANDIDATE)
        self.assertNotIn("umask", driver.run.call_args.kwargs)

    def test_check_only_rejects_restrictive_source(self):
        self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
        (self.repo / "source.py").chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "tracked_source_mode_not_materialized"):
            self.normalize(normalize=False)

    def test_unexpected_modes_rejected_without_partial_normalization(self):
        self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
        for mode in (0o666, 0o664, 0o755, 0o4644, 0o000):
            with self.subTest(mode=oct(mode)):
                (self.repo / "source.py").chmod(mode)
                (self.repo / "run.sh").chmod(0o700)
                expected = self.assertRaises(OSError) if mode == 0 and os.geteuid() != 0 else self.assertRaisesRegex(
                    RuntimeError, "unexpected_tracked_source_mode")
                with expected:
                    self.normalize()
                self.assertEqual(stat.S_IMODE((self.repo / "run.sh").stat().st_mode), 0o700)
        self.assertEqual(self.identity(self.protected), self.protected_before)

    def test_protected_scope_rejected_before_chmod(self):
        relative = "ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
        with self.assertRaisesRegex(RuntimeError, "protected_source_path_in_candidate"):
            campaign.normalize_tracked_modes(self.repo, [relative], {relative: ("100755", "a" * 40)}, owner_uid=os.getuid())
        self.assertEqual(self.identity(self.protected), self.protected_before)

    def test_tracked_symlink_mode_rejected(self):
        self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
        with self.assertRaisesRegex(RuntimeError, "unsupported_tracked_source_type"):
            campaign.normalize_tracked_modes(self.repo, ["source.py"], {"source.py": ("120000", "a" * 40)}, owner_uid=os.getuid())

    def test_leaf_and_parent_symlinks_never_followed(self):
        self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "module.py").write_text("outside = True\n")
        (outside / "module.py").chmod(0o600)
        before = self.identity(outside / "module.py")
        (self.repo / "source.py").unlink()
        (self.repo / "source.py").symlink_to(outside / "module.py")
        with self.assertRaises(OSError):
            self.normalize()
        (self.repo / "source.py").unlink()
        (self.repo / "source.py").write_text("value = 1\n")
        (self.repo / "source.py").chmod(0o644)
        shutil.rmtree(self.repo / "new-directory")
        (self.repo / "new-directory").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.normalize()
        self.assertEqual(self.identity(outside / "module.py"), before)

    def test_hardlink_and_wrong_owner_fail_closed(self):
        self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
        os.link(self.repo / "source.py", self.root / "second-link")
        with self.assertRaisesRegex(RuntimeError, "unsafe_tracked_source_type"):
            self.normalize()
        (self.root / "second-link").unlink()
        paths, entries = self.scope()
        with self.assertRaisesRegex(RuntimeError, "unexpected_tracked_source_mode"):
            campaign.normalize_tracked_modes(self.repo, paths, entries, owner_uid=os.getuid() + 1)

    def test_read_probe_compiles_without_running_and_rejects_syntax_errors(self):
        self.git("merge", "--ff-only", "-q", self.candidate, umask=0o022)
        (self.repo / "source.py").write_text("this is invalid syntax !\n")
        value = subprocess.run(["python3", "-I", "-c", campaign.SOURCE_READ_PROBE, str(self.repo), '["source.py"]'], capture_output=True)
        self.assertNotEqual(value.returncode, 0)

    def test_read_probe_uses_service_uid_and_no_supplementary_groups(self):
        with campaign_identities(campaign):
            driver = campaign.Campaign(CANDIDATE, self.root)
        self.assertNotEqual(driver.owner.pw_uid, driver.service_user.pw_uid)
        entries = b"100644 " + b"a" * 40 + b" 0\tapps/workflow-api/workflow/api.py\0"
        driver.git_bytes = Mock(return_value=entries)
        with patch.object(campaign.subprocess, "run", return_value=Mock(returncode=0, stdout=b'{"result":"PASS","readable_files":1}')) as process:
            driver.service_source_readability()
        self.assertEqual(process.call_args.kwargs["user"], driver.service_user.pw_uid)
        self.assertEqual(process.call_args.kwargs["group"], driver.service_user.pw_gid)
        self.assertEqual(process.call_args.kwargs["extra_groups"], [])

    def test_git_path_parser_rejects_escape_and_non_nul_output(self):
        for value in (b"../escape\0", b"/absolute\0", b"a//b\0", b"a", b"a\0a\0"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                campaign.git_paths(value)


class LegacyEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.frozen, self.live = self.root / "frozen.db", self.root / "live.db"
        with sqlite3.connect(self.frozen) as conn:
            conn.executescript("PRAGMA user_version=1; CREATE TABLE automation_events(event_id TEXT PRIMARY KEY, payload_json TEXT);"
                "CREATE TABLE automation_runs(run_id TEXT PRIMARY KEY, status TEXT, definition_json TEXT);"
                "CREATE TABLE automation_run_steps(id INTEGER PRIMARY KEY, run_id TEXT, status TEXT);"
                "INSERT INTO automation_events VALUES('event','{}'); INSERT INTO automation_runs VALUES('run','completed','{}');"
                "INSERT INTO automation_run_steps VALUES(1,'run','completed');")
        shutil.copyfile(self.frozen, self.live)
        with sqlite3.connect(self.live) as conn:
            conn.execute("PRAGMA user_version=2")

    def test_read_only_comparison_allows_new_events_and_runs(self):
        with sqlite3.connect(self.live) as conn:
            conn.execute("INSERT INTO automation_events VALUES('new-event','{}')")
            conn.execute("INSERT INTO automation_runs VALUES('new-run','completed','{}')")
        before = campaign.sha(self.frozen)
        evidence = resume.verify_legacy(self.live, self.frozen)
        self.assertEqual(evidence["legacy_counts"], {"automation_events": 1, "automation_runs": 1, "automation_run_steps": 1})
        self.assertTrue(evidence["read_only"])
        self.assertEqual(campaign.sha(self.frozen), before)

    def test_changed_or_missing_original_evidence_rejected(self):
        for sql in ("UPDATE automation_events SET payload_json='changed'", "DELETE FROM automation_run_steps",
                    "UPDATE automation_runs SET definition_json='changed'"):
            with self.subTest(sql=sql):
                shutil.copyfile(self.frozen, self.live)
                with sqlite3.connect(self.live) as conn:
                    conn.execute("PRAGMA user_version=2")
                    conn.execute(sql)
                with self.assertRaisesRegex(RuntimeError, "legacy_immutable_evidence_changed"):
                    resume.verify_legacy(self.live, self.frozen)

    def test_wrong_versions_and_unresolved_frozen_runs_rejected(self):
        with sqlite3.connect(self.live) as conn:
            conn.execute("PRAGMA user_version=1")
        with self.assertRaisesRegex(RuntimeError, "legacy_database_versions"):
            resume.verify_legacy(self.live, self.frozen)
        with sqlite3.connect(self.live) as conn:
            conn.execute("PRAGMA user_version=2")
        with sqlite3.connect(self.frozen) as conn:
            conn.execute("UPDATE automation_runs SET status='partial'")
        with self.assertRaisesRegex(RuntimeError, "frozen_unresolved_execution"):
            resume.verify_legacy(self.live, self.frozen)

    def test_frozen_nonempty_wal_or_symlink_rejected_before_immutable_read(self):
        wal = self.frozen.with_name(self.frozen.name + "-wal")
        wal.write_bytes(b"unverified WAL frames")
        with self.assertRaisesRegex(RuntimeError, "frozen_snapshot_wal_not_empty"):
            resume.verify_legacy(self.live, self.frozen)
        wal.unlink()
        wal.symlink_to(self.live)
        with self.assertRaisesRegex(RuntimeError, "frozen_snapshot_wal_not_empty"):
            resume.verify_legacy(self.live, self.frozen)
        wal.unlink()
        wal.write_bytes(b"")
        self.assertEqual(resume.verify_legacy(self.live, self.frozen)["result"], "PASS")


class FakeResume(resume.ResumeCloseout):
    def __init__(self, root):
        with campaign_identities(campaign):
            super().__init__(CANDIDATE, root)
        self.calls = []
        self.head, self.remote = resume.DEPLOYED, resume.BASELINE
        self.fail_stage = None
        self.partial = 0
        self.statuses = {"completed": 178}
        self.event_statuses = {"routed": 280}
        self.worker = {"healthy": True, "thread_alive": True, "heartbeat_stale": False, "scan_stalled": False}
        self.alerts, self.backlog, self.quarantined = [], 0, 0
        self.paths = ["ops/phase4/production_campaign.py", "ops/phase4/resume_production_closeout.py"]
        self.original_digest = "fixture-original"
        self.frozen_digest = "fixture-frozen"
        self.report_failure = False

    def stage_start(self, stage):
        super().stage_start(stage)
        if stage == self.fail_stage:
            raise RuntimeError("fixture_original_failure")

    def protected_unchanged(self):
        self.calls.append(("protected_unchanged",))

    def load_environment(self):
        self.calls.append(("load_environment",))

    def verify_previous_recovery(self):
        self.calls.append(("verify_previous_recovery",))
        self.mark(production_migration_completed=True, production_migration_completed_before_resume=True,
                  predeployment_backup={"archive": "fixture-original-backup"},
                  frozen_v1_snapshot={"path": "fixture-frozen", "version": 1, "verified": True})

    def preserved_recovery(self):
        self.calls.append(("preserved_recovery",))

    def legacy_evidence(self):
        self.calls.append(("legacy_evidence",))
        return {"result": "PASS", "read_only": True}

    def git_bytes(self, repository, *args):
        self.calls.append(("git_bytes", *args))
        return ("\0".join(self.paths) + "\0").encode()

    def git(self, repository, *args, timeout=900):
        self.calls.append(("git", *args))
        if args[0] == "rev-parse":
            if len(args) > 1 and args[1].endswith("^{}"):
                return resume.BASELINE
            if len(args) > 1 and ":" in args[1]:
                return "d" * 40
            return self.head if repository == resume.PROD else CANDIDATE
        if args[0] == "status":
            return campaign.EXPECTED_STATUS if repository == resume.PROD else ""
        if args[0] == "merge-base":
            return args[1]
        if args[0] == "ls-remote":
            if args[-1] == "refs/heads/main":
                return self.remote + "\trefs/heads/main"
            posttag = "recovery/post-phase4-durable-events-v1-" + datetime.now(timezone.utc).strftime("%Y%m%d")
            return resume.BASELINE + "\trefs/tags/" + resume.PRETAG + "^{}\n" + CANDIDATE + "\trefs/tags/" + posttag + "^{}"
        if args[0] == "merge":
            self.head = CANDIDATE
            return "fixture-fast-forward"
        if args[0] == "push":
            if args[-1].endswith(":refs/heads/main"):
                self.remote = CANDIDATE
            return "fixture-push"
        raise AssertionError("unexpected fake Git operation")

    def run(self, argv, **kwargs):
        self.calls.append(tuple(argv))
        if argv[:2] == ["/usr/bin/systemctl", "show"]:
            return "running" if "--property=SubState" in argv else "active"
        if argv[:2] == ["/usr/bin/systemctl", "--failed"]:
            return ""
        if argv[:3] == ["/usr/bin/systemctl", "start", "optibrain-phase2a-upload.service"]:
            return ""
        raise AssertionError("unexpected fake system operation")

    def inspect_database(self, path=None):
        if self.report_failure:
            raise OSError("fixture unreadable database")
        return {"version": 2, "counts": {"automation_runs": 178, "automation_events": 280},
                "run_status_counts": self.statuses, "smoke_policy": {"safe": True, "reason": "safe_internal_smoke"},
                "watchdog_sample_at": datetime.now(timezone.utc).isoformat(), "watchdog_sample_id": 100,
                "watchdog_sample_healthy": True}

    def checkout_permissions(self, candidate=None, *, normalize=True):
        self.calls.append(("checkout_permissions", candidate, normalize))
        return {"result": "PASS"}

    def service_source_readability(self):
        self.calls.append(("service_source_readability",))
        return {"result": "PASS"}

    def api(self, path, body=None):
        self.calls.append(("api", path))
        if path == "/health":
            return {"version": "1.9.0"}
        if path.endswith("execution-health"):
            return {"recovery_worker": self.worker, "partial": self.partial}
        if path.endswith("health-alerts"):
            return {"status": "ok", "alerts": self.alerts}
        if path.endswith("event-health"):
            return {"backlog": self.backlog, "quarantined": self.quarantined, "statuses": self.event_statuses}
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
        raise AssertionError("unexpected fake API request")

    def archive(self, expected_commit, label):
        self.stage_start(label + "-backup")
        self.calls.append(("archive", expected_commit, label))
        archive = self.root / "postbackup.tar.gz"
        archive.write_bytes(b"verified V2 archive fixture")
        generation = "20260928T000000Z"
        campaign.OFFHOST_STATE.write_text(json.dumps({"generation": generation, "source_sha256": campaign.sha(archive),
                                                    "verification_status": "download_hash_verified"}))
        self.result["postdeployment_backup"] = {"archive": str(archive), "verify": "PASS", "isolated_restore": {"result": "PASS"}}
        return archive, generation, {}

    def recovery_tag(self, name, commit):
        self.calls.append(("tag", name, commit))


class ResumeStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = patch.object(campaign, "OFFHOST_STATE", self.root / "offhost.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        # No root-owned production fixture: this validator is separately covered.
        patcher = patch.object(campaign, "protected_file", Mock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.driver = FakeResume(self.root)

    def execute(self):
        return campaign.execute_with_evidence(self.driver)

    def writes(self):
        return [call for call in self.driver.calls if call[:2] in {("git", "merge"), ("git", "push"), ("api", "/v1/automation/events")}]

    def assert_no_lifecycle_or_migration(self):
        for call in self.driver.calls:
            self.assertFalse(call[:3] in {("/usr/bin/systemctl", "stop", resume.SERVICE),
                                         ("/usr/bin/systemctl", "start", resume.SERVICE),
                                         ("/usr/bin/systemctl", "restart", resume.SERVICE)})
            self.assertNotIn("--snapshot-to", call)
            self.assertFalse(any(isinstance(value, str) and value.endswith("migrate_db.py") for value in call))

    def test_full_fake_closeout_promotes_only_after_recovery_gates_without_migration_or_restart(self):
        result = self.execute()
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(self.driver.head, CANDIDATE)
        self.assertEqual(self.driver.remote, CANDIDATE)
        self.assertTrue(result["production_migration_completed_before_resume"])
        self.assertFalse(result["migration_repeated"])
        self.assertFalse(result["production_service_restart_attempted"])
        self.assertTrue(result["postdeployment_backup_completed"])
        self.assertTrue(result["offhost_verification_completed"])
        self.assertTrue(result["production_smoke_completed"])
        self.assert_no_lifecycle_or_migration()
        calls = self.driver.calls
        merge = next(i for i, call in enumerate(calls) if call[:2] == ("git", "merge"))
        evidence = calls.index(("verify_previous_recovery",))
        push = next(i for i, call in enumerate(calls) if call[:2] == ("git", "push"))
        upload = calls.index(("/usr/bin/systemctl", "start", "optibrain-phase2a-upload.service"))
        self.assertLess(evidence, merge)
        self.assertLess(upload, push)

    def test_already_hotfixed_checkout_skips_merge(self):
        self.driver.head = CANDIDATE
        self.assertEqual(self.execute()["result"], "PASS")
        self.assertFalse(any(call[:2] == ("git", "merge") for call in self.driver.calls))

    def test_runtime_or_other_unapproved_diff_blocks_before_any_write(self):
        for path in ("apps/workflow-api/workflow/api.py", "apps/workflow-api/config/automation/workflows/new.yaml",
                     "ops/backup/optibrain-cloudflare-auth-diagnostic.sh", "docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"):
            with self.subTest(path=path):
                self.driver.paths = [path]
                result = self.execute()
                self.assertEqual(result["category"], "resume_hotfix_not_ops_only")
                self.assertEqual(self.writes(), [])

    def test_partial_or_unknown_run_status_blocks_before_hotfix_or_smoke(self):
        self.driver.partial = 1
        self.assertEqual(self.execute()["category"], "unresolved_execution_work")
        self.assertEqual(self.writes(), [])
        self.driver.partial = 0
        for status in ("partial", "dead_letter", "human_action_required", "future_unresolved"):
            with self.subTest(status=status):
                self.driver.statuses = {"completed": 178, status: 1}
                self.assertEqual(self.execute()["category"], "unresolved_execution_work")
                self.assertEqual(self.writes(), [])

    def test_backlog_quarantine_alert_or_worker_failure_blocks_before_write(self):
        cases = (("backlog", 1), ("quarantined", 1), ("event_statuses", {"routed": 280, "pending": 1}),
                 ("alerts", ["fixture"]), ("worker", {"healthy": True, "thread_alive": False,
                                                       "heartbeat_stale": False, "scan_stalled": False}))
        for name, value in cases:
            with self.subTest(name=name):
                driver = FakeResume(self.root)
                setattr(driver, name, value)
                result = campaign.execute_with_evidence(driver)
                self.assertEqual(result["result"], "BLOCKED")
                self.assertFalse(any(call[:2] == ("git", "merge") for call in driver.calls))

    def test_changed_remote_blocks_without_write(self):
        self.driver.remote = "d" * 40
        self.assertEqual(self.execute()["category"], "remote_main_changed")
        self.assertEqual(self.writes(), [])

    def test_missing_original_evidence_blocks_before_checkout_advances(self):
        self.driver.verify_previous_recovery = Mock(side_effect=RuntimeError("original_prebackup_not_verified"))
        result = self.execute()
        self.assertEqual(result["blocking_stage"], "verify-existing-v1-recovery-evidence")
        self.assertEqual(self.writes(), [])
        self.assertEqual(result["production_database_version"], 2)

    def test_every_resume_failure_boundary_preserves_v2_service_and_completed_gates(self):
        stages = ("resume-preflight", "verify-existing-v1-recovery-evidence", "resume-fresh-watchdog-and-health",
                  "ops-only-checkout-fast-forward", "ops-only-source-permissions", "post-hotfix-live-verification",
                  "safe-production-smoke", "post-smoke-health-and-integrity", "postdeployment-backup",
                  "encrypted-offhost-download-verification", "final-health-and-preserved-evidence", "remote-main-preflight",
                  "promote-remote-main", "verify-remote-main", "postdeployment-recovery-tag", "publish-production-recovery-tags")
        advanced, promoted = False, False
        for stage in stages:
            with self.subTest(stage=stage):
                root = self.root / stage
                root.mkdir()
                self.driver = FakeResume(root)
                self.driver.fail_stage = stage
                result = self.execute()
                if stage == "ops-only-source-permissions":
                    advanced = True
                if stage == "verify-remote-main":
                    promoted = True
                self.assertEqual(result["result"], "BLOCKED")
                self.assertEqual(result["blocking_stage"], stage)
                self.assertEqual(result["category"], "fixture_original_failure")
                self.assertEqual(result["production_database_version"], 2)
                self.assertTrue(result["production_service_active"])
                self.assertEqual(result["production_git_sha"], CANDIDATE if advanced else resume.DEPLOYED)
                self.assertEqual(result["remote_main_sha"], CANDIDATE if promoted else resume.BASELINE)
                self.assertEqual(result["hotfix_checkout_advanced"], advanced)
                self.assertTrue(result["manual_recovery_required"])
                self.assertFalse(result["production_service_restart_attempted"])
                self.assertNotIn("production_database_overwritten", result)
                self.assert_no_lifecycle_or_migration()
                self.assertEqual(sum(call[:2] == ("git", "push") for call in self.driver.calls), int(promoted))

    def test_backup_failure_reports_hotfix_v2_and_does_not_promote_main(self):
        self.driver.fail_stage = "postdeployment-backup"
        result = self.execute()
        self.assertTrue(result["production_smoke_completed"])
        self.assertFalse(result["postdeployment_backup_completed"])
        self.assertEqual(result["production_git_sha"], CANDIDATE)
        self.assertEqual(result["production_database_version"], 2)
        self.assertEqual(self.driver.remote, resume.BASELINE)
        self.assertTrue(result["production_service_active"])

    def test_offhost_failure_keeps_backup_smoke_migration_evidence_and_remote_baseline(self):
        self.driver.fail_stage = "encrypted-offhost-download-verification"
        result = self.execute()
        self.assertTrue(result["production_smoke_completed"])
        self.assertTrue(result["postdeployment_backup_completed"])
        self.assertFalse(result["offhost_verification_completed"])
        self.assertTrue(result["frozen_v1_snapshot"]["verified"])
        self.assertEqual(self.driver.remote, resume.BASELINE)

    def test_lost_merge_result_observes_new_candidate_without_recovery_start_or_push(self):
        original = self.driver.git
        def lost(repository, *args, **kwargs):
            value = original(repository, *args, **kwargs)
            if args[0] == "merge":
                raise TimeoutError("fixture merge response lost")
            return value
        self.driver.git = lost
        result = self.execute()
        self.assertEqual(result["blocking_stage"], "ops-only-checkout-fast-forward")
        self.assertTrue(result["hotfix_checkout_advanced"])
        self.assertEqual(result["production_database_version"], 2)
        self.assertFalse(any(call[:2] == ("git", "push") for call in self.driver.calls))
        self.assert_no_lifecycle_or_migration()

    def test_reporting_failure_preserves_original_stage_with_unknown_observations(self):
        self.driver.fail_stage = "postdeployment-backup"
        self.driver.blocked = Mock(side_effect=OSError("fixture report failed"))
        result = self.execute()
        self.assertEqual(result["blocking_stage"], "postdeployment-backup")
        self.assertEqual(result["category"], "fixture_original_failure")
        self.assertEqual(result["production_database_version"], "unknown")
        self.assertTrue(result["production_smoke_completed"])
        self.assertEqual(self.driver.remote, resume.BASELINE)

    def test_smoke_requires_increased_duplicate_count(self):
        original = self.driver.api
        def fixed_count(path, body=None):
            value = original(path, body)
            if path.endswith("/events/fixture-event"):
                value["duplicate_count"] = 1
            return value
        self.driver.api = fixed_count
        result = self.execute()
        self.assertEqual(result["category"], "production_ledger_evidence")
        self.assertFalse(result["production_smoke_completed"])
        self.assertEqual(self.driver.remote, resume.BASELINE)

    def test_smoke_rejects_wrong_run_identity_workflow_or_external_action(self):
        for field, value in (("workflow_id", "wrong-workflow"), ("event_id", "wrong-event"),
                             ("steps", [{"action": "zoho.crm.create"}])):
            with self.subTest(field=field):
                driver = FakeResume(self.root)
                original = driver.api
                def unsafe_run(path, body=None):
                    response = original(path, body)
                    if path.endswith("/runs/fixture-run"):
                        response[field] = value
                    return response
                driver.api = unsafe_run
                result = campaign.execute_with_evidence(driver)
                self.assertEqual(result["category"], "production_smoke_execution")
                self.assertFalse(result["production_smoke_completed"])
                self.assertEqual(driver.remote, resume.BASELINE)

    def test_database_inspection_failure_reports_unknown_never_false_unchanged(self):
        self.driver.report_failure = True
        result = self.execute()
        self.assertEqual(result["production_database_version"], "unknown")
        self.assertEqual(result["recovery_category"], "resume_database_state_unproven_preserve_evidence")
        self.assertEqual(self.writes(), [])

    def test_failure_recovery_is_observation_only(self):
        self.driver.head = CANDIDATE
        self.driver.remote = CANDIDATE
        result = self.driver.blocked(RuntimeError("fixture"), "fixture-boundary")
        self.assertTrue(result["remote_main_promoted"])
        self.assertEqual(self.writes(), [])
        self.assert_no_lifecycle_or_migration()

    def test_lifecycle_and_migration_defensive_guard(self):
        with campaign_identities(campaign):
            driver = resume.ResumeCloseout(CANDIDATE, self.root)
        for argv in (["/usr/bin/systemctl", "stop", resume.SERVICE], ["/usr/bin/systemctl", "restart", resume.SERVICE],
                     [str(campaign.PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(campaign.DB)]):
            with self.subTest(argv=argv), self.assertRaises(RuntimeError):
                driver.run(argv)

    def test_plan_is_read_only_and_requires_no_root(self):
        value = subprocess.run(["python3", "-I", str(SCRIPT), "--candidate", CANDIDATE, "--plan"], capture_output=True, text=True)
        self.assertEqual(value.returncode, 0, value.stderr)
        plan = json.loads(value.stdout)
        self.assertEqual(plan["migration"], "forbidden")
        self.assertEqual(plan["workflow_service_restart"], "forbidden")

    def test_non_root_cli_refuses_before_production_access(self):
        if os.geteuid() != 0:
            value = subprocess.run(["python3", "-I", str(SCRIPT), "--candidate", CANDIDATE], capture_output=True, text=True)
            self.assertNotEqual(value.returncode, 0)
            self.assertIn("human_root_authentication_required", value.stderr)


class PreviousRecoveryEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with campaign_identities(campaign):
            self.driver = resume.ResumeCloseout(CANDIDATE, self.root)
        self.frozen = self.root / "frozen.db"
        self.frozen.write_bytes(b"frozen V1 fixture")
        self.frozen.chmod(0o600)
        self.archive = self.root / "prebackup.tar.gz"
        payload = json.dumps({"production_git_sha": resume.BASELINE}).encode()
        import io
        with tarfile.open(self.archive, "w:gz") as tar:
            member = tarfile.TarInfo("generation-20260928T115757Z/manifest.json")
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
        digest = campaign.sha(self.archive)
        self.archive.with_name(self.archive.name + ".sha256").write_text(digest + "  " + self.archive.name + "\n")
        self.original = {"baseline": resume.BASELINE, "candidate": resume.DEPLOYED, "result": "BLOCKED",
            "blocking_stage": "candidate-api-readiness", "production_migration_started": True,
            "production_migration_drill": {"result": "PASS"},
            "production_migration_completed": True, "production_migration": {"result": "PASS", "previous_version": 1,
                "new_version": 2, "legacy_row_hashes": "PASS", "integrity": "PASS", "foreign_keys": "PASS",
                "legacy_row_counts": {"fixture": 3}}, "predeployment_backup": {"archive": str(self.archive),
                "archive_sha256": digest, "generation": "20260928T115757Z", "verify": "PASS", "isolated_restore": {"result": "PASS"}},
            "frozen_v1_snapshot": {"path": str(self.frozen), "sha256": campaign.sha(self.frozen), "verified": True, "version": 1}}
        self.publish_original()
        for module, name, value in ((resume, "ORIGINAL_WORKSPACE", self.root), (resume, "PRE_ARCHIVE", self.archive),
                                    (resume, "FROZEN", self.frozen), (campaign, "protected_file", Mock())):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.driver.service_user = Mock(pw_uid=os.getuid())
        self.driver.inspect_database = Mock(return_value={"version": 1, "counts": {"fixture": 3}, "watchdog_sample_id": 7})
        self.driver.legacy_evidence = Mock(return_value={"result": "PASS", "read_only": True})
        self.driver.run = Mock(return_value="")

    def publish_original(self):
        (self.root / "result.json").write_text(json.dumps(self.original))

    def test_verifies_original_backup_frozen_and_migration_without_repeating_drill(self):
        before = campaign.sha(self.root / "result.json")
        self.driver.verify_previous_recovery()
        self.assertTrue(self.driver.result["production_migration_completed_before_resume"])
        self.assertEqual(self.driver.previous_sample, 7)
        self.assertEqual(campaign.sha(self.root / "result.json"), before)
        self.assertEqual(self.driver.run.call_count, 1)
        self.assertIn("--verify", self.driver.run.call_args.args[0])
        self.driver.preserved_recovery()

    def test_original_evidence_mismatches_fail_closed(self):
        for field, value in (("candidate", CANDIDATE), ("blocking_stage", "different"), ("production_migration_completed", False)):
            with self.subTest(field=field):
                old = self.original[field]
                self.original[field] = value
                self.publish_original()
                with self.assertRaisesRegex(RuntimeError, "original_migration_evidence_unexpected"):
                    self.driver.verify_previous_recovery()
                self.original[field] = old

    def test_tampered_frozen_snapshot_rejected(self):
        self.frozen.write_bytes(b"changed V1 fixture")
        with self.assertRaisesRegex(RuntimeError, "original_frozen_snapshot_changed"):
            self.driver.verify_previous_recovery()

    def test_tampered_backup_rejected(self):
        self.archive.write_bytes(b"changed archive")
        with self.assertRaisesRegex(RuntimeError, "original_prebackup_hash_changed"):
            self.driver.verify_previous_recovery()

    def test_failed_original_migration_proof_rejected(self):
        self.original["production_migration"]["legacy_row_hashes"] = "FAIL"
        self.publish_original()
        with self.assertRaisesRegex(RuntimeError, "original_migration_not_verified"):
            self.driver.verify_previous_recovery()
