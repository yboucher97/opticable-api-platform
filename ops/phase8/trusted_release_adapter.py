#!/usr/bin/env python3
"""Branch proposal for a fixed-source Phase 8 collector and guarded staging seam.

No CLI executes staging. Installation, authority issuance, backup creation and
the stage executor are separate reviewed work. This module never imports the
candidate checkout or accepts a caller-supplied observation packet.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
from urllib.request import Request, urlopen

GATES_PATH = Path(__file__).resolve().parents[2] / "deploy/phase8-static-release-gates.py"
spec = importlib.util.spec_from_file_location("phase8_static_release_gates", GATES_PATH)
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)

PRODUCTION = Path("/opt/opticable-api-platform")
RECOVERY = Path("/var/lib/optibrain/phase8/recovery")
ACTIVE = Path("/var/lib/optibrain/phase8/active-release.json")
BACKUPS = Path("/var/backups/optibrain")
SERVICE = "opticable-workflow-api.service"
SAFE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}


def run(*args):
    try:
        return subprocess.check_output(args, stdin=subprocess.DEVNULL, env=SAFE_ENV,
                                       text=True, timeout=25).strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise gates.GateError("source_unavailable:" + args[0]) from error


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def protected_sha(path):
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        gates.require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and
                      not info.st_mode & 0o022, "unsafe_source_parent")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        gates.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                      info.st_nlink == 1 and not info.st_mode & 0o077,
                      "unsafe_archive")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            return hashlib.file_digest(stream, "sha256").hexdigest()
    finally:
        if fd >= 0:
            os.close(fd)


def protected_bytes(path, private=True):
    """A single root-owned regular file under root-controlled directories."""
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        gates.require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and
                      not info.st_mode & 0o022, "unsafe_source_parent")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        gates.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                      info.st_nlink == 1 and not info.st_mode & (0o077 if private else 0o022)
                      and info.st_size < 100_000_000, "unsafe_source_file")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            return stream.read()
    finally:
        if fd >= 0:
            os.close(fd)


def private_json(path):
    return json.loads(protected_bytes(path), object_pairs_hook=gates.unique_object)


def github(path):
    url = "https://api.github.com/repos/" + gates.REPOSITORY + "/" + path
    with urlopen(Request(url, headers={"Accept": "application/vnd.github+json"}), timeout=20) as response:
        gates.require(response.status == 200, "github_status")
        return json.loads(response.read(1_000_001), object_pairs_hook=gates.unique_object)


def exact_ref(output, ref):
    rows = output.splitlines()
    gates.require(len(rows) == 1, "remote_ref_ambiguous")
    parts = rows[0].split("\t")
    gates.require(len(parts) == 2 and parts[1] == ref and
                  re.fullmatch(r"[0-9a-f]{40}", parts[0]), "remote_ref_identity")
    return parts[0]


def require_installed_identity():
    gates.require(Path(__file__).resolve() == gates.INSTALLED_ARTIFACTS["adapter_sha256"],
                  "branch_adapter_cannot_stage")


def backup_from_sources(release_id, label, expected_sha, now):
    """Recompute archive bytes and compare independent root-private receipts.

    The restore record must be written by the separately reviewed isolated drill.
    Its producer and permissions are part of the later installation review.
    """
    gates.require(label in {"baseline", "candidate"}, "backup_label")
    root = RECOVERY / release_id
    manifest = private_json(root / (label + "-backup.json"))
    gates.fields(manifest, {"generation", "manifest_production_sha", "created_at",
                            "preserve_existing", "retention_hold", "capacity_verified"},
                 label + "_manifest_fields")
    generation = manifest["generation"]
    gates.require(type(generation) is str and gates.GENERATION.fullmatch(generation),
                  label + "_generation")
    archive = BACKUPS / ("optibrain-backup-" + generation + ".tar.gz")
    archive_hash = protected_sha(archive)
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        expected_member = "generation-" + generation + "/manifest.json"
        matching = [member for member in members if member.name == expected_member]
        gates.require(len(matching) == 1 and matching[0].isfile() and
                      matching[0].size < 1_000_000, label + "_archive_manifest")
        embedded = json.load(stream.extractfile(matching[0]), object_pairs_hook=gates.unique_object)
        gates.require(embedded.get("production_git_sha") == expected_sha and
                      embedded.get("timestamp") == generation,
                      label + "_archive_identity")
    sidecar = protected_bytes(Path(str(archive) + ".sha256")).decode().split()
    gates.require(len(sidecar) == 2 and sidecar[0] == archive_hash and
                  sidecar[1] == str(archive), label + "_sidecar")
    offhost = private_json(root / (label + "-offhost.json"))
    gates.fields(offhost, {"generation", "source_sha256", "verification_status"},
                 label + "_offhost_fields")
    restore = private_json(root / (label + "-restore.json"))
    gates.fields(restore, {"generation", "archive_sha256", "restored_at", "result",
                           "isolated", "journal_dedupe_result"}, label + "_restore_fields")
    gates.require(offhost["generation"] == restore["generation"] == generation and
                  offhost["source_sha256"] == restore["archive_sha256"] == archive_hash,
                  label + "_source_mismatch")
    value = {"generation": generation, "manifest_production_sha": manifest["manifest_production_sha"],
             "archive_sha256": archive_hash, "sidecar_sha256": sidecar[0],
             "offhost_generation": offhost["generation"],
             "offhost_sha256": offhost["source_sha256"],
             "offhost_status": offhost["verification_status"],
             "created_at": manifest["created_at"], "restore_at": restore["restored_at"],
             "restore_result": restore["result"], "restore_isolated": restore["isolated"],
             "journal_dedupe_result": restore["journal_dedupe_result"],
             "preserve_existing": manifest["preserve_existing"],
             "retention_hold": manifest["retention_hold"],
             "capacity_verified": manifest["capacity_verified"]}
    gates.validate_backup(value, expected_sha, now, label)
    return value


class LiveCollector:
    """Fixed source reads; every observation is recollected at call time."""

    def observe(self, authority, stage, now=None):
        now = datetime.now(timezone.utc) if now is None else now
        gates.validate_authority(authority, now)
        gates.require(stage in {"prestage_identity", "baseline_recovery",
                                "prepromotion_identity"}, "unknown_stage")
        expected_stage = "prepromotion" if stage == "prepromotion_identity" else "prestage"
        refs = {}
        for name, ref in (("main", "refs/heads/main"), ("branch", "refs/heads/" + gates.BRANCH)):
            refs[name] = exact_ref(run("/usr/bin/git", "ls-remote",
                                       "https://github.com/" + gates.REPOSITORY + ".git", ref), ref)
        local = lambda *args: run("/usr/bin/git", "-c", "core.fsmonitor=false",
                                  "-c", "core.hooksPath=/dev/null", "-C", str(PRODUCTION), *args)
        prod_sha = local("rev-parse", "HEAD")
        prod_status = local("status", "--porcelain", "--untracked-files=all")
        diagnostic_hash = sha(PRODUCTION / "ops/backup/optibrain-cloudflare-auth-diagnostic.sh")
        gates.require(run("/usr/bin/systemctl", "is-active", SERVICE) == "active", "service_inactive")
        local_health = json.loads(run("/usr/bin/curl", "--fail", "--silent", "--show-error",
                                      "--max-time", "15", "http://127.0.0.1:8100/health"))
        public_health = json.loads(run("/usr/bin/curl", "--fail", "--silent", "--show-error",
                                       "--max-time", "15", "https://optibrain.opticable.ca/v1/system/health"))
        gates.require(type(local_health) is dict and type(public_health) is dict and
                      local_health.get("version") == public_health.get("version"), "health_source_mismatch")
        pid = run("/usr/bin/systemctl", "show", SERVICE, "--property=MainPID", "--value")
        gates.require(pid.isdecimal() and int(pid) > 0, "service_pid")
        effective = dict(item.split("=", 1) for item in
                         Path("/proc/" + pid + "/environ").read_bytes().decode().split("\0")
                         if "=" in item)
        gates.require(run("/usr/bin/systemctl", "show", SERVICE, "--property=MainPID", "--value") == pid,
                      "service_identity_changed")
        gates.require(all(effective.get(key, "") in {"", "observe", "disabled"} for key in
                          ("OPTIBRAIN_CRM_LEAD_WRITES", "OPTIBRAIN_SALES_DRAFTS",
                           "OPTIBRAIN_OUTBOUND_SENDS")), "effective_external_actions_enabled")
        state = private_json(ACTIVE)
        gates.fields(state, {"release_id", "candidate", "baseline", "status", "external_actions_enabled",
                             "workflow_hashes_verified", "registration_pins_verified",
                             "inflight_provider_operation", "prior_release_reconciled"}, "active_state_fields")
        gates.require(state["release_id"] == authority["release_id"] and
                      state["candidate"] == gates.CANDIDATE and state["baseline"] == gates.BASELINE and
                      state["status"] in {"prepared", "staged"} and
                      (state["status"] == "staged") == (expected_stage == "prepromotion"),
                      "active_release_identity")
        run_data = github("actions/runs/" + str(gates.CI_RUN))
        ancestry = github("compare/" + gates.BASELINE + "..." + gates.CANDIDATE)
        gates.require(ancestry.get("status") in {"ahead", "identical"} and
                      ancestry.get("base_commit", {}).get("sha") == gates.BASELINE and
                      ancestry.get("merge_base_commit", {}).get("sha") == gates.BASELINE,
                      "candidate_not_descendant")
        jobs_data = github("actions/runs/" + str(gates.CI_RUN) + "/jobs?per_page=100")
        gates.require(type(jobs_data) is dict and jobs_data.get("total_count") == len(gates.JOBS)
                      and type(jobs_data.get("jobs")) is list and
                      len(jobs_data["jobs"]) == len(gates.JOBS) and
                      all(job.get("head_sha") == gates.CANDIDATE for job in jobs_data["jobs"]),
                      "ci_job_count_or_sha")
        ci = {"run_id": run_data.get("id"), "repository": run_data.get("repository", {}).get("full_name"),
              "name": run_data.get("name"), "event": run_data.get("event"),
              "head_branch": run_data.get("head_branch"), "head_sha": run_data.get("head_sha"),
              "status": run_data.get("status"), "conclusion": run_data.get("conclusion"),
              "jobs": [{"name": job.get("name"), "status": job.get("status"),
                        "conclusion": job.get("conclusion")} for job in jobs_data["jobs"]]}
        artifacts = {}
        for key, path in gates.INSTALLED_ARTIFACTS.items():
            artifacts[key] = hashlib.sha256(protected_bytes(path, private=False)).hexdigest()
        baseline = backup_from_sources(authority["release_id"], "baseline", gates.BASELINE, now)
        candidate = (backup_from_sources(authority["release_id"], "candidate", gates.CANDIDATE, now)
                     if expected_stage == "prepromotion" else None)
        forward = (private_json(RECOVERY / authority["release_id"] / "forward-recovery.json")
                   if expected_stage == "prepromotion" else None)
        if forward is not None:
            gates.fields(forward, {"baseline_generation", "candidate_generation", "result"},
                         "forward_recovery_fields")
            gates.require(forward["baseline_generation"] == baseline["generation"] and
                          forward["candidate_generation"] == candidate["generation"],
                          "forward_recovery_identity")
        packet = {"release_id": authority["release_id"], "observed_at": now.isoformat(),
                  "repository": gates.REPOSITORY, "branch": gates.BRANCH,
                  "remote_main": refs["main"], "remote_branch": refs["branch"],
                  "baseline_ancestor": True,
                  "production_sha": prod_sha, "production_status": prod_status,
                  "diagnostic_sha256": diagnostic_hash, "service_health": local_health.get("status"),
                  "public_health": public_health.get("status"), "api_version": local_health.get("version"),
                  "external_actions_disabled": state["external_actions_enabled"] is False,
                  "workflow_hashes_verified": state["workflow_hashes_verified"],
                  "registration_pins_verified": state["registration_pins_verified"],
                  "inflight_provider_operation": state["inflight_provider_operation"],
                  "prior_release_reconciled": state["prior_release_reconciled"],
                  "ci": ci, "artifacts": artifacts, "baseline_backup": baseline,
                  "stage": expected_stage, "candidate_backup": candidate,
                  "forward_recovery_result": forward["result"] if forward else None}
        gates.validate_packet(authority, packet, datetime.now(timezone.utc))
        return packet


class GuardedStagingAdapter:
    """One-shot staging seam. The executor is supplied only by reviewed root code."""

    def __init__(self, collector, executor):
        self.collector = collector
        self.executor = executor
        self.attempted = False

    def stage_once(self):
        gates.require(not self.attempted, "staging_attempt_already_recorded_reconcile_first")
        require_installed_identity()
        authority = gates.read_root_private(gates.AUTHORITY_PATH)
        now = datetime.now(timezone.utc)
        gates.validate_authority(authority, now)
        gates.verify_installed_artifacts(authority)
        first = self.collector.observe(authority, "prestage_identity")
        gates.validate_packet(authority, first)
        second = self.collector.observe(authority, "baseline_recovery")
        gates.validate_packet(authority, second)
        gates.require(gates.timestamp(second["observed_at"], "observation_time") >
                      gates.timestamp(first["observed_at"], "observation_time"),
                      "observation_not_newer")
        gates.require(first["baseline_backup"] == second["baseline_backup"],
                      "baseline_recovery_changed")
        # claim_once must durably reserve this release before any stage action.
        gates.require(self.executor.claim_once(authority["release_id"], gates.CANDIDATE),
                      "staging_attempt_already_recorded_reconcile_first")
        self.attempted = True  # unknown executor outcome is terminal in this process
        receipt = self.executor.stage_exact(gates.CANDIDATE, gates.BASELINE, authority["release_id"])
        gates.fields(receipt, {"release_id", "candidate", "baseline", "result"}, "stage_receipt_fields")
        gates.require(receipt == {"release_id": authority["release_id"],
                                 "candidate": gates.CANDIDATE, "baseline": gates.BASELINE,
                                 "result": "STAGED"}, "stage_receipt_identity")
        observed = self.collector.observe(authority, "prepromotion_identity")
        gates.validate_packet(authority, observed)
        gates.require(gates.timestamp(observed["observed_at"], "observation_time") >
                      gates.timestamp(second["observed_at"], "observation_time"),
                      "observation_not_newer")
        gates.require(observed["baseline_backup"] == second["baseline_backup"],
                      "baseline_recovery_changed")
        return {"result": "STAGED_VERIFIED", "candidate": gates.CANDIDATE,
                "release_id": authority["release_id"], "deployment_authorized": False,
                "main_promotion_authorized": False, "provider_actions_authorized": False}
