#!/usr/bin/env python3
"""Commit-pinned closeout of the verified e294064 / V2 / API 1.9.0 deployment.

Never invokes the original deployment, migrates, restores production, or changes
the workflow service lifecycle. Recovery only observes and preserves evidence.
Run with python3 -I from the isolated candidate worktree.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tarfile
import time
from uuid import uuid4

spec = importlib.util.spec_from_file_location("phase4_closeout_campaign", Path(__file__).with_name("production_campaign.py"))
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
check, sha = campaign.check, campaign.sha
BASELINE, PROD, REPO, DB, SERVICE = campaign.BASELINE, campaign.PROD, campaign.REPO, campaign.DB, campaign.SERVICE
DEPLOYED = "e294064f9ebe40ee615842ec875a605d6b9f4b08"
ORIGINAL_WORKSPACE = Path("/var/lib/optibrain/phase4/20260928T115756Z-09efc73c")
PRE_ARCHIVE = Path("/var/backups/optibrain/optibrain-backup-20260928T115757Z.tar.gz")
FROZEN = Path("/var/lib/optibrain-phase4-staging/20260928T115756Z-09efc73c/pre-migration-frozen-v1.db")
PRETAG = "recovery/pre-phase4-durable-events-v1-20260928"
RUNBOOK = PROD / "docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
RUNBOOK_SHA = "cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085"
ALLOWED_HOTFIX_PATHS = {
    "ops/phase4/production_campaign.py", "ops/phase4/resume_production_closeout.py",
    "apps/workflow-api/tests/test_phase4_campaign.py", "apps/workflow-api/tests/test_phase4_resume.py",
    "docs/OPTIBRAIN_PHASE4_ENGINEERING_RECORD.md",
}
RUNTIME_TREES = ("apps/workflow-api/workflow", "apps/workflow-api/config")


def frozen_without_wal(frozen: Path) -> None:
    try:
        meta = frozen.with_name(frozen.name + "-wal").lstat()
    except FileNotFoundError:
        return
    check(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1 and meta.st_size == 0, "frozen_snapshot_wal_not_empty")


def verify_legacy(live: Path, frozen: Path) -> dict:
    """Read-only comparison of frozen immutable evidence, allowing new V2 rows.

    Workflows are reloaded at startup; health audit and resolved claims have
    retention. Those mutable tables are covered by the original migration proof,
    not incorrectly required to remain byte-identical after normal operation.
    """
    deadline = time.monotonic() + 45
    check(live.is_file() and frozen.is_file() and not live.is_symlink() and not frozen.is_symlink(),
          "legacy_database_file_type")
    frozen_without_wal(frozen)
    counts, hashes = {}, {}
    with sqlite3.connect(live.as_uri() + "?mode=ro", uri=True, timeout=5) as current, \
            sqlite3.connect(frozen.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5) as original:
        for conn in (current, original):
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        check(current.execute("PRAGMA user_version").fetchone()[0] == 2
              and original.execute("PRAGMA user_version").fetchone()[0] == 1, "legacy_database_versions")
        check(set(dict(original.execute("SELECT status, COUNT(*) FROM automation_runs GROUP BY status"))) <= {"completed"},
              "frozen_unresolved_execution")
        current.execute("BEGIN")
        for table, key in (("automation_events", "event_id"), ("automation_runs", "run_id"), ("automation_run_steps", "id")):
            columns = [row[1] for row in original.execute(f"PRAGMA table_info({table})")]
            check(columns and key in columns and all(re.fullmatch(r"[a-z_]+", col) for col in columns), "legacy_schema_unexpected")
            projection = ",".join(columns)
            digest, count = hashlib.sha256(), 0
            for row in original.execute(f"SELECT {projection} FROM {table} ORDER BY {key}"):
                check(time.monotonic() <= deadline and count < 100000, "legacy_comparison_bound")
                retained = current.execute(f"SELECT {projection} FROM {table} WHERE {key}=?", (row[columns.index(key)],)).fetchone()
                check(retained == row, "legacy_immutable_evidence_changed")
                encoded = json.dumps(row, separators=(",", ":")).encode()
                check(len(encoded) <= 4 * 1024**2, "legacy_row_size_bound")
                digest.update(encoded + b"\n")
                count += 1
            counts[table], hashes[table] = count, digest.hexdigest()
        current.rollback()
    frozen_without_wal(frozen)
    return {"result": "PASS", "read_only": True, "legacy_counts": counts, "legacy_hashes": hashes}


class ResumeCloseout(campaign.Campaign):
    def __init__(self, candidate: str, root: Path) -> None:
        super().__init__(candidate, root)
        self.result.update(resumed_from=str(ORIGINAL_WORKSPACE), deployed_before_resume=DEPLOYED,
                           migration_repeated=False, workflow_service_lifecycle_changed=False,
                           production_migration_completed="unknown", production_migration_started_before_resume="unknown",
                           production_migration_completed_before_resume="unknown", hotfix_checkout_advanced=False)
        self.original_digest = ""
        self.frozen_digest = ""
        self.prebackup_digest = ""
        self.previous_sample = 0

    def run(self, argv: list[str], **kwargs):
        # A second defensive boundary: even an accidental future call cannot
        # start baseline code, migrate production, or replace its snapshot.
        if argv[0] == "/usr/bin/systemctl" and SERVICE in argv:
            check(argv[1] == "show", "resume_workflow_lifecycle_forbidden")
        if any(Path(value).name == "migrate_db.py" for value in argv):
            check("--inspect" in argv and "--snapshot-to" not in argv, "resume_migration_forbidden")
        return super().run(argv, **kwargs)

    def blocked(self, exc: BaseException, blocking_stage: str) -> dict:
        result = dict(self.result, result="BLOCKED", blocking_stage=blocking_stage,
                      category=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                      manual_recovery_required=True, recovery_category="resume_preserve_v2_manual_review")
        self.observe_failure_state(result)
        head = result["production_git_sha"]
        result["production_checkout_advanced"] = True if head in {DEPLOYED, self.candidate} else "unknown"
        result["hotfix_checkout_advanced"] = head == self.candidate if head in {DEPLOYED, self.candidate} else "unknown"
        if result["production_database_version"] != 2:
            result["recovery_category"] = "resume_database_state_unproven_preserve_evidence"
        return result

    def protected_unchanged(self) -> None:
        path = campaign.PROTECTED
        meta = path.lstat()
        check(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1
              and (stat.S_IMODE(meta.st_mode), meta.st_uid, meta.st_gid, meta.st_size, int(meta.st_mtime))
              == (0o750, self.owner.pw_uid, self.owner.pw_gid, 16191, 1790470113)
              and sha(path) == campaign.PROTECTED_SHA, "protected_diagnostic_changed")
        campaign.protected_file(RUNBOOK)
        book = RUNBOOK.stat()
        check(sha(RUNBOOK) == RUNBOOK_SHA
              and (stat.S_IMODE(book.st_mode), book.st_uid, book.st_gid, book.st_size, int(book.st_mtime))
              == (0o644, 0, 0, 14685, 1790525656),
              "root_runbook_changed")

    def verify_candidate(self) -> list[str]:
        check(REPO != PROD and self.candidate != DEPLOYED
              and self.git(REPO, "rev-parse", "HEAD") == self.candidate, "resume_candidate_identity")
        check(self.git(REPO, "status", "--porcelain") == "", "candidate_worktree_changes")
        check(self.git(REPO, "merge-base", BASELINE, self.candidate) == BASELINE
              and self.git(REPO, "merge-base", DEPLOYED, self.candidate) == DEPLOYED, "resume_candidate_ancestry")
        paths = campaign.git_paths(self.git_bytes(REPO, "diff", "--name-only", "--no-renames", "-z", DEPLOYED, self.candidate))
        check(paths and set(paths) <= ALLOWED_HOTFIX_PATHS, "resume_hotfix_not_ops_only")
        for tree in RUNTIME_TREES:
            check(self.git(REPO, "rev-parse", DEPLOYED + ":" + tree)
                  == self.git(REPO, "rev-parse", self.candidate + ":" + tree), "resume_runtime_tree_changed")
        check(self.git(REPO, "rev-parse", PRETAG + "^{}") == BASELINE, "predeployment_tag_mismatch")
        return paths

    def verify_checkout(self) -> str:
        head = self.git(PROD, "rev-parse", "HEAD")
        check(head in {DEPLOYED, self.candidate}, "resume_production_head_unexpected")
        check(self.git(PROD, "status", "--porcelain") == campaign.EXPECTED_STATUS, "unexpected_production_changes")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "remote_main_changed")
        self.protected_unchanged()
        return head

    def load_environment(self) -> None:
        campaign.protected_file(campaign.ENV, private=True)
        environment = campaign.parse_env(campaign.ENV.read_text())
        self.key = environment.get(environment.get("SITE_WORKFLOW_API_KEY_ENV", "SITE_WORKFLOW_API_KEY"), "")
        check(bool(self.key.strip()), "production_api_key_missing")
        configured = environment.get("OPTICABLE_AUTOMATION_DB_PATH", str(Path(environment.get(
            "SITE_WORKFLOW_OUTPUT_ROOT", "/var/lib/opticable-workflow-api/output")) / "automation/automation.db"))
        check(Path(configured).resolve() == DB and DB.is_file() and not DB.is_symlink(), "unexpected_database_location")

    def verify_live(self) -> dict:
        check(self.service_state() == "active", "production_service_not_active")
        check(self.run(["/usr/bin/systemctl", "show", SERVICE, "--property=SubState", "--value"], timeout=10) == "running",
              "production_service_not_running")
        self.wait_watchdog(self.previous_sample, 2)
        self.healthy("1.9.0", events=True)
        health = self.api("/v1/automation/execution-health")
        worker = health["recovery_worker"]
        check(worker.get("thread_alive") is True and worker.get("heartbeat_stale") is False
              and worker.get("scan_stalled") is False, "resume_recovery_worker_unhealthy")
        events = self.api("/v1/automation/event-health")
        check(set(events["statuses"]) <= {"routed"}, "resume_unresolved_event_status")
        alerts = self.api("/v1/automation/health-alerts")
        check(alerts["alerts"] == [], "resume_health_alerts_present")
        database = self.inspect_database()
        check(database["version"] == 2 and database["watchdog_sample_healthy"] is True
              and self.watchdog_fresh(database), "resume_database_or_watchdog_unhealthy")
        check(database["smoke_policy"].get("reason") == "safe_internal_smoke", "resume_unsafe_smoke_policy")
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"], timeout=30), "failed_systemd_units")
        self.mark(production_service_active=True, production_service_ready=True, production_database_version=2,
                  production_service_active_before_campaign=True, execution_health=health, event_health=events,
                  production_database_counts=database["counts"])
        return database

    def legacy_evidence(self) -> dict:
        evidence = json.loads(self.run([str(campaign.PYTHON), "-I", str(Path(__file__).resolve()),
            "--verify-legacy", str(DB), str(FROZEN)], user="opticable-workflow-api", timeout=60))
        check(evidence["result"] == "PASS" and evidence["read_only"] is True, "resume_legacy_evidence_failed")
        return evidence

    def verify_previous_recovery(self) -> None:
        result_path = ORIGINAL_WORKSPACE / "result.json"
        campaign.protected_file(result_path, private=True)
        check(result_path.stat().st_size <= 4 * 1024**2, "original_evidence_size")
        original = json.loads(result_path.read_text())
        check(original["baseline"] == BASELINE and original["candidate"] == DEPLOYED
              and original["result"] == "BLOCKED" and original["blocking_stage"] == "candidate-api-readiness"
              and original["production_migration_started"] is True and original["production_migration_completed"] is True,
              "original_migration_evidence_unexpected")
        check(original["production_migration_drill"]["result"] == "PASS", "original_migration_drill_not_verified")
        migration = original["production_migration"]
        check(migration["result"] == "PASS" and migration["previous_version"] == 1 and migration["new_version"] == 2
              and all(migration[name] == "PASS" for name in ("legacy_row_hashes", "integrity", "foreign_keys")),
              "original_migration_not_verified")
        backup, snapshot = original["predeployment_backup"], original["frozen_v1_snapshot"]
        check(backup["archive"] == str(PRE_ARCHIVE) and backup["generation"] == "20260928T115757Z"
              and backup["verify"] == "PASS" and backup["isolated_restore"]["result"] == "PASS",
              "original_prebackup_not_verified")
        campaign.protected_file(PRE_ARCHIVE, private=True)
        check(sha(PRE_ARCHIVE) == backup["archive_sha256"], "original_prebackup_hash_changed")
        sidecar = PRE_ARCHIVE.with_name(PRE_ARCHIVE.name + ".sha256")
        campaign.protected_file(sidecar, private=True)
        fields = sidecar.read_text().split()
        check(len(fields) == 2 and fields[0] == backup["archive_sha256"]
              and fields[1] in {PRE_ARCHIVE.name, str(PRE_ARCHIVE)}, "original_prebackup_sidecar")
        self.run(["/usr/local/lib/optibrain-backup/optibrain-backup.sh", "--verify", str(PRE_ARCHIVE)])
        with tarfile.open(PRE_ARCHIVE) as archive:
            member = archive.getmember("generation-20260928T115757Z/manifest.json")
            check(member.isfile() and member.size <= 4 * 1024**2, "original_backup_manifest_type")
            manifest = json.load(archive.extractfile(member))
        check(manifest["production_git_sha"] == BASELINE, "original_backup_commit_changed")
        meta = FROZEN.lstat()
        check(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1 and meta.st_uid == self.service_user.pw_uid
              and stat.S_IMODE(meta.st_mode) == 0o600, "unsafe_original_frozen_snapshot")
        check(snapshot["path"] == str(FROZEN) and snapshot["verified"] is True and snapshot["version"] == 1
              and sha(FROZEN) == snapshot["sha256"], "original_frozen_snapshot_changed")
        frozen_without_wal(FROZEN)
        frozen = self.inspect_database(FROZEN)
        check(frozen["version"] == 1 and frozen["counts"] == migration["legacy_row_counts"], "original_frozen_counts_changed")
        self.previous_sample = frozen["watchdog_sample_id"]
        evidence = self.legacy_evidence()
        self.original_digest, self.frozen_digest = sha(result_path), sha(FROZEN)
        self.prebackup_digest = backup["archive_sha256"]
        self.mark(original_campaign={"path": str(result_path), "sha256": self.original_digest,
                                    "blocking_stage": original["blocking_stage"]},
                  predeployment_backup=backup, frozen_v1_snapshot=snapshot, original_production_migration=migration,
                  production_migration_started_before_resume=True,
                  production_migration_completed_before_resume=True, production_migration_completed=True,
                  legacy_evidence=evidence)

    def preserved_recovery(self) -> None:
        check(sha(ORIGINAL_WORKSPACE / "result.json") == self.original_digest and sha(FROZEN) == self.frozen_digest,
              "original_recovery_evidence_changed")
        check(sha(PRE_ARCHIVE) == self.prebackup_digest, "original_prebackup_changed_during_closeout")
        frozen_without_wal(FROZEN)

    def execute(self) -> dict:
        self.stage_start("resume-preflight")
        paths = self.verify_candidate()
        head = self.verify_checkout()
        self.load_environment()
        self.verify_live()
        self.stage_start("verify-existing-v1-recovery-evidence")
        self.verify_previous_recovery()
        self.stage_start("resume-fresh-watchdog-and-health")
        self.verify_live()
        self.checkout_permissions(head, normalize=False)
        self.service_source_readability()
        self.mark(ops_only_paths=paths)
        self.stage_start("ops-only-checkout-fast-forward")
        check(self.verify_checkout() == head, "resume_checkout_changed_before_fast_forward")
        self.verify_live()
        if head == DEPLOYED:
            self.git(PROD, "merge", "--ff-only", self.candidate)
        check(self.git(PROD, "rev-parse", "HEAD") == self.candidate, "resume_checkout_not_candidate")
        self.mark(hotfix_checkout_advanced=True, production_checkout_advanced=True, production_git_sha=self.candidate)
        self.stage_start("ops-only-source-permissions")
        self.checkout_permissions()
        self.service_source_readability()
        self.stage_start("post-hotfix-live-verification")
        self.verify_live()
        self.verify_checkout()
        self.mark(legacy_evidence_after_hotfix=self.legacy_evidence())
        self.smoke()
        self.stage_start("post-smoke-health-and-integrity")
        self.verify_live()
        self.mark(post_smoke_legacy_evidence=self.legacy_evidence())
        post_archive, generation, _ = self.archive(self.candidate, "postdeployment")
        self.mark(postdeployment_backup_completed=True)
        self.stage_start("encrypted-offhost-download-verification")
        self.run(["/usr/bin/systemctl", "start", "optibrain-phase2a-upload.service"], timeout=2800)
        campaign.protected_file(campaign.OFFHOST_STATE, private=True)
        state = json.loads(campaign.OFFHOST_STATE.read_text())
        check(state["generation"] == generation and state["source_sha256"] == sha(post_archive)
              and state["verification_status"] == "download_hash_verified", "offhost_generation_not_verified")
        self.mark(offhost={"generation": generation, "verification": "download_hash_verified",
                          "offline_decrypt_restore": "requires_external_private_key"}, offhost_verification_completed=True)
        self.stage_start("final-health-and-preserved-evidence")
        self.verify_live()
        self.verify_checkout()
        self.checkout_permissions(normalize=False)
        self.preserved_recovery()
        self.mark(final_legacy_evidence=self.legacy_evidence())
        self.stage_start("remote-main-preflight")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE,
              "remote_changed_before_promotion")
        self.stage_start("promote-remote-main")
        self.mark(remote_main_promotion_attempted=True)
        self.git(REPO, "push", "origin", self.candidate + ":refs/heads/main")
        self.stage_start("verify-remote-main")
        check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == self.candidate, "remote_promotion_failed")
        self.mark(remote_main_promoted=True, remote_main_sha=self.candidate)
        self.stage_start("postdeployment-recovery-tag")
        posttag = "recovery/post-phase4-durable-events-v1-" + datetime.now(timezone.utc).strftime("%Y%m%d")
        self.recovery_tag(posttag, self.candidate)
        check(self.git(REPO, "rev-parse", PRETAG + "^{}") == BASELINE, "predeployment_tag_mismatch")
        self.stage_start("publish-production-recovery-tags")
        self.git(REPO, "push", "origin", PRETAG, posttag)
        tags = dict(line.split()[::-1] for line in self.git(REPO, "ls-remote", "origin",
                    "refs/tags/" + PRETAG + "^{}", "refs/tags/" + posttag + "^{}").splitlines())
        check(tags.get("refs/tags/" + PRETAG + "^{}") == BASELINE
              and tags.get("refs/tags/" + posttag + "^{}") == self.candidate, "remote_recovery_tag_verification_failed")
        self.result.update(result="PASS", production_sha=self.candidate, api_version="1.9.0", database_version=2,
                           predeployment_tag=PRETAG, postdeployment_tag=posttag, manual_recovery_required=False)
        return self.result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--verify-legacy", nargs=2, type=Path)
    args = parser.parse_args()
    if args.verify_legacy:
        check(not args.candidate and not args.plan, "invalid_read_only_mode")
        print(json.dumps(verify_legacy(*args.verify_legacy), sort_keys=True))
        return
    check(bool(args.candidate and re.fullmatch(r"[0-9a-f]{40}", args.candidate)), "invalid_candidate_sha")
    if args.plan:
        print(json.dumps({"candidate": args.candidate, "resume_from": DEPLOYED, "database_version": 2,
            "migration": "forbidden", "workflow_service_restart": "forbidden",
            "operations": ["verify healthy V2 and original recovery evidence", "ops-only fast-forward with safe source modes",
                "safe internal smoke and duplicate suppression", "V2 backup/verify/isolated restore",
                "encrypted offhost download-hash verification", "final health", "fast-forward main and publish recovery tags"]}))
        return
    check(os.geteuid() == 0, "human_root_authentication_required")
    os.umask(0o077)
    root = Path("/var/lib/optibrain/phase4")
    check(not root.is_symlink() and (root.stat().st_uid, root.stat().st_gid, stat.S_IMODE(root.stat().st_mode))
          == (0, 0, 0o700), "unsafe_phase4_recovery_root")
    fd = os.open(root / "deployment.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        meta = os.fstat(fd)
        check(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and meta.st_nlink == 1 and stat.S_IMODE(meta.st_mode) == 0o600,
              "unsafe_phase4_deployment_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        workspace = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-closeout-" + uuid4().hex[:8])
        workspace.mkdir(mode=0o700)
        driver = ResumeCloseout(args.candidate, workspace)
        result = campaign.execute_with_evidence(driver)
        try:
            campaign.write_record(workspace / "result.json", result)
        except (Exception, KeyboardInterrupt) as error:
            if result["result"] == "PASS":
                result = campaign.blocked_with_evidence(driver, RuntimeError("result_persistence_failed"), "final-result-persistence")
            result.setdefault("failure_reporting_errors", {})["result_persistence"] = type(error).__name__
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["result"] == "PASS" else 1)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
