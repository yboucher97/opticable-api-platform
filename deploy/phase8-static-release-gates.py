#!/usr/bin/env python3
"""Phase 8 data-only release gate checker. There is deliberately no execute path.

The operator must re-collect observations from their original systems before any
separate release implementation can use them. A passing packet is not deploy or
provider authorization. Candidate code is never imported or executed here.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

REPOSITORY = "yboucher97/opticable-api-platform"
BRANCH = "phase8/integrated-sales-candidate-20260930"
CANDIDATE = "dcdff624b8d04911dfb26d4af782c90527a5174f"
BASELINE = "d2ca75d588665112d1d62329abfda23dd92d533f"
CI_RUN = 36651969227
JOBS = frozenset({"workflow-api", "control-plane-worker"})
DIAGNOSTIC_SHA256 = "7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000"
AUTHORITY_PATH = Path("/etc/optibrain/phase8-release-authorization.json")
INSTALLED_ARTIFACTS = {
    "loader_sha256": Path("/usr/local/lib/optibrain/phase8-static-release-gates.py"),
    "campaign_sha256": Path("/usr/local/lib/optibrain/phase8-production-campaign.py"),
    "wrapper_sha256": Path("/usr/local/sbin/opticable-api-deploy-root"),
    "hook_sha256": Path("/usr/local/lib/optibrain/phase8-main-push-hook"),
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GENERATION = re.compile(r"[0-9]{8}T[0-9]{6}Z\Z")
RELEASE_ID = re.compile(r"phase8-[0-9]{8}-[a-z0-9]{8,32}\Z")


class GateError(ValueError):
    pass


def require(condition, gate):
    if not condition:
        raise GateError(gate)


def fields(value, expected, gate):
    require(type(value) is dict and set(value) == set(expected), gate)


def timestamp(value, gate):
    require(type(value) is str, gate)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GateError(gate) from error
    require(parsed.tzinfo is not None, gate)
    return parsed.astimezone(timezone.utc)


def digest(value, gate):
    require(type(value) is str and SHA256.fullmatch(value), gate)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_field")
        result[key] = value
    return result


def read_root_private(path):
    """Read only a single root-owned regular file below safe root-owned parents."""
    require(path.is_absolute(), "authority_path")
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "unsafe_authority_parent")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o077 and info.st_size < 65536, "unsafe_authority")
        with os.fdopen(descriptor) as stream:
            descriptor = -1
            return json.load(stream, object_pairs_hook=unique_object)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def verify_installed_artifacts(authority):
    """Bind the reviewed hashes to actual protected installed bytes."""
    for key, path in INSTALLED_ARTIFACTS.items():
        for parent in (path.parent, *path.parent.parents):
            info = parent.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                    "unsafe_installed_parent")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(descriptor)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                    and not info.st_mode & 0o022, "unsafe_installed_" + key)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                require(hashlib.file_digest(stream, "sha256").hexdigest() == authority[key],
                        "installed_" + key + "_changed")
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def validate_authority(authority, now):
    fields(authority, {"repository", "branch", "candidate", "validated_sha", "baseline",
                       "ci_run_id", "ci_jobs", "release_id", "approved_by", "issued_at",
                       "expires_at", "loader_sha256", "campaign_sha256", "wrapper_sha256",
                       "hook_sha256"}, "authority_fields")
    require(authority["repository"] == REPOSITORY and authority["branch"] == BRANCH
            and authority["candidate"] == authority["validated_sha"] == CANDIDATE
            and authority["baseline"] == BASELINE and type(authority["ci_run_id"]) is int
            and authority["ci_run_id"] == CI_RUN and type(authority["ci_jobs"]) is list
            and len(authority["ci_jobs"]) == len(JOBS)
            and all(type(name) is str for name in authority["ci_jobs"])
            and set(authority["ci_jobs"]) == JOBS,
            "authority_identity")
    require(type(authority["release_id"]) is str and RELEASE_ID.fullmatch(authority["release_id"]),
            "release_id")
    require(type(authority["approved_by"]) is str and
            re.fullmatch(r"human:[A-Za-z0-9@._-]{3,120}", authority["approved_by"]),
            "human_authority")
    issued = timestamp(authority["issued_at"], "authority_time")
    expiry = timestamp(authority["expires_at"], "authority_time")
    require(issued <= now < expiry and 0 < (expiry - issued).total_seconds() <= 7200,
            "authority_expired_or_stale")
    for key in ("loader_sha256", "campaign_sha256", "wrapper_sha256", "hook_sha256"):
        digest(authority[key], "artifact_digest")
    return issued


def validate_backup(backup, expected_sha, now, stage):
    fields(backup, {"generation", "manifest_production_sha", "archive_sha256",
                    "sidecar_sha256", "offhost_generation", "offhost_sha256",
                    "offhost_status", "created_at", "restore_at", "restore_result",
                    "restore_isolated", "journal_dedupe_result", "preserve_existing",
                    "retention_hold", "capacity_verified"}, stage + "_fields")
    require(type(backup["generation"]) is str and GENERATION.fullmatch(backup["generation"]),
            stage + "_generation")
    created = timestamp(backup["created_at"], stage + "_time")
    restored = timestamp(backup["restore_at"], stage + "_time")
    require(timedelta(0) <= now - created <= timedelta(hours=2) and
            created <= restored <= now, stage + "_stale_or_unrestored")
    digest(backup["archive_sha256"], stage + "_hash")
    require(backup["manifest_production_sha"] == expected_sha and
            backup["archive_sha256"] == backup["sidecar_sha256"] == backup["offhost_sha256"]
            and backup["offhost_generation"] == backup["generation"] and
            backup["offhost_status"] == "download_hash_verified", stage + "_recovery_mismatch")
    require(backup["restore_result"] == "PASS" and backup["restore_isolated"] is True
            and backup["journal_dedupe_result"] == "PASS" and
            backup["preserve_existing"] is True and backup["retention_hold"] is True
            and backup["capacity_verified"] is True, stage + "_recovery_unproven")


def validate_packet(authority, packet, now=None):
    """Pure offline check of a collected packet; observations need live recheck."""
    now = now or datetime.now(timezone.utc)
    validate_authority(authority, now)
    fields(packet, {"release_id", "observed_at", "repository", "branch", "remote_main",
                    "remote_branch", "baseline_ancestor", "production_sha", "production_status",
                    "diagnostic_sha256", "service_health", "public_health", "api_version",
                    "external_actions_disabled", "workflow_hashes_verified", "registration_pins_verified",
                    "inflight_provider_operation", "prior_release_reconciled", "ci", "artifacts",
                    "baseline_backup", "stage", "candidate_backup", "forward_recovery_result"},
           "packet_fields")
    require(packet["release_id"] == authority["release_id"] and
            packet["repository"] == REPOSITORY and packet["branch"] == BRANCH,
            "packet_identity")
    observed = timestamp(packet["observed_at"], "observation_time")
    require(timedelta(0) <= now - observed <= timedelta(minutes=15),
            "stale_observation")
    require(packet["remote_branch"] == CANDIDATE and packet["baseline_ancestor"] is True,
            "candidate_identity")
    require(packet["production_status"] ==
            "?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh" and
            packet["diagnostic_sha256"] == DIAGNOSTIC_SHA256 and
            packet["service_health"] == "ok" and packet["public_health"] == "ok" and
            packet["api_version"] == "1.11.0", "production_integrity")
    require(packet["external_actions_disabled"] is True and
            packet["workflow_hashes_verified"] is True and
            packet["registration_pins_verified"] is True and
            packet["inflight_provider_operation"] is False and
            packet["prior_release_reconciled"] is True, "operational_safety")
    ci = packet["ci"]
    fields(ci, {"run_id", "repository", "name", "event", "head_branch", "head_sha",
                "status", "conclusion", "jobs"}, "ci_fields")
    require(type(ci["run_id"]) is int and ci["run_id"] == CI_RUN and
            ci["repository"] == REPOSITORY and ci["name"] == "Validate API Platform" and
            ci["event"] == "push" and ci["head_branch"] == BRANCH and
            ci["head_sha"] == CANDIDATE and ci["status"] == "completed" and
            ci["conclusion"] == "success", "ci_identity")
    require(type(ci["jobs"]) is list and len(ci["jobs"]) == len(JOBS), "ci_jobs")
    require(all(type(job) is dict and set(job) == {"name", "status", "conclusion"}
                for job in ci["jobs"]), "ci_job_fields")
    require(all(type(job["name"]) is str for job in ci["jobs"]), "ci_job_name")
    require({job["name"] for job in ci["jobs"]} == JOBS and
            all(job["status"] == "completed" and job["conclusion"] == "success"
                for job in ci["jobs"]), "ci_jobs_failed")
    fields(packet["artifacts"], {"loader_sha256", "campaign_sha256", "wrapper_sha256",
                                 "hook_sha256"}, "artifact_fields")
    require(packet["artifacts"] == {key: authority[key] for key in packet["artifacts"]},
            "artifact_changed")
    require(packet["remote_main"] == BASELINE, "main_changed")
    validate_backup(packet["baseline_backup"], BASELINE, now, "baseline")
    require(type(packet["stage"]) is str and
            packet["stage"] in {"prestage", "prepromotion"}, "unknown_stage")
    if packet["stage"] == "prestage":
        require(packet["production_sha"] == BASELINE and packet["candidate_backup"] is None
                and packet["forward_recovery_result"] is None, "prestage_identity")
    else:
        require(packet["production_sha"] == CANDIDATE and
                packet["forward_recovery_result"] == "PASS", "prepromotion_identity")
        validate_backup(packet["candidate_backup"], CANDIDATE, now, "candidate")
        require(packet["candidate_backup"]["generation"] !=
                packet["baseline_backup"]["generation"], "backup_generation_reused")
    return {"result": "PASS", "stage": packet["stage"], "release_id": authority["release_id"],
            "candidate": CANDIDATE, "deployment_authorized": False,
            "provider_actions_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args()
    try:
        authority = read_root_private(AUTHORITY_PATH)
        validate_authority(authority, datetime.now(timezone.utc))
        verify_installed_artifacts(authority)
        packet = json.loads(args.packet.read_text(), object_pairs_hook=unique_object)
        result = validate_packet(authority, packet)
    except (GateError, OSError, ValueError, KeyError, TypeError) as error:
        result = {"result": "BLOCKED", "gate": str(error), "deployment_authorized": False,
                  "provider_actions_authorized": False}
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
