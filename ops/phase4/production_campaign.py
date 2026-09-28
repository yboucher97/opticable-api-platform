#!/usr/bin/env python3
"""Human-invoked, commit-pinned Phase 4 production gates and normal deployment.

Run with python3 -I. Does not change sudoers, provider scopes, backup protections,
the protected diagnostic, or the root recovery runbook. Never repairs an
ambiguous migration or automatically overwrites a production database.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
EXPECTED_STATUS = "?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
OFFHOST_STATE = Path("/var/lib/optibrain/phase2a/state.json")
UNRESOLVED_STATES = ("queued", "claimed", "running", "expired_leases", "failed", "partial",
                     "dead_letter", "human_action_required", "stale_queued", "stale_running")
FORBIDDEN_SOURCE_PATHS = {"ops/backup/optibrain-cloudflare-auth-diagnostic.sh",
                          "docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"}


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


def write_record(path: Path, value: dict) -> None:
    """Publish one durable private record without exposing a partial JSON file."""
    temporary = path.with_name("." + path.name + ".tmp")
    with temporary.open("w") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def git_paths(raw: bytes) -> list[str]:
    check(len(raw) <= 8 * 1024**2 and (not raw or raw.endswith(b"\0")), "unsafe_git_path_output")
    paths = [value.decode("utf-8", "strict") for value in raw.split(b"\0")[:-1]]
    check(len(paths) <= 4096 and len(set(paths)) == len(paths), "unsafe_git_path_count")
    for value in paths:
        check(value and len(value) <= 4096 and not value.startswith("/")
              and all(part not in {"", ".", ".."} for part in value.split("/")), "unsafe_git_relative_path")
    return paths


def index_entries(raw: bytes) -> dict[str, tuple[str, str]]:
    check(len(raw) <= 8 * 1024**2 and (not raw or raw.endswith(b"\0")), "unsafe_git_index_output")
    entries = {}
    for record in raw.split(b"\0")[:-1]:
        header, separator, name = record.partition(b"\t")
        fields = header.decode("ascii").split()
        check(separator and len(fields) == 3 and fields[2] == "0"
              and re.fullmatch(r"[0-9a-f]{40}", fields[1]), "unsafe_git_index_entry")
        path = git_paths(name + b"\0")[0]
        check(path not in entries, "duplicate_git_index_entry")
        entries[path] = (fields[0], fields[1])
    return entries


@contextmanager
def source_descriptor(repository: Path, relative: str):
    """Open through directory descriptors; never follow a parent or leaf symlink."""
    git_paths(relative.encode() + b"\0")
    descriptor = os.open(repository, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    file_descriptor = None
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                  dir_fd=descriptor)
        metadata = os.fstat(file_descriptor)
        check(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1, "unsafe_tracked_source_type")
        yield file_descriptor
        current = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
        check((current.st_dev, current.st_ino) == (metadata.st_dev, metadata.st_ino), "tracked_source_replaced")
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(descriptor)


def normalize_tracked_modes(repository: Path, paths: list[str], entries: dict[str, tuple[str, str]],
                            *, owner_uid: int, normalize: bool = True) -> dict:
    """Only changed, indexed regular files; accept Git modes or the known 077 defect."""
    targets, deleted = [], 0
    for path in paths:
        check(path not in FORBIDDEN_SOURCE_PATHS, "protected_source_path_in_candidate")
        if path not in entries:
            deleted += 1
            continue
        mode, _ = entries[path]
        check(mode in {"100644", "100755"}, "unsupported_tracked_source_type")
        targets.append((path, 0o644 if mode == "100644" else 0o755))
    # Validate the entire scope before changing any mode. Revalidate each open
    # descriptor during normalization so a replacement cannot redirect chmod.
    def validate(descriptor: int, expected: int) -> int:
        metadata = os.fstat(descriptor)
        actual = stat.S_IMODE(metadata.st_mode)
        check(metadata.st_uid == owner_uid and actual in {expected, expected & ~0o077}, "unexpected_tracked_source_mode")
        check(normalize or actual == expected, "tracked_source_mode_not_materialized")
        return actual
    for path, expected in targets:
        with source_descriptor(repository, path) as descriptor:
            validate(descriptor, expected)
    corrected = 0
    for path, expected in targets:
        with source_descriptor(repository, path) as descriptor:
            actual = validate(descriptor, expected)
            if actual != expected:
                os.fchmod(descriptor, expected)
                corrected += 1
            check(stat.S_IMODE(os.fstat(descriptor).st_mode) == expected, "tracked_source_mode_verification")
    return {"result": "PASS", "verified_files": len(targets), "normalized_files": corrected, "deleted_files_ignored": deleted}


SOURCE_READ_PROBE = r'''
import json, os, stat, sys
repository, paths = sys.argv[1], json.loads(sys.argv[2])
for relative in paths:
    parent = os.open(repository, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    leaf = None
    try:
        parts = relative.split('/')
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        if not stat.S_ISREG(os.fstat(leaf).st_mode):
            raise RuntimeError('service_source_type')
        with os.fdopen(leaf, 'rb', closefd=False) as stream:
            content = stream.read(4 * 1024**2 + 1)
        if len(content) > 4 * 1024**2:
            raise RuntimeError('service_source_size')
        if relative.endswith('.py'):
            compile(content, relative, 'exec')
    finally:
        if leaf is not None:
            os.close(leaf)
        os.close(parent)
print(json.dumps({'result':'PASS','readable_files':len(paths),'application_import_executed':False}))
'''


class Campaign:
    def __init__(self, candidate: str, root: Path) -> None:
        self.candidate, self.root = candidate, root
        self.stage = "preflight"
        self.result = {
            "baseline": BASELINE, "candidate": candidate, "result": "IN_PROGRESS",
            "recovery_workspace": str(root), "production_git_sha": "unknown", "remote_main_sha": "unknown",
            "production_service_active": "unknown", "production_service_active_before_campaign": "unknown",
            "production_database_version": "unknown", "production_service_stop_attempted": False,
            "production_service_stop_completed": False, "production_migration_started": False,
            "production_migration_completed": False, "production_checkout_advanced": "unknown",
            "production_service_restart_attempted": False, "production_service_ready": False,
            "production_smoke_completed": False, "postdeployment_backup_completed": False,
            "offhost_verification_completed": False, "remote_main_promotion_attempted": False,
            "remote_main_promoted": "unknown",
        }
        self.owner = pwd.getpwnam("optibrain")
        self.service_user = pwd.getpwnam("opticable-workflow-api")
        self.key = ""

    def run(self, argv: list[str], *, user: str | None = None, timeout: int = 900,
            umask: int | None = None, binary: bool = False) -> str | bytes:
        if user == "optibrain":
            argv = ["/usr/sbin/runuser", "-u", user, "--", *argv]
            kwargs = {}
        elif user == "opticable-workflow-api":
            kwargs = {"user": self.service_user.pw_uid, "group": self.service_user.pw_gid, "extra_groups": []}
        else:
            kwargs = {}
        if umask is not None:
            kwargs["umask"] = umask
        with (self.root / "operations.log").open("ab") as output:
            completed = subprocess.run(argv, env=SAFE_ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=output, timeout=timeout, check=False, **kwargs)
            if completed.returncode:
                # Fixed CLI tools emit bounded non-secret result categories.
                # Preserve them in the root-only record instead of discarding
                # the failed drill's reason while reporting a generic exit.
                output.write(completed.stdout[:65536])
        check(completed.returncode == 0, "fixed_operation_failed")
        return completed.stdout if binary else completed.stdout.decode("utf-8", "replace").strip()

    def git(self, repository: Path, *args: str, timeout: int = 900) -> str:
        # Only Git materialization gets 022 in its child. Root recovery artifacts
        # retain the caller's 077; no process-global umask relaxation occurs.
        options = {"umask": 0o022} if repository == PROD and args and args[0] == "merge" else {}
        return self.run(["/usr/bin/git", "-C", str(repository), *args], user="optibrain", timeout=timeout, **options)

    def git_bytes(self, repository: Path, *args: str) -> bytes:
        return self.run(["/usr/bin/git", "-C", str(repository), *args], user="optibrain", timeout=30, binary=True)

    def checkout_permissions(self, candidate: str | None = None, *, normalize: bool = True) -> dict:
        candidate = candidate or self.candidate
        check(self.git(PROD, "rev-parse", "HEAD") == candidate, "source_permissions_checkout_identity")
        check(self.git(PROD, "status", "--porcelain") == EXPECTED_STATUS, "source_permissions_worktree_changed")
        check(not self.git_bytes(PROD, "diff", "--cached", "--name-only", "-z", candidate), "source_permissions_index_changed")
        paths = git_paths(self.git_bytes(PROD, "diff", "--name-only", "--no-renames", "-z", BASELINE, candidate))
        entries = index_entries(self.git_bytes(PROD, "ls-files", "--stage", "-z"))
        result = normalize_tracked_modes(PROD, paths, entries, owner_uid=self.owner.pw_uid, normalize=normalize)
        self.mark(source_permissions=result)
        return result

    def service_source_readability(self) -> dict:
        entries = index_entries(self.git_bytes(PROD, "ls-files", "--stage", "-z"))
        paths = [path for path, (mode, _) in entries.items()
                 if ((path.startswith("apps/workflow-api/workflow/") and path.endswith(".py"))
                     or path.startswith("apps/workflow-api/config/automation/"))]
        check(paths and len(paths) <= 4096 and all(entries[path][0] in {"100644", "100755"} for path in paths),
              "unsafe_service_source_scope")
        result = json.loads(self.run([str(PYTHON), "-I", "-c", SOURCE_READ_PROBE, str(PROD), json.dumps(paths)],
                                    user="opticable-workflow-api", timeout=60))
        check(result["result"] == "PASS" and result["readable_files"] == len(paths), "service_source_readability_failed")
        self.mark(service_source_readability=result)
        return result

    def mark(self, **values) -> None:
        self.result.update(values)
        write_record(self.root / "progress.json", dict(self.result, current_stage=self.stage))

    def service_state(self) -> str:
        value = self.run(["/usr/bin/systemctl", "show", SERVICE, "--property=ActiveState", "--value"], timeout=10)
        check(value in {"active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance", "refreshing"},
              "unknown_production_service_state")
        return value

    def inspect_database(self, path: Path = DB) -> dict:
        # --inspect is read-only and does not instantiate AutomationStore.
        return json.loads(self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(path), "--inspect"],
                                  user="opticable-workflow-api", timeout=30))

    @staticmethod
    def watchdog_fresh(database: dict) -> bool:
        sample = database.get("watchdog_sample_at")
        if not isinstance(sample, str):
            return False
        try:
            observed = datetime.fromisoformat(sample.replace("Z", "+00:00"))
            return observed.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - observed).total_seconds() < 600
        except (ValueError, TypeError):
            return False

    def wait_watchdog(self, previous_id: int, version: int) -> None:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            database = self.inspect_database()
            check(database["version"] == version, "watchdog_database_version")
            if (database.get("watchdog_sample_id", 0) > previous_id
                    and database.get("watchdog_sample_healthy") is True and self.watchdog_fresh(database)):
                self.mark(fresh_watchdog_sample_id=database["watchdog_sample_id"])
                return
            time.sleep(1)
        raise RuntimeError("fresh_watchdog_readiness_timeout")

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
        for name in UNRESOLVED_STATES:
            check(health.get(name, 0) == 0, "unresolved_execution_work")
        check(self.api("/v1/automation/health-alerts")["status"] == "ok", "automation_health_alert")
        if events:
            event_health = self.api("/v1/automation/event-health")
            check(event_health["backlog"] == 0 and event_health["quarantined"] == 0, "unexpected_event_backlog")
        # Open SQLite with the service identity so any transient WAL/SHM files
        # keep the application's ownership and permissions.
        database = self.inspect_database()
        check(database["version"] == (2 if events else 1), "production_database_version")
        # Only completed is a deployable run state. This also rejects future or
        # unexpected statuses absent from the aggregate execution-health API.
        check(set(database["run_status_counts"]) <= {"completed"}, "unresolved_execution_work")
        check(database["smoke_policy"]["safe"], "unsafe_production_smoke_routing")
        check(database["watchdog_sample_at"] is not None, "watchdog_sample_missing")
        check(self.watchdog_fresh(database), "watchdog_sample_stale")

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
        self.mark()
        print("Phase 4 gate: " + name, flush=True)

    def observe_failure_state(self, result: dict) -> dict | None:
        """Independent bounded probes; a failed probe never fabricates a fact."""
        errors = result.setdefault("failure_reporting_errors", {})
        database = None
        probes = {
            "production_git_sha": lambda: self.git(PROD, "rev-parse", "HEAD", timeout=10),
            "production_git_status": lambda: self.git(PROD, "status", "--porcelain", timeout=10),
            "remote_main_sha": lambda: self.git(PROD, "ls-remote", "origin", "refs/heads/main", timeout=30).split()[0],
            "production_service_state": self.service_state,
            "production_database_version": self.inspect_database,
        }
        for name, probe in probes.items():
            try:
                value = probe()
                if name in {"production_git_sha", "remote_main_sha"}:
                    check(bool(re.fullmatch(r"[0-9a-f]{40}", value)), "uninspectable_git_identity")
                if name == "production_database_version":
                    check(type(value["version"]) is int, "uninspectable_database_version")
                    database, value = value, value["version"]
                result[name] = value
            except (Exception, KeyboardInterrupt) as error:
                result[name] = "unknown"
                errors[name] = type(error).__name__
        state = result["production_service_state"]
        result["production_service_active"] = state == "active" if state != "unknown" else "unknown"
        head, remote = result["production_git_sha"], result["remote_main_sha"]
        result["production_checkout_advanced"] = False if head == BASELINE else True if head == self.candidate else "unknown"
        result["remote_main_promoted"] = False if remote == BASELINE else True if remote == self.candidate else "unknown"
        if result["production_migration_started"] and result["production_migration_completed"] is not True:
            result["production_migration_completed"] = False if result["production_database_version"] == 1 else "unknown"
        return database

    def recover_baseline(self, result: dict, database: dict | None) -> None:
        """The only automatic recovery: proven unchanged baseline code and V1."""
        if not result["production_service_stop_attempted"]:
            baseline_observed = (result["production_git_sha"] == BASELINE
                                 and result["production_git_status"] == EXPECTED_STATUS
                                 and result["production_database_version"] == 1
                                 and result["production_service_active"] is True)
            result.update(recovery_category="before_service_stop_no_recovery" if baseline_observed
                          else "before_service_stop_unverified_manual_review",
                          manual_recovery_required=not baseline_observed)
            return
        result["manual_recovery_required"] = True
        if result["production_migration_completed"] is True:
            result["recovery_category"] = ("verified_candidate_v2_preserved_manual_review"
                if result["production_git_sha"] == self.candidate and result["production_database_version"] == 2
                else "verified_migration_current_state_unproven_manual_review")
            return
        if result["production_migration_started"]:
            result["recovery_category"] = {1: "migration_attempt_v1_preserved_manual_review",
                                          2: "unverified_v2_migration_preserved_manual_review"}.get(
                                              result["production_database_version"], "migration_state_unknown_preserved_manual_review")
            return
        proven = (result["production_service_active_before_campaign"] is True
                  and result["production_git_sha"] == BASELINE and result["production_git_status"] == EXPECTED_STATUS
                  and result["production_database_version"] == 1 and database is not None
                  and set(database["run_status_counts"]) <= {"completed"}
                  and result["production_service_state"] in {"active", "inactive", "failed"})
        if not proven:
            result["recovery_category"] = "unproven_baseline_preserved_manual_review"
            return
        # Recheck immediately before start. Neither inspection nor recovery calls
        # a migration, changes a checkout, replaces a DB, or writes remote main.
        result["recovery_category"] = "baseline_recovery_in_progress"
        check(self.git(PROD, "rev-parse", "HEAD", timeout=10) == BASELINE
              and self.git(PROD, "status", "--porcelain", timeout=10) == EXPECTED_STATUS,
              "baseline_recovery_checkout_changed")
        current = self.inspect_database()
        check(current["version"] == 1 and set(current["run_status_counts"]) <= {"completed"},
              "baseline_recovery_database_changed")
        state = self.service_state()
        check(state in {"active", "inactive", "failed"}, "baseline_recovery_service_transition")
        if state != "active":
            result["production_service_restart_attempted"] = True
            self.mark(production_service_restart_attempted=True, baseline_recovery_restart_attempted=True)
            self.run(["/usr/bin/systemctl", "start", SERVICE], timeout=60)
            self.ready("1.8.0")
            self.wait_watchdog(current["watchdog_sample_id"], 1)
        else:
            self.ready("1.8.0")
        self.healthy("1.8.0", events=False)
        result.update(production_service_ready=True, recovery_category="baseline_service_recovered",
                      manual_recovery_required=False)

    def blocked(self, exc: BaseException, blocking_stage: str) -> dict:
        result = dict(self.result, result="BLOCKED", blocking_stage=blocking_stage,
                      category=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                      manual_recovery_required=True)
        database = self.observe_failure_state(result)
        try:
            self.recover_baseline(result, database)
        except (Exception, KeyboardInterrupt) as error:
            result["failure_reporting_errors"]["baseline_recovery"] = type(error).__name__
            result.update(recovery_category="baseline_recovery_failed_manual_review", manual_recovery_required=True,
                          production_service_ready=False)
        # Recovery can itself fail after start. Observe the resulting state again
        # while retaining the original failure stage and every completed gate.
        if result["recovery_category"].startswith("baseline_"):
            self.observe_failure_state(result)
        return result

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
        self.mark(**{label + "_backup_attempt": {"generation": generation, "archive": str(archive)}})
        sidecar = archive.with_name(archive.name + ".sha256")
        protected_file(sidecar, private=True)
        fields = sidecar.read_text().split()
        check(len(fields) == 2 and fields[1] in {archive.name, str(archive)}, "backup_checksum_sidecar")
        digest = sha(archive)
        check(fields[0] == digest, "backup_checksum_mismatch")
        self.mark(**{label + "_backup_attempt": {"generation": generation, "archive": str(archive), "archive_sha256": digest}})
        self.run(["/usr/local/lib/optibrain-backup/optibrain-backup.sh", "--verify", str(archive)])
        restored = self.restore_archive(archive, digest)
        with tarfile.open(archive) as tar:
            member = "generation-" + generation + "/manifest.json"
            manifest = json.load(tar.extractfile(member))
        check(manifest["production_git_sha"] == expected_commit, "backup_source_commit_mismatch")
        self.result[label + "_backup"] = {"generation": generation, "archive": str(archive), "archive_sha256": digest,
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
        self.stage_start("preflight")
        check(REPO != PROD and self.git(REPO, "rev-parse", "HEAD") == self.candidate, "candidate_identity")
        check(self.git(REPO, "status", "--porcelain") == "", "candidate_worktree_changes")
        check(self.git(PROD, "rev-parse", "HEAD") == BASELINE, "production_head_changed")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "remote_main_changed")
        check(self.git(REPO, "merge-base", BASELINE, self.candidate) == BASELINE, "candidate_merge_base")
        candidate_paths = git_paths(self.git_bytes(REPO, "diff", "--name-only", "--no-renames", "-z", BASELINE, self.candidate))
        check(not FORBIDDEN_SOURCE_PATHS.intersection(candidate_paths), "protected_source_path_in_candidate")
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
        service_state = self.service_state()
        self.mark(production_service_active_before_campaign=service_state == "active")
        check(service_state == "active", "production_service_not_active")
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
        return self.promote(private, protected_meta, pretag, posttag)

    def promote(self, private: Path, protected_meta: os.stat_result, pretag: str, posttag: str) -> dict:
        self.stage_start("pre-stop-health")
        self.healthy("1.8.0", events=False)
        check(self.git(PROD, "rev-parse", "HEAD") == BASELINE, "production_head_changed_during_drill")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE,
              "remote_main_changed_during_drill")
        check(self.git(PROD, "status", "--porcelain") == "?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
              and sha(PROTECTED) == PROTECTED_SHA, "production_state_changed_during_drill")
        self.stage_start("stop-production-service")
        self.mark(production_service_stop_attempted=True)
        self.run(["/usr/bin/systemctl", "stop", SERVICE], timeout=60)
        check(self.service_state() == "inactive", "production_service_not_stopped")
        self.mark(production_service_stop_completed=True)
        self.stage_start("inspect-stopped-production")
        stopped = self.inspect_database()
        check(stopped["version"] == 1, "stopped_database_not_v1")
        check(set(stopped["run_status_counts"]) <= {"completed"}, "work_arrived_before_stop_preserve_evidence")
        # Freeze one additional consistent V1 rollback snapshot after stopping the
        # service. The source backup and failed-state evidence are retained.
        frozen = private / "pre-migration-frozen-v1.db"
        self.stage_start("freeze-v1-snapshot")
        self.mark(frozen_v1_snapshot={"path": str(frozen), "verified": False})
        self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(DB), "--snapshot-to", str(frozen)],
                 user="opticable-workflow-api")
        snapshot = self.inspect_database(frozen)
        check(snapshot["version"] == 1 and snapshot["counts"] == stopped["counts"] and snapshot["hashes"] == stopped["hashes"],
              "frozen_snapshot_not_verified")
        self.mark(frozen_v1_snapshot={"path": str(frozen), "sha256": sha(frozen), "version": 1, "verified": True})
        self.stage_start("advance-production-checkout")
        self.git(PROD, "merge", "--ff-only", self.candidate)
        check(self.git(PROD, "rev-parse", "HEAD") == self.candidate, "production_checkout_not_candidate")
        self.mark(production_checkout_advanced=True)
        self.stage_start("production-source-permissions")
        self.checkout_permissions()
        self.service_source_readability()
        self.stage_start("migrate-production-database")
        self.mark(production_migration_started=True)
        migration = json.loads(self.run([str(PYTHON), str(REPO / "ops/phase4/migrate_db.py"), "--db", str(DB)], user="opticable-workflow-api"))
        check(migration["result"] == "PASS" and migration["previous_version"] == 1 and migration["new_version"] == 2,
              "production_migration_failed_preserve_evidence")
        self.mark(production_migration=migration, production_migration_completed=True)
        self.stage_start("start-candidate-service")
        self.mark(production_service_restart_attempted=True)
        self.run(["/usr/bin/systemctl", "start", SERVICE], timeout=60)
        self.stage_start("candidate-api-readiness")
        self.ready("1.9.0")
        self.mark(production_service_ready=True)
        self.stage_start("candidate-watchdog-readiness")
        self.wait_watchdog(stopped["watchdog_sample_id"], 2)
        self.stage_start("candidate-health")
        self.healthy("1.9.0", events=True)
        self.smoke()
        self.stage_start("post-smoke-health")
        self.healthy("1.9.0", events=True)
        post_archive, post_generation, _ = self.archive(self.candidate, "postdeployment")
        self.mark(postdeployment_backup_completed=True)
        self.stage_start("encrypted-offhost-download-verification")
        self.run(["/usr/bin/systemctl", "start", "optibrain-phase2a-upload.service"], timeout=2800)
        state = json.loads(OFFHOST_STATE.read_text())
        check(state["generation"] == post_generation and state["source_sha256"] == sha(post_archive)
              and state["verification_status"] == "download_hash_verified", "offhost_generation_not_verified")
        self.mark(offhost={"generation": post_generation, "verification": "download_hash_verified",
                           "offline_decrypt_restore": "requires_external_private_key"}, offhost_verification_completed=True)
        self.stage_start("final-health")
        self.healthy("1.9.0", events=True)
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"]), "postdeployment_failed_units")
        check(sha(PROTECTED) == PROTECTED_SHA and (PROTECTED.stat().st_mode, PROTECTED.stat().st_uid, PROTECTED.stat().st_gid)
              == (protected_meta.st_mode, protected_meta.st_uid, protected_meta.st_gid), "protected_diagnostic_changed")
        self.stage_start("remote-main-preflight")
        check(self.git(PROD, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "remote_changed_before_promotion")
        self.stage_start("promote-remote-main")
        self.mark(remote_main_promotion_attempted=True)
        self.git(REPO, "push", "origin", self.candidate + ":refs/heads/main")
        self.stage_start("verify-remote-main")
        check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == self.candidate, "remote_promotion_failed")
        self.mark(remote_main_promoted=True)
        self.stage_start("postdeployment-recovery-tag")
        self.recovery_tag(posttag, self.candidate)
        self.stage_start("publish-production-recovery-tags")
        self.git(REPO, "push", "origin", pretag, posttag)
        self.result.update(result="PASS", production_sha=self.candidate, api_version="1.9.0", database_version=2,
                           predeployment_tag=pretag, postdeployment_tag=posttag)
        return self.result

    def smoke(self) -> None:
        self.stage_start("safe-production-smoke")
        event = {"event_type": "system.automation.smoke_test", "source": "internal", "idempotency_key": "phase4-production-smoke-" + uuid4().hex,
                 "payload": {"requested_via": "phase4-gates"}}
        self.mark(smoke_attempt={"event_type": event["event_type"], "idempotency_key": event["idempotency_key"]})
        first = self.api("/v1/automation/events", event)
        check(first["accepted"] and len(first["run_ids"]) == 1, "production_smoke_acceptance")
        run = self.api("/v1/automation/runs/" + first["run_ids"][0])
        check(run["status"] == "completed" and run["workflow_id"] == "platform.smoke-test"
              and run["event_id"] == first["event_id"] and [s["action"] for s in run["steps"]] == ["core.set", "event.emit"],
              "production_smoke_execution")
        before_duplicate = self.api("/v1/automation/events/" + first["event_id"])
        check(before_duplicate["status"] == "routed" and type(before_duplicate["duplicate_count"]) is int
              and before_duplicate["duplicate_count"] >= 0, "production_ledger_first_delivery")
        duplicate = self.api("/v1/automation/events", event)
        check(duplicate["duplicate"] and duplicate["event_id"] == first["event_id"], "production_smoke_dedupe")
        evidence = self.api("/v1/automation/events/" + first["event_id"])
        check(evidence["status"] == "routed" and type(evidence["duplicate_count"]) is int
              and evidence["duplicate_count"] > before_duplicate["duplicate_count"], "production_ledger_evidence")
        self.mark(smoke={"result": "PASS", "run_id": first["run_ids"][0], "event_id": first["event_id"],
                         "idempotency_key": event["idempotency_key"], "workflow_id": run["workflow_id"],
                         "actions": [s["action"] for s in run["steps"]],
                         "duplicate_count_before": before_duplicate["duplicate_count"],
                         "duplicate_count_after": evidence["duplicate_count"]}, production_smoke_completed=True)


def blocked_with_evidence(campaign: Campaign, exc: BaseException, stage: str) -> dict:
    # Freeze the blocking identity BEFORE any probe/recovery/reporting code.
    fallback = dict(campaign.result, result="BLOCKED", blocking_stage=stage,
                    category=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                    recovery_workspace=str(campaign.root), manual_recovery_required=True,
                    recovery_category="failure_reporting_unavailable_manual_review")
    try:
        return campaign.blocked(exc, stage)
    except (Exception, KeyboardInterrupt) as reporting_error:
        # The handler may have attempted a proven baseline restart before its
        # own later failure. Preserve its latest markers, not the earlier copy.
        fallback.update(campaign.result)
        fallback.update(result="BLOCKED", blocking_stage=stage,
                        category=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
                        recovery_workspace=str(campaign.root), manual_recovery_required=True,
                        recovery_category="failure_reporting_unavailable_manual_review")
        # Stale pre-failure observations cannot describe a partially applied
        # operation. Keep verified milestones, but label current facts unknown.
        for name in ("production_git_sha", "remote_main_sha", "production_service_active",
                     "production_database_version", "production_checkout_advanced", "remote_main_promoted"):
            fallback[name] = "unknown"
        if "hotfix_checkout_advanced" in fallback:
            fallback["hotfix_checkout_advanced"] = "unknown"
        if fallback["production_migration_started"] and fallback["production_migration_completed"] is not True:
            fallback["production_migration_completed"] = "unknown"
        fallback["failure_reporting_errors"] = {"handler": type(reporting_error).__name__}
        return fallback


def execute_with_evidence(campaign: Campaign) -> dict:
    try:
        return campaign.execute()
    except (Exception, KeyboardInterrupt) as exc:
        return blocked_with_evidence(campaign, exc, campaign.stage)


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
        result = execute_with_evidence(campaign)
        try:
            write_record(workspace / "result.json", result)
        except (Exception, KeyboardInterrupt) as reporting_error:
            # Still emit the original blocking stage/category to the terminal if
            # disk failure prevents the final durable report.
            if result["result"] == "PASS":
                result = blocked_with_evidence(campaign, RuntimeError("result_persistence_failed"), "final-result-persistence")
            result.setdefault("failure_reporting_errors", {})["result_persistence"] = type(reporting_error).__name__
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["result"] == "PASS" else 1)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
