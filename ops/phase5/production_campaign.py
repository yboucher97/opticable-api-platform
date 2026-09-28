#!/usr/bin/env python3
"""Pinned Phase 5 deployment using Phase 4 source, backup and recovery guards.

No privilege expansion, production migration, or automatic rollback.
Failure evidence preserves the actual service/source/database state for review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import tarfile
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("phase5_base_campaign", REPO / "ops/phase4/production_campaign.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
BASELINE = "209aac07160e1376381faebd86fb38a18f92582a"
base.BASELINE = BASELINE
check, sha, PROD, DB, SERVICE = base.check, base.sha, base.PROD, base.DB, base.SERVICE
RUNBOOK = PROD / "docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
RUNBOOK_SHA = "cdab559d264fb7a17c469fd10953827a98a24ac4a926939db1055522a6dfc085"
BRANCH = "hardening/phase5-business-autonomy-v1"
CHANNEL = "5062683202609281"
ORG = "5062683000000020005"
CONFIG_DIRECTORY = Path("/etc/optibrain/phase5")


class Phase5Campaign(base.Campaign):
    def __init__(self, candidate, root):
        super().__init__(candidate, root)
        self.environment = {}
        self.result.update(database_migration_required=False, main_modified=False,
                           final_baseline_sha=BASELINE,
                           notification_subscription_started=False, notification_subscription_verified=False)

    def stage_start(self, name):
        self.stage = name
        self.mark()
        print("Phase 5 gate: " + name, flush=True)

    def recovery_tag(self, name, commit):
        existing = self.git(REPO, "tag", "--list", name)
        if existing:
            check(self.git(REPO, "rev-parse", name + "^{}") == commit, "recovery_tag_conflict")
        else:
            self.git(REPO, "tag", "-a", name, "-m", "OptiBrain Phase 5 verified recovery point", commit)
        self.result[name.split("/")[-1]] = commit

    def protected_unchanged(self):
        diagnostic = base.PROTECTED.lstat()
        check(sha(base.PROTECTED) == base.PROTECTED_SHA and
              (diagnostic.st_mode, diagnostic.st_uid, diagnostic.st_gid, diagnostic.st_size, diagnostic.st_mtime_ns) == self.protected_meta,
              "protected_diagnostic_changed")
        check(sha(RUNBOOK) == RUNBOOK_SHA and sha(RUNBOOK) == self.runbook_digest, "root_runbook_changed")

    def blocked(self, exc, stage):
        result = dict(self.result, result="BLOCKED", blocking_stage=stage,
                      category=str(exc) if type(exc) is RuntimeError and re.fullmatch(r"[a-z][a-z0-9_]{0,120}", str(exc)) else type(exc).__name__,
                      manual_recovery_required=True, recovery_category="phase5_preserve_observed_state")
        self.observe_failure_state(result)
        result["main_modified"] = result["remote_main_promoted"]
        result["final_baseline_sha"] = result["remote_main_sha"]
        # Materialization/configuration may have partially succeeded before a
        # marker was written. Inspect presence/modes, never config/secret values.
        try:
            result["phase5_configuration_observed"] = {p: (stat.S_IMODE((CONFIG_DIRECTORY / p).lstat().st_mode)
                if (CONFIG_DIRECTORY / p).exists() else None) for p in ("webhooks.yaml", "delta-sync.yaml")}
            result["production_source_modes"] = self.checkout_permissions(result.get("production_git_sha")
                if re.fullmatch(r"[a-f0-9]{40}", result["production_git_sha"]) else self.candidate, normalize=False)
        except Exception as error:
            result.setdefault("failure_reporting_errors", {})["source_or_configuration_modes"] = type(error).__name__
        if result.get("postdeployment_tag"):
            try:
                remote = self.git(REPO, "ls-remote", "origin", "refs/tags/" + result["postdeployment_tag"] + "^{}", timeout=30)
                result["recovery_tag_sha"] = remote.split()[0] if remote else "absent"
                result["recovery_tag_published"] = result["recovery_tag_sha"] == self.candidate
            except Exception as error:
                result["recovery_tag_sha"] = "unknown"
                result["recovery_tag_published"] = "unknown"
                result.setdefault("failure_reporting_errors", {})["recovery_tag_sha"] = type(error).__name__
        # Never restart, overwrite a DB, reverse provider writes, or infer V1
        # recovery eligibility after a partially completed V2 campaign.
        return result

    def provider(self, mode):
        with (self.root / "provider-operations.log").open("ab") as log:
            completed = subprocess.run([str(base.PYTHON), "-I", str(REPO / "ops/phase5/production_provider.py"), "--mode", mode],
                env={**base.SAFE_ENV, **self.environment}, user=self.service_user.pw_uid,
                group=self.service_user.pw_gid, extra_groups=[], stdout=subprocess.PIPE, stderr=log,
                timeout=180, cwd=REPO / "apps/workflow-api")
            log.write(completed.stdout[:65536])
        value = json.loads(completed.stdout)
        self.mark(**{"provider_" + mode.replace("-", "_") + "_observed": value})
        check(completed.returncode == 0, "provider_gate_failed_" + mode)
        check(value["result"] == "PASS", "provider_gate_unverified")
        return value

    def configuration(self):
        """Add private callback config inside the existing backed-up /etc tree."""
        import yaml
        directory = CONFIG_DIRECTORY
        self.mark(runtime_configuration_started=True)
        directory.mkdir(mode=0o750)
        os.chown(directory, 0, self.service_user.pw_gid)
        directory.chmod(0o750)
        old_webhooks = Path(self.environment.get("OPTIBRAIN_WEBHOOK_CONFIG", str(PROD / "apps/workflow-api/config/automation/webhooks.yaml")))
        old_sync = Path(self.environment.get("OPTIBRAIN_SYNC_CONFIG", str(PROD / "apps/workflow-api/config/automation/delta-sync.yaml")))
        webhooks = yaml.safe_load(old_webhooks.read_text()) if old_webhooks.exists() else {}
        jobs = yaml.safe_load(old_sync.read_text()) if old_sync.exists() else []
        check(isinstance(webhooks, dict) and isinstance(jobs, list) and "phase5-crm-leads" not in webhooks, "existing_callback_config_collision")
        check(not any(j.get("provider") == "zoho_crm" for j in jobs), "existing_crm_sync_job_collision")
        check("OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL" not in self.environment and
              self.environment.get("OPTIBRAIN_CRM_LEAD_WRITES", "") != "phase5-lead-v1", "unexpected_phase5_runtime_policy")
        expiry = (datetime.now(timezone.utc) + timedelta(days=6)).replace(microsecond=0).isoformat()
        self.environment.update(OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL=secrets.token_urlsafe(24),
            OPTIBRAIN_PHASE5_CRM_CHANNEL_EXPIRY=expiry,
            OPTIBRAIN_PHASE5_CRM_NOTIFY_ENDPOINT="https://optibrain.opticable.ca/v1/automation/webhooks/phase5-crm-leads",
            OPTIBRAIN_CRM_DRIFT_ENABLED="true", OPTIBRAIN_WEBHOOK_CONFIG=str(directory / "webhooks.yaml"),
            OPTIBRAIN_SYNC_CONFIG=str(directory / "delta-sync.yaml"))
        webhooks["phase5-crm-leads"] = {"provider": "zoho_crm", "source_account": ORG,
            "secret_env": "OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL", "channel_id": CHANNEL, "expires_at": expiry,
            "allowed_event_types": ["zoho.crm.Leads.insert", "zoho.crm.Leads.update"], "enabled": True}
        jobs.append({"provider": "zoho_crm", "source_account": ORG, "stream": "Leads", "mode": "incremental",
                     "initial_cursor": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                     "page_limit": 100, "poll_interval_seconds": 300, "enabled": True})
        for path, content in ((directory / "webhooks.yaml", webhooks), (directory / "delta-sync.yaml", jobs)):
            base.write_record(path, content)  # JSON is a YAML subset.
            os.chown(path, 0, self.service_user.pw_gid); path.chmod(0o640)
        before = base.ENV.read_bytes()
        saved = self.root / "pre-phase5-service-environment"
        saved.write_bytes(before); saved.chmod(0o600)
        updated = "\n".join(k + "=" + shlex.quote(v) for k, v in self.environment.items()) + "\n"
        temporary = base.ENV.with_name(".opticable-workflow-api.phase5.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, updated.encode()); os.fsync(fd)
        finally: os.close(fd)
        os.replace(temporary, base.ENV)
        descriptor = os.open(base.ENV.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        self.mark(runtime_configuration_written=True, channel_id=CHANNEL, channel_expiry=expiry,
                  lead_policy="observe; no autonomous customer communication or CRM record writes")

    def promote_main(self):
        required = ("production_service_ready", "production_smoke_completed", "notification_subscription_verified",
                    "public_lead_delivery_verified", "crm_delta_fallback_verified", "provider_governance_verified",
                    "postdeployment_backup_completed", "offhost_verification_completed", "final_recovery_gates_verified")
        check(all(self.result.get(key) is True for key in required), "main_promotion_before_recovery_gates")
        self.stage_start("fast-forward-remote-main")
        remote = self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0]
        self.mark(remote_main_sha=remote, final_baseline_sha=remote)
        check(remote == BASELINE, "prepromotion_main_mismatch")
        self.git(REPO, "fetch", "origin", "main")
        check(self.git(REPO, "rev-parse", "FETCH_HEAD") == BASELINE, "prepromotion_fetched_main_mismatch")
        check(self.git(REPO, "merge-base", BASELINE, self.candidate) == BASELINE, "main_promotion_not_fast_forward")
        check(self.git(REPO, "rev-parse", "HEAD") == self.candidate and
              self.git(REPO, "branch", "--show-current") == BRANCH and not self.git(REPO, "status", "--porcelain"),
              "candidate_changed_before_main_promotion")
        self.mark(remote_main_promotion_attempted=True)
        try:
            # Normal push performs the server's atomic fast-forward check. No
            # force/lease/reset and no local main checkout or branch mutation.
            # The checked-in pre-push hook also requires the remote's advertised
            # old OID to be BASELINE. Git uses that OID for its atomic update,
            # closing the preflight/push race without any force option.
            self.git(REPO, "-c", "core.hooksPath=" + str(REPO / "ops/phase5/git-hooks"),
                     "push", "origin", self.candidate + ":refs/heads/main")
        finally:
            try:
                observed = self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0]
                check(bool(re.fullmatch(r"[a-f0-9]{40}", observed)), "main_readback_invalid")
                promoted = True if observed == self.candidate else False if observed == BASELINE else "unknown"
                self.mark(remote_main_sha=observed, remote_main_promoted=promoted,
                          main_modified=promoted, final_baseline_sha=observed)
            except Exception as error:
                self.mark(remote_main_sha="unknown", remote_main_promoted="unknown", main_modified="unknown",
                          final_baseline_sha="unknown", main_promotion_readback_error=type(error).__name__)
        check(self.result["remote_main_sha"] == self.candidate, "main_promotion_unverified")

    def publish_final_recovery_tag(self, pretag):
        check(self.result["remote_main_promoted"] is True and self.result["remote_main_sha"] == self.candidate,
              "post_tag_before_main_promotion")
        self.stage_start("publish-final-phase5-recovery-tag")
        posttag = "recovery/post-phase5-business-autonomy-v1-" + datetime.now(timezone.utc).strftime("%Y%m%d")
        self.mark(postdeployment_tag=posttag, recovery_tag_publication_attempted=True)
        self.recovery_tag(posttag, self.candidate)
        self.git(REPO, "push", "origin", pretag, posttag)
        remote = self.git(REPO, "ls-remote", "origin", "refs/tags/" + posttag + "^{}")
        check(remote.split()[0] == self.candidate, "phase5_recovery_tag_unpublished")
        self.mark(predeployment_tag=pretag, postdeployment_tag=posttag, recovery_tag_sha=self.candidate,
                  recovery_tag_published=True)
        return posttag

    def verify_final_identity(self):
        self.observe_failure_state(self.result)
        self.result["final_baseline_sha"] = self.result["remote_main_sha"]
        tag = self.git(REPO, "ls-remote", "origin", "refs/tags/" + self.result["postdeployment_tag"] + "^{}").split()[0]
        self.mark(recovery_tag_sha=tag)
        check(self.result["production_git_sha"] == self.result["remote_main_sha"] == tag == self.candidate and
              self.result["production_database_version"] == 2 and self.result["production_service_active"] is True and
              not self.result.get("failure_reporting_errors"), "final_state_unverified")

    def restored_drill(self, archive, generation, manifest, label):
        staging = Path("/var/lib/optibrain-phase5-staging")
        if not staging.exists():
            staging.mkdir(mode=0o710); os.chown(staging, 0, self.service_user.pw_gid)
            staging.chmod(0o710)
        meta = staging.lstat()
        check(stat.S_ISDIR(meta.st_mode) and (meta.st_uid, meta.st_gid, stat.S_IMODE(meta.st_mode)) == (0, self.service_user.pw_gid, 0o710), "unsafe_phase5_staging")
        private = staging / (self.root.name + "-" + label)
        private.mkdir(mode=0o700); os.chown(private, self.service_user.pw_uid, self.service_user.pw_gid)
        source = private / "restored-production-v2.db"
        expected = next(x for x in manifest["files"] if x["path"] == "database/automation.db")
        with tarfile.open(archive) as tar, source.open("xb") as out:
            stream = tar.extractfile("generation-" + generation + "/database/automation.db")
            for block in iter(lambda: stream.read(1048576), b""): out.write(block)
        source.chmod(0o600); os.chown(source, self.service_user.pw_uid, self.service_user.pw_gid)
        check(sha(source) == expected["sha256"], "restored_db_checksum")
        result = json.loads(self.run([str(base.PYTHON), str(REPO / "ops/phase5/isolated_drill.py"),
            "--source-db", str(source), "--workspace", str(private / "drill")], user="opticable-workflow-api", timeout=180))
        check(result["result"] == "PASS" and result["migration_performed"] is False, "actual_restored_v2_drill_failed")
        self.mark(**{label + "_restored_production_drill": result})

    def execute(self):
        self.stage_start("immutable-preflight")
        check(REPO != PROD and self.git(REPO, "rev-parse", "HEAD") == self.candidate, "candidate_identity")
        check(self.git(REPO, "branch", "--show-current") == BRANCH and not self.git(REPO, "status", "--porcelain"), "candidate_branch_or_dirty_state")
        check(self.git(PROD, "rev-parse", "HEAD") == BASELINE, "production_baseline_changed")
        check(self.git(REPO, "merge-base", BASELINE, self.candidate) == BASELINE, "candidate_ancestry")
        check(self.git(PROD, "status", "--porcelain") == base.EXPECTED_STATUS, "production_dirty_state")
        check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "main_changed")
        tag = "recovery/post-phase4-durable-events-v1-20260928"
        check(self.git(REPO, "ls-remote", "origin", "refs/tags/" + tag + "^{}").split()[0] == BASELINE, "phase4_recovery_tag_changed")
        paths = base.git_paths(self.git_bytes(REPO, "diff", "--name-only", "--no-renames", "-z", BASELINE, self.candidate))
        check(not base.FORBIDDEN_SOURCE_PATHS.intersection(paths), "protected_source_in_candidate")
        d = base.PROTECTED.lstat()
        self.protected_meta = (d.st_mode, d.st_uid, d.st_gid, d.st_size, d.st_mtime_ns)
        self.runbook_digest = sha(RUNBOOK)
        self.protected_unchanged()
        base.protected_file(base.ENV, private=True)
        self.environment = base.parse_env(base.ENV.read_text())
        self.key = self.environment.get(self.environment.get("SITE_WORKFLOW_API_KEY_ENV", "SITE_WORKFLOW_API_KEY"), "")
        check(bool(self.key.strip()), "production_authentication_missing")
        configured = self.environment.get("OPTICABLE_AUTOMATION_DB_PATH", str(Path(self.environment.get("SITE_WORKFLOW_OUTPUT_ROOT", "/var/lib/opticable-workflow-api/output")) / "automation/automation.db"))
        check(Path(configured).resolve() == DB, "production_database_location_changed")
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"]), "failed_systemd_units")
        self.healthy("1.9.0", events=True)
        self.stage_start("full-candidate-regression")
        summary = self.run([str(base.PYTHON), str(REPO / "ops/phase4/run_tests.py")], user="optibrain", timeout=300).splitlines()[-1]
        test = json.loads(summary); check(test["passed"] and test["tests"] >= 419 and test["subtests"] >= 374 and test["skipped"] == 0, "full_suite_failed")
        self.mark(full_suite=test)
        pre, pregen, manifest = self.archive(BASELINE, "predeployment")
        self.restored_drill(pre, pregen, manifest, "predeployment")
        self.stage_start("live-provider-governance")
        self.mark(provider_governance_before=self.provider("verify"))
        self.stage_start("predeployment-recovery-tag")
        pretag = "recovery/pre-phase5-business-autonomy-v1-" + datetime.now(timezone.utc).strftime("%Y%m%d")
        self.recovery_tag(pretag, BASELINE)
        self.healthy("1.9.0", events=True)
        check(self.git(PROD, "rev-parse", "HEAD") == BASELINE, "baseline_changed_before_stop")
        self.protected_unchanged()
        self.stage_start("stop-and-materialize-candidate")
        self.mark(production_service_stop_attempted=True)
        self.run(["/usr/bin/systemctl", "stop", SERVICE], timeout=60)
        check(self.service_state() == "inactive", "service_not_stopped")
        self.mark(production_service_stop_completed=True)
        stopped = self.inspect_database()
        check(stopped["version"] == 2 and set(stopped["run_status_counts"]) <= {"completed"}, "new_work_before_stop")
        self.git(PROD, "merge", "--ff-only", self.candidate)
        self.mark(production_checkout_advanced=True)
        self.mark(source_permissions=self.checkout_permissions(self.candidate), source_readability=self.service_source_readability())
        self.configuration()
        self.stage_start("candidate-startup-and-health")
        self.mark(production_service_restart_attempted=True)
        self.run(["/usr/bin/systemctl", "start", SERVICE], timeout=60)
        self.ready("1.10.0"); self.wait_watchdog(stopped["watchdog_sample_id"], 2)
        self.healthy("1.10.0", events=True)
        self.mark(production_service_ready=True)
        self.smoke()
        self.stage_start("additive-native-subscription")
        self.mark(notification_subscription_started=True)
        self.mark(notification_subscription=self.provider("subscribe"), notification_subscription_verified=True)
        self.stage_start("authenticated-public-lead-delivery-drill")
        delivery = self.provider("notification-proof")
        self.mark(lead_delivery=delivery)
        check(delivery["delivery_class"] == "synthetic" and delivery["duplicate"] is True and
              delivery["crm_record_writes"] == 0 and delivery["provider_emitted_event_proven"] is False, "public_delivery_evidence_invalid")
        self.mark(public_lead_delivery_verified=True)
        self.stage_start("crm-delta-fallback-verification")
        self.mark(crm_delta_fallback=self.provider("delta-proof"), crm_delta_fallback_verified=True)
        self.stage_start("durable-provider-origin-observation")
        self.mark(native_lead_delivery=self.provider("native-origin-proof"))
        self.stage_start("live-provider-noop-and-health")
        self.mark(provider_governance_after=self.provider("verify"), provider_governance_verified=True)
        self.healthy("1.10.0", events=True)
        post, generation, postmanifest = self.archive(self.candidate, "postdeployment")
        self.restored_drill(post, generation, postmanifest, "postdeployment")
        self.mark(postdeployment_backup_completed=True)
        self.stage_start("encrypted-offhost-verification")
        self.run(["/usr/bin/systemctl", "start", "optibrain-phase2a-upload.service"], timeout=2800)
        base.protected_file(base.OFFHOST_STATE, private=True)
        state = json.loads(base.OFFHOST_STATE.read_text())
        check(state["generation"] == generation and state["source_sha256"] == sha(post)
              and state["verification_status"] == "download_hash_verified", "offhost_verification_failed")
        self.mark(offhost={"generation": generation, "verification": "download_hash_verified",
                          "offline_decrypt_restore": "external_private_key_required"}, offhost_verification_completed=True)
        self.stage_start("final-health-protections-before-main-promotion")
        self.healthy("1.10.0", events=True); self.protected_unchanged(); self.checkout_permissions(self.candidate, normalize=False)
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"]), "failed_systemd_units")
        observed = self.inspect_database()
        check(observed["version"] == 2 and self.git(PROD, "rev-parse", "HEAD") == self.candidate, "candidate_final_source_database")
        self.mark(final_recovery_gates_verified=True)
        self.promote_main()
        posttag = self.publish_final_recovery_tag(pretag)
        self.stage_start("verified-final-production-state")
        self.healthy("1.10.0", events=True)
        self.protected_unchanged()
        self.mark(native_lead_delivery=self.provider("native-origin-proof"))
        self.verify_final_identity()
        self.result.update(result="PASS", api_version="1.10.0", database_version=2,
                           production_sha=self.candidate, predeployment_tag=pretag, postdeployment_tag=posttag,
                           manual_recovery_required=False)
        return self.result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    check(re.fullmatch(r"[a-f0-9]{40}", args.candidate), "invalid_candidate")
    if args.plan:
        print(json.dumps({"baseline": BASELINE, "candidate": args.candidate, "branch": BRANCH,
            "main_promotion": "fast-forward-only after every production/recovery gate", "migration": False, "gates": ["immutable preflight", "complete regression",
                "fresh backup and restored V2 drill", "live desired-state noops", "source modes", "readiness/authenticated health",
                "safe smoke", "verified additive subscription", "public authenticated lead path/dedupe", "CRM delta fallback",
                "post backup/restore", "encrypted offhost download hash", "protected files and systemd", "final authenticated health",
                "exact baseline remote main", "fast-forward main to candidate", "publish final candidate recovery tag"],
            "provider_origin_delivery": "durable pending -> verified; pending does not block deployment"}))
        return
    check(os.geteuid() == 0, "human_root_authentication_required")
    os.umask(0o077)
    parent = Path("/var/lib/optibrain/phase5")
    parent.mkdir(mode=0o700, exist_ok=True)
    meta = parent.lstat()
    check(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0 and stat.S_IMODE(meta.st_mode) == 0o700, "unsafe_phase5_root")
    fd = os.open("/var/lock/opticable-api-platform-deploy.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        meta = os.fstat(fd)
        check(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and meta.st_nlink == 1 and not meta.st_mode & 0o022, "unsafe_deployment_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        workspace = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        workspace.mkdir(mode=0o700)
        campaign = Phase5Campaign(args.candidate, workspace)
        result = base.execute_with_evidence(campaign)
        base.write_record(workspace / "result.json", result)
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["result"] == "PASS" else 1)
    finally: os.close(fd)


if __name__ == "__main__": main()
