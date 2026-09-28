#!/usr/bin/env python3
"""Human-invoked, commit-pinned Phase 4 production gates and normal deployment.

Run with python3 -I. Does not change sudoers, provider scopes, backup protections,
the protected diagnostic, or the root recovery runbook. Never repairs an
ambiguous migration or automatically overwrites a production database.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

BASELINE = "10e2d1feac9e724ee7d78ba3333a6242fde82898"
PROD = Path("/opt/opticable-api-platform")
REPO = Path(__file__).resolve().parents[2]
PYTHON = PROD / "apps/workflow-api/.venv/bin/python"
ENV = Path("/etc/opticable-workflow-api.env")
DB = Path("/var/lib/opticable-workflow-api/output/automation/automation.db")
SERVICE = "opticable-workflow-api.service"
PROTECTED = PROD / "ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
PROTECTED_SHA = "7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000"
SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


def check(condition: bool, category: str) -> None:
    if not condition:
        raise RuntimeError(category)


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def protected_file(path: Path, *, private: bool = False) -> None:
    meta = path.lstat()
    check(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and meta.st_nlink == 1
          and not meta.st_mode & (0o077 if private else 0o022), "unsafe_fixed_root_file")


def parse_env(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = shlex.split(line, comments=True)
        check(len(fields) == 1 and "=" in fields[0], "unsupported_environment_syntax")
        name, value = fields[0].split("=", 1)
        check(bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", name)) and name not in result, "duplicate_environment_setting")
        result[name] = value
    return result


class Campaign:
    def __init__(self, candidate: str, root: Path) -> None:
        self.candidate, self.root = candidate, root
        self.stage = "preflight"
        self.result = {"baseline": BASELINE, "candidate": candidate, "result": "IN_PROGRESS"}
        self.owner = pwd.getpwnam("optibrain")
        self.service_user = pwd.getpwnam("opticable-workflow-api")
        self.key = ""

    def run(self, argv: list[str], *, user: str | None = None, timeout: int = 900) -> str:
        if user == "optibrain":
            argv = ["/usr/sbin/runuser", "-u", user, "--", *argv]
            kwargs = {}
        elif user == "opticable-workflow-api":
            kwargs = {"user": self.service_user.pw_uid, "group": self.service_user.pw_gid, "extra_groups": []}
        else:
            kwargs = {}
        with (self.root / "operations.log").open("ab") as output:
            completed = subprocess.run(argv, env=SAFE_ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=output, timeout=timeout, check=False, **kwargs)
            if completed.returncode:
                # Fixed CLI tools emit bounded non-secret result categories.
                # Preserve them in the root-only record instead of discarding
                # the failed drill's reason while reporting a generic exit.
                output.write(completed.stdout[:65536])
        check(completed.returncode == 0, "fixed_operation_failed")
        return completed.stdout.decode("utf-8", "replace").strip()

    def git(self, repository: Path, *args: str) -> str:
        return self.run(["/usr/bin/git", "-C", str(repository), *args], user="optibrain")

    def api(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request("http://127.0.0.1:8100" + path, data=data,
            headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            check(response.status == 200, "api_http_status")
            return json.load(response)

    def healthy(self, version: str, *, events: bool) -> None:
        check(self.api("/health")["version"] == version, "unexpected_production_api_version")
        health = self.api("/v1/automation/execution-health")
        check(health["recovery_worker"]["healthy"], "unhealthy_recovery_worker")
        for name in ("queued", "claimed", "running", "expired_leases", "failed", "dead_letter", "human_action_required"):
            check(health.get(name, 0) == 0, "unresolved_execution_work")
        check(self.api("/v1/automation/health-alerts")["status"] == "ok", "automation_health_alert")
        if events:
            event_health = self.api("/v1/automation/event-health")
            check(event_health["backlog"] == 0 and event_health["quarantined"] == 0, "unexpected_event_backlog")
        # Open SQLite with the service identity so any transient WAL/SHM files
        # keep the application's ownership and permissions.
        database = json.loads(self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(DB), "--inspect"],
                                       user="opticable-workflow-api"))
        check(database["version"] == (2 if events else 1), "production_database_version")
        check(database["smoke_policy"]["safe"], "unsafe_production_smoke_routing")
        sample = database["watchdog_sample_at"]
        check(sample is not None, "watchdog_sample_missing")
        check(0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(sample.replace("Z", "+00:00"))).total_seconds() < 600,
              "watchdog_sample_stale")

    def ready(self, version: str) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if self.api("/health")["version"] == version:
                    return
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(0.5)
        raise RuntimeError("production_readiness_timeout")

    def stage_start(self, name: str) -> None:
        self.stage = name
        print("Phase 4 gate: " + name, flush=True)

    def restore_archive(self, archive: Path, digest: str) -> dict:
        # The existing verifier accepts positional arguments and owns its
        # root-only isolated staging. Reuse that interface exactly.
        result = json.loads(self.run(["/usr/bin/python3", "-I",
            str(REPO / "ops/backup/optibrain-restore-drill.py"), str(archive), digest]))
        check(result["result"] == "PASS" and result["source_sha256"] == digest,
              "isolated_archive_restore_failed")
        return result

    def archive(self, expected_commit: str, label: str) -> tuple[Path, str, dict]:
        self.stage_start(label + "-backup")
        started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run(["/usr/bin/systemctl", "start", "optibrain-backup.service"], timeout=1800)
        archives = sorted(Path("/var/backups/optibrain").glob("optibrain-backup-*.tar.gz"))
        check(bool(archives), "backup_missing")
        archive = archives[-1]
        protected_file(archive, private=True)
        generation = re.fullmatch(r"optibrain-backup-([0-9]{8}T[0-9]{6}Z)\.tar\.gz", archive.name)[1]
        check(generation >= started, "fresh_backup_not_created")
        sidecar = archive.with_name(archive.name + ".sha256")
        protected_file(sidecar, private=True)
        fields = sidecar.read_text().split()
        check(len(fields) == 2 and fields[1] in {archive.name, str(archive)}, "backup_checksum_sidecar")
        digest = sha(archive)
        check(fields[0] == digest, "backup_checksum_mismatch")
        self.run(["/usr/local/lib/optibrain-backup/optibrain-backup.sh", "--verify", str(archive)])
        restored = self.restore_archive(archive, digest)
        with tarfile.open(archive) as tar:
            member = "generation-" + generation + "/manifest.json"
            manifest = json.load(tar.extractfile(member))
        check(manifest["production_git_sha"] == expected_commit, "backup_source_commit_mismatch")
        self.result[label + "_backup"] = {"generation": generation, "archive_sha256": digest,
                                          "verify": "PASS", "isolated_restore": restored}
        return archive, generation, manifest

    def recovery_tag(self, name: str, commit: str) -> None:
        existing = self.run(["/usr/bin/git", "-C", str(REPO), "tag", "--list", name], user="optibrain")
        if existing:
            check(self.git(REPO, "rev-parse", name + "^{}") == commit, "recovery_tag_conflict")
        else:
            self.git(REPO, "tag", "-a", name, "-m", "OptiBrain Phase 4 verified recovery point", commit)
        self.result[name.split("/")[-1]] = commit

    def execute(self) -> dict:
        check(REPO != PROD and self.git(REPO, "rev-parse", "HEAD") == self.candidate, "candidate_identity")
        check(self.git(REPO, "status", "--porcelain") == "", "candidate_worktree_changes")
        check(self.git(PROD, "rev-parse", "HEAD") == BASELINE, "production_head_changed")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "remote_main_changed")
        check(self.git(REPO, "merge-base", BASELINE, self.candidate) == BASELINE, "candidate_merge_base")
        check(self.git(PROD, "status", "--porcelain") == "?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh", "unexpected_production_changes")
        check(sha(PROTECTED) == PROTECTED_SHA, "protected_diagnostic_changed")
        protected_meta = PROTECTED.stat()
        protected_file(ENV, private=True)
        environment = parse_env(ENV.read_text())
        self.key = environment.get(environment.get("SITE_WORKFLOW_API_KEY_ENV", "SITE_WORKFLOW_API_KEY"), "")
        check(bool(self.key.strip()), "production_api_key_missing")
        configured_db = environment.get("OPTICABLE_AUTOMATION_DB_PATH", str(Path(environment.get("SITE_WORKFLOW_OUTPUT_ROOT", "/var/lib/opticable-workflow-api/output")) / "automation/automation.db"))
        check(Path(configured_db).resolve() == DB, "unexpected_database_location")
        check(DB.is_file() and not DB.is_symlink(), "production_database_unavailable")
        space = os.statvfs("/var/backups/optibrain")
        check(space.f_bavail * space.f_frsize > 4 * 1024**3, "backup_headroom_insufficient")
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"]), "failed_systemd_units")
        self.healthy("1.8.0", events=False)
        archive, generation, manifest = self.archive(BASELINE, "predeployment")
        self.stage_start("restored-production-migration-drill")
        # /var/lib/optibrain is deliberately root-only. Put service-owned drill
        # files beneath a NEW dedicated hierarchy; never relax that boundary.
        staging_base = Path("/var/lib/optibrain-phase4-staging")
        try:
            staging_base.mkdir(mode=0o710)
            staging_base.chmod(0o710)
            os.chown(staging_base, 0, self.service_user.pw_gid)
        except FileExistsError:
            check(not staging_base.is_symlink() and
                  (staging_base.stat().st_uid, staging_base.stat().st_gid,
                   stat.S_IMODE(staging_base.stat().st_mode)) == (0, self.service_user.pw_gid, 0o710),
                  "unsafe_phase4_staging_root")
        private = staging_base / self.root.name
        private.mkdir(mode=0o700)
        os.chown(private, self.service_user.pw_uid, self.service_user.pw_gid)
        self.result["service_staging"] = str(private)
        source = private / "restored-production-v1.db"
        with tarfile.open(archive) as tar, source.open("xb") as out:
            database_member = "generation-" + generation + "/database/automation.db"
            expected = next(item for item in manifest["files"] if item["path"] == "database/automation.db")
            inp = tar.extractfile(database_member)
            for block in iter(lambda: inp.read(1048576), b""):
                out.write(block)
        source.chmod(0o600); os.chown(source, self.service_user.pw_uid, self.service_user.pw_gid)
        check(sha(source) == expected["sha256"], "restored_database_checksum")
        drill = json.loads(self.run([str(PYTHON), str(REPO / "ops/phase4/isolated_drill.py"), "--source-db", str(source),
                                    "--workspace", str(private / "production-drill")], user="opticable-workflow-api"))
        check(drill["result"] == "PASS", "production_migration_drill_failed")
        self.result["production_migration_drill"] = drill
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        pretag, posttag = "recovery/pre-phase4-durable-events-v1-" + date, "recovery/post-phase4-durable-events-v1-" + date
        self.recovery_tag(pretag, BASELINE)
        self.stage_start("fast-forward-and-tested-migration")
        self.healthy("1.8.0", events=False)
        check(self.git(PROD, "rev-parse", "HEAD") == BASELINE, "production_head_changed_during_drill")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE,
              "remote_main_changed_during_drill")
        check(self.git(PROD, "status", "--porcelain") == "?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
              and sha(PROTECTED) == PROTECTED_SHA, "production_state_changed_during_drill")
        self.run(["/usr/bin/systemctl", "stop", SERVICE])
        stopped = json.loads(self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(DB), "--inspect"],
                                      user="opticable-workflow-api"))
        check(set(stopped["run_status_counts"]) <= {"completed"}, "work_arrived_before_stop_preserve_evidence")
        # Freeze one additional consistent V1 rollback snapshot after stopping the
        # service. The source backup and failed-state evidence are retained.
        frozen = private / "pre-migration-frozen-v1.db"
        self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(DB), "--snapshot-to", str(frozen)],
                 user="opticable-workflow-api")
        self.git(PROD, "merge", "--ff-only", self.candidate)
        migration = json.loads(self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(DB)], user="opticable-workflow-api"))
        check(migration["result"] == "PASS", "production_migration_failed_preserve_evidence")
        self.result["production_migration"] = migration
        self.run(["/usr/bin/systemctl", "start", SERVICE])
        self.ready("1.9.0"); self.healthy("1.9.0", events=True)
        self.stage_start("safe-production-smoke")
        event = {"event_type": "system.automation.smoke_test", "source": "internal", "idempotency_key": "phase4-production-smoke-" + uuid4().hex,
                 "payload": {"requested_via": "phase4-gates"}}
        first = self.api("/v1/automation/events", event)
        check(first["accepted"] and len(first["run_ids"]) == 1, "production_smoke_acceptance")
        run = self.api("/v1/automation/runs/" + first["run_ids"][0])
        check(run["status"] == "completed" and [s["action"] for s in run["steps"]] == ["core.set", "event.emit"], "production_smoke_execution")
        duplicate = self.api("/v1/automation/events", event)
        check(duplicate["duplicate"] and duplicate["event_id"] == first["event_id"], "production_smoke_dedupe")
        evidence = self.api("/v1/automation/events/" + first["event_id"])
        check(evidence["status"] == "routed" and evidence["duplicate_count"] >= 1, "production_ledger_evidence")
        self.result["smoke"] = {"result": "PASS", "run_id": first["run_ids"][0], "event_id": first["event_id"], "idempotency_key": event["idempotency_key"]}
        self.healthy("1.9.0", events=True)
        post_archive, post_generation, _ = self.archive(self.candidate, "postdeployment")
        self.stage_start("encrypted-offhost-download-verification")
        self.run(["/usr/bin/systemctl", "start", "optibrain-phase2a-upload.service"], timeout=2800)
        state = json.loads(Path("/var/lib/optibrain/phase2a/state.json").read_text())
        check(state["generation"] == post_generation and state["source_sha256"] == sha(post_archive)
              and state["verification_status"] == "download_hash_verified", "offhost_generation_not_verified")
        self.result["offhost"] = {"generation": post_generation, "verification": "download_hash_verified", "offline_decrypt_restore": "requires_external_private_key"}
        self.stage_start("final-health-and-fast-forward-main")
        self.healthy("1.9.0", events=True)
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"]), "postdeployment_failed_units")
        check(sha(PROTECTED) == PROTECTED_SHA and (PROTECTED.stat().st_mode, PROTECTED.stat().st_uid, PROTECTED.stat().st_gid)
              == (protected_meta.st_mode, protected_meta.st_uid, protected_meta.st_gid), "protected_diagnostic_changed")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "remote_changed_before_promotion")
        self.git(REPO, "push", "origin", self.candidate + ":refs/heads/main")
        check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == self.candidate, "remote_promotion_failed")
        self.recovery_tag(posttag, self.candidate)
        self.git(REPO, "push", "origin", pretag, posttag)
        self.result.update(result="PASS", production_sha=self.candidate, api_version="1.9.0", database_version=2,
                           predeployment_tag=pretag, postdeployment_tag=posttag)
        return self.result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    check(bool(re.fullmatch(r"[0-9a-f]{40}", args.candidate)), "invalid_candidate_sha")
    if args.plan:
        print(json.dumps({"baseline": BASELINE, "candidate": args.candidate, "operations": ["preflight", "fresh backup and isolated archive restore",
            "migration drill on restored production DB", "stop service and snapshot V1", "fast-forward production", "tested V1 to V2 migration",
            "bounded readiness and safe smoke", "fresh V2 backup and isolated restore", "encrypted offhost download verification", "fast-forward main and recovery tags"]}))
        return
    check(os.geteuid() == 0, "human_root_authentication_required")
    os.umask(0o077)
    root = Path("/var/lib/optibrain/phase4")
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        check(not root.is_symlink() and (root.stat().st_uid, root.stat().st_gid, stat.S_IMODE(root.stat().st_mode))
              == (0, 0, 0o700), "unsafe_phase4_recovery_root")
    fd = os.open(root / "deployment.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        meta = os.fstat(fd)
        check(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and meta.st_nlink == 1 and stat.S_IMODE(meta.st_mode) == 0o600,
              "unsafe_phase4_deployment_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        workspace = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        workspace.mkdir(mode=0o700)
        campaign = Campaign(args.candidate, workspace)
        try:
            result = campaign.execute()
        except Exception as exc:
            result = dict(campaign.result, result="BLOCKED", blocking_stage=campaign.stage,
                          category=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                          recovery_workspace=str(workspace), production_database_overwritten=False)
        (workspace / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["result"] == "PASS" else 1)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
