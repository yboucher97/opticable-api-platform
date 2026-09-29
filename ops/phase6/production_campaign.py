#!/usr/bin/env python3
"""Human-root, exact-release Phase6 staged recovery campaign. Default is plan only.

No privilege expansion, environment edit, DB migration, provider mutation or
automatic rollback. Root approval and a frozen source bundle are prerequisites.
The existing forced SSH command is reconciliation-only for Phase6.
"""
from datetime import datetime, timezone
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import time

REPO = Path(__file__).resolve().parents[2]
BASELINE = "52f11d4fc14d8582c03837e0317f849efe8aa3d7"
BRANCH = "phase6/sales-autonomy-v1"
RECOVERY = "recovery/post-phase5-business-autonomy-v1-20260928"
AUTHORIZATION = Path("/etc/optibrain/phase6-release-authorization.json")
API_VERSION = "1.11.0"
ACTIVE_RELEASE = Path("/var/lib/optibrain/phase6/active-release.json")
spec = importlib.util.spec_from_file_location("phase6_recovery_primitives", REPO / "ops/phase5/production_campaign.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
base = legacy.base
base.BASELINE = BASELINE  # Private module; never changes Phase4/5 imports used elsewhere.
check = base.check

STAGES = ("preflight", "provider-governance-readonly", "fresh-baseline-backup", "baseline-restore", "baseline-offhost",
          "pre-release-reference", "staged-deployment", "candidate-health-smoke",
          "candidate-backup", "candidate-restore", "rollback-proof", "candidate-offhost",
          "guarded-main-promotion", "ci-deploy-reconciliation", "final-equality",
          "post-release-reference", "final-backup-verification")


def validate_authorization(value, candidate, now=None):
    now = now or datetime.now(timezone.utc)
    required = {"candidate", "baseline", "branch", "approved_by", "approved_at", "expires_at",
                "campaign_sha256", "validated_sha", "ci_run_id", "full_tests", "subtests",
                "focused_tests", "failures", "errors", "skipped", "release_id"}
    check(isinstance(value, dict) and set(value) == required, "authorization_fields")
    check(re.fullmatch(r"[a-f0-9]{40}", candidate) and candidate != BASELINE, "candidate_sha")
    check(value["candidate"] == value["validated_sha"] == candidate and
          value["baseline"] == BASELINE and value["branch"] == BRANCH, "authorization_identity")
    check(isinstance(value["approved_by"], str) and re.fullmatch(r"human:[A-Za-z0-9@._-]{3,120}", value["approved_by"]), "human_authorization_required")
    check(isinstance(value["release_id"], str) and re.fullmatch(r"[0-9]{8}-[a-z0-9-]{3,48}", value["release_id"]), "release_identity")
    check(isinstance(value["campaign_sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["campaign_sha256"]), "campaign_digest")
    approved, expires = (datetime.fromisoformat(value[k].replace("Z", "+00:00")) for k in ("approved_at", "expires_at"))
    check(approved.tzinfo is not None and expires.tzinfo is not None and
          approved <= now < expires and 0 < (expires - approved).total_seconds() <= 7200, "authorization_lifetime")
    for key, minimum in (("full_tests", 556), ("subtests", 495), ("focused_tests", 84), ("ci_run_id", 1)):
        check(type(value[key]) is int and value[key] >= minimum, "validation_evidence")
    check(all(type(value[k]) is int and value[k] == 0 for k in ("failures", "errors", "skipped")), "validation_not_clean")
    return value


def read_authorization(candidate):
    base.protected_file(AUTHORIZATION, private=True)
    value = validate_authorization(json.loads(AUTHORIZATION.read_text()), candidate)
    check(value["campaign_sha256"] == base.sha(Path(__file__)), "approved_campaign_changed")
    return value


def execute_stages(backend):
    """Ordered durable gates; an exception never advances to the next operation."""
    completed = []
    for stage in STAGES:
        if hasattr(backend, "authorization"):
            validate_authorization(backend.authorization, backend.candidate)
        backend.stage_start(stage)
        backend.perform(stage)
        completed.append(stage)
        backend.mark(completed_gates=list(completed))
    return completed


class Phase6Campaign(legacy.Phase5Campaign):
    def __init__(self, authorization, root):
        super().__init__(authorization["candidate"], root)
        self.authorization = authorization
        self.result.update(baseline=BASELINE, api_version=API_VERSION, main_modified=False,
                           database_migration_required=False, external_actions_enabled=False)
        self.deploy_lock = None
        self.pre = self.post = None
        self.environment_digest = None

    def run(self, argv, **kwargs):
        # Reuse V2 extraction/ownership but invoke the new version-bound drill.
        argv = [str(REPO / "ops/phase6/isolated_drill.py") if arg == str(REPO / "ops/phase5/isolated_drill.py") else arg for arg in argv]
        if any(Path(arg).name == "migrate_db.py" for arg in argv):
            check("--inspect" in argv, "production_database_mutation_forbidden")
        check(not any(arg in {"subscribe", "notification-proof", "delta-proof"} for arg in argv), "provider_write_mode_forbidden")
        return super().run(argv, **kwargs)

    def protections(self):
        self.protected_unchanged()
        check(base.sha(base.ENV) == self.environment_digest, "production_environment_changed")
        check(self.git(base.PROD, "status", "--porcelain", "--untracked-files=all") == base.EXPECTED_STATUS, "production_dirty")
        check(not self.git(base.PROD, "diff", "--cached", "--name-only"), "production_index_dirty")
        check(not self.run(["/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager"]), "failed_systemd_units")

    def git(self, repository, *args, timeout=900):
        if repository == REPO:
            return self.run(["/usr/bin/git", "-C", str(repository), *args], timeout=timeout)
        return super().git(repository, *args, timeout=timeout)

    def git_bytes(self, repository, *args):
        if repository == REPO:
            return self.run(["/usr/bin/git", "-C", str(repository), *args], timeout=30, binary=True)
        return super().git_bytes(repository, *args)

    def api(self, path, body=None):
        if body is not None:
            check(path == "/v1/automation/events" and body.get("event_type") == "system.automation.smoke_test"
                  and body.get("source") == "internal", "unsafe_campaign_api_mutation")
        return super().api(path, body)

    def restored_drill(self, archive, generation, manifest, label):
        # Existing service-owned private staging/extraction, with version-bound V2 proof.
        super().restored_drill(archive, generation, manifest, label)
        private = Path("/var/lib/optibrain-phase5-staging") / (self.root.name + "-" + label)
        self.mark(**{label + "_restore_workspace": str(private)})

    def audit_routes(self, candidate=False):
        import yaml
        spec = importlib.util.spec_from_file_location("phase6_definition_hash", REPO / "ops/phase6/inspect_workflows.py")
        inspector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inspector)
        workflows = json.loads(self.run([str(base.PYTHON), "-I", str(REPO / "ops/phase6/inspect_workflows.py")],
                                        user="opticable-workflow-api", timeout=30))["workflows"]
        shipped = REPO / "apps/workflow-api/config/automation/workflows"
        checked = []
        for raw in workflows:
            document = raw
            # Reject custom active routing before switching or sending internal smoke.
            if not document.get("enabled", True):
                continue
            matches = [p for p in shipped.glob("*.yaml") if yaml.safe_load(p.read_text()).get("id") == document.get("workflow_id")]
            check(len(matches) == 1, "unreviewed_custom_active_workflow")
            expected = yaml.safe_load(matches[0].read_text())
            if not candidate:
                relative = str(matches[0].relative_to(REPO))
                try:
                    expected = yaml.safe_load(self.git(REPO, "show", BASELINE + ":" + relative))
                except RuntimeError:
                    raise RuntimeError("unexpected_new_workflow_on_baseline") from None
            check(document["definition_sha256"] == inspector.definition_hash(expected), "unreviewed_workflow_definition")
            if candidate:
                check(not set(document["actions"]) & {"lifecycle.mail_reply_approved", "lifecycle.mail_send_approved_v2"}, "legacy_or_outbound_route_enabled")
            checked.append(document.get("workflow_id"))
        self.mark(reviewed_workflow_ids=checked)

    def source(self):
        check(REPO != base.PROD and self.git(REPO, "rev-parse", "HEAD") == self.candidate and
              self.git(REPO, "branch", "--show-current") == BRANCH and
              not self.git(REPO, "status", "--porcelain", "--untracked-files=all"), "candidate_source_identity")
        check(self.git(REPO, "ls-remote", "origin", "refs/heads/" + BRANCH).split()[0] == self.candidate, "remote_candidate_changed")
        check(self.git(REPO, "merge-base", BASELINE, self.candidate) == BASELINE, "candidate_not_descendant")
        paths = base.git_paths(self.git_bytes(REPO, "diff", "--name-only", "--no-renames", "-z", BASELINE, self.candidate))
        check(not base.FORBIDDEN_SOURCE_PATHS.intersection(paths), "protected_source_changed")
        # Human execution requires a cold frozen bundle, not writable branch files.
        for relative in base.index_entries(self.git_bytes(REPO, "ls-files", "--stage", "-z")):
            path = REPO / relative
            meta = path.lstat()
            check(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and not meta.st_mode & 0o022 and meta.st_nlink == 1, "source_bundle_not_root_frozen")
        api = (REPO / "apps/workflow-api/workflow/api.py").read_text()
        check('API_VERSION = "1.11.0"' in api and "register_outbound_mail_action" not in api and
              "install_operator_outbound_routes" not in api, "release_exposure_or_version")

    def github(self, suffix):
        raw = self.run(["/usr/bin/curl", "--fail", "--silent", "--show-error", "--max-time", "20",
                        "https://api.github.com/repos/yboucher97/opticable-api-platform/" + suffix], timeout=30)
        return json.loads(raw)

    def offhost(self, backup):
        archive, generation, _ = backup
        self.run(["/usr/bin/systemctl", "start", "--wait", "optibrain-phase2a-upload.service"], timeout=2800)
        self.verify_backup_receipt(backup)
        self.mark(**{self.stage.replace("-", "_"): {"generation": generation, "source_sha256": base.sha(archive), "status": "download_hash_verified"}})

    def verify_backup_receipt(self, backup):
        archive, generation, _ = backup
        base.protected_file(base.OFFHOST_STATE, private=True)
        receipt = json.loads(base.OFFHOST_STATE.read_text())
        check(receipt["generation"] == generation and receipt["source_sha256"] == base.sha(archive) and
              receipt["verification_status"] == "download_hash_verified", "offhost_wrong_generation_or_hash")
        self.run(["/usr/local/lib/optibrain-backup/optibrain-backup.sh", "--verify", str(archive)])

    def reference(self, kind, commit):
        tag = "recovery/" + kind + "-phase6-sales-autonomy-v1-" + self.authorization["release_id"]
        check(not self.git(REPO, "ls-remote", "origin", "refs/tags/" + tag), "recovery_reference_already_exists")
        check(not self.git(REPO, "tag", "--list", tag), "local_recovery_reference_already_exists")
        self.git(REPO, "tag", "-a", tag, commit, "-m", "Verified Phase6 " + kind + " recovery checkpoint")
        try:
            self.git(REPO, "push", "origin", "refs/tags/" + tag)
        finally:
            observed = self.git(REPO, "ls-remote", "origin", "refs/tags/" + tag + "^{}")
            self.mark(**{kind + "_reference_readback": observed.split()[0] if observed else "absent"})
        check(observed and observed.split()[0] == commit, "recovery_reference_unverified")

    def policies(self):
        check(all(self.environment.get(key, "") in {"", "observe", "disabled"} for key in
                  ("OPTIBRAIN_CRM_LEAD_WRITES", "OPTIBRAIN_SALES_DRAFTS", "OPTIBRAIN_OUTBOUND_SENDS")), "external_policy_enabled")
        # File values alone are insufficient: require no unit drop-ins or overrides.
        unit = self.run(["/usr/bin/systemctl", "show", base.SERVICE, "--property=DropInPaths", "--value"])
        check(not unit, "unreviewed_systemd_overrides")
        pid = int(self.run(["/usr/bin/systemctl", "show", base.SERVICE, "--property=MainPID", "--value"]))
        check(pid > 0, "service_identity_missing")
        effective = dict(item.split("=", 1) for item in Path(f"/proc/{pid}/environ").read_bytes().decode().split("\0") if "=" in item)
        check(all(effective.get(k, "") in {"", "observe", "disabled"} for k in
                  ("OPTIBRAIN_CRM_LEAD_WRITES", "OPTIBRAIN_SALES_DRAFTS", "OPTIBRAIN_OUTBOUND_SENDS")), "effective_external_policy_enabled")

    def rollback_proof(self):
        # Restore baseline code alongside baseline BACKUP data, never the live DB.
        cold = self.root / "baseline-code"
        cold.mkdir(mode=0o755)
        archive = self.root / "baseline-source.tar"
        self.git(REPO, "archive", "--format=tar", "--output=" + str(archive), BASELINE)
        with tarfile.open(archive) as handle:
            check(all(member.isfile() or member.isdir() for member in handle.getmembers()), "unsafe_baseline_archive")
            handle.extractall(cold, filter="data")
        # /var/lib/optibrain is private; service-owned staging gives no root workspace access.
        private = Path(self.result["postdeployment_restore_workspace"])
        public = private / "baseline-code"
        self.run(["/usr/bin/cp", "-a", str(cold), str(public)])
        self.run(["/usr/bin/chmod", "-R", "a+rX", str(public)])
        source = private / "restored-production-v2.db"
        value = json.loads(self.run([str(base.PYTHON), str(public / "ops/phase5/isolated_drill.py"),
                                   "--source-db", str(source), "--workspace", str(private / "rollback-drill")],
                                  user="opticable-workflow-api", timeout=240))
        check(value["result"] == "PASS" and value["source_unchanged"] is True and value["migration_performed"] is False, "baseline_rollback_drill")
        self.mark(rollback_proof={"baseline": BASELINE, "schema": 2, "result": "PASS", "live_db_restored": False})

    def perform(self, stage):
        if stage == "preflight":
            self.source()
            check(self.git(base.PROD, "rev-parse", "HEAD") == BASELINE, "production_baseline_changed")
            check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "main_baseline_changed")
            check(self.git(REPO, "ls-remote", "origin", "refs/tags/" + RECOVERY + "^{}").split()[0] == BASELINE, "phase5_reference_changed")
            d = base.PROTECTED.lstat()
            self.protected_meta = (d.st_mode, d.st_uid, d.st_gid, d.st_size, d.st_mtime_ns)
            self.runbook_digest = base.sha(legacy.RUNBOOK)
            base.protected_file(base.ENV, private=True)
            self.environment_digest = base.sha(base.ENV)
            self.environment = base.parse_env(base.ENV.read_text())
            self.key = self.environment.get(self.environment.get("SITE_WORKFLOW_API_KEY_ENV", "SITE_WORKFLOW_API_KEY"), "")
            check(bool(self.key), "production_authentication_missing")
            self.protections(); self.policies(); self.healthy("1.10.0", events=True); self.audit_routes()
            configured_db = self.environment.get("OPTICABLE_AUTOMATION_DB_PATH", str(Path(self.environment.get("SITE_WORKFLOW_OUTPUT_ROOT", "/var/lib/opticable-workflow-api/output")) / "automation/automation.db"))
            check(Path(configured_db).resolve() == base.DB, "production_database_location_changed")
            ci = self.github("actions/runs/" + str(self.authorization["ci_run_id"]))
            check(ci["head_sha"] == self.candidate and ci["name"] == "Validate API Platform" and
                  ci["head_branch"] == BRANCH and ci["conclusion"] == "success", "candidate_ci_not_green")
            wrapper = Path("/usr/local/sbin/opticable-api-deploy-root")
            base.protected_file(wrapper)
            check(base.sha(wrapper) == base.sha(REPO / "deploy/production-root-command.sh"), "deploy_trust_chain_not_hardened")
            check(not ACTIVE_RELEASE.exists() and not ACTIVE_RELEASE.is_symlink(), "previous_release_requires_manual_review")
            check(os.statvfs("/var/backups/optibrain").f_bavail * os.statvfs("/var/backups/optibrain").f_frsize > 4 * 1024**3, "backup_capacity")
            # Serialize staging with the automatic production deploy driver.
            descriptor = os.open("/var/lock/opticable-api-platform-deploy.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            self.deploy_lock = os.fdopen(descriptor, "r+")
            metadata = os.fstat(descriptor)
            check(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and metadata.st_nlink == 1
                  and not metadata.st_mode & 0o022, "unsafe_deploy_lock")
            fcntl.flock(self.deploy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.git(REPO, "-c", "core.hooksPath=" + str(REPO / "ops/phase6/git-hooks"), "push", "--dry-run", "origin", self.candidate + ":refs/heads/main")
        elif stage == "provider-governance-readonly":
            self.mark(provider_governance=self.provider("verify"))
        elif stage == "fresh-baseline-backup":
            check(len(list(Path("/var/backups/optibrain").glob("optibrain-backup-*.tar.gz"))) <= 5, "two_generation_retention_headroom_required")
            self.pre = self.archive(BASELINE, "predeployment")
        elif stage == "baseline-restore": self.restored_drill(*self.pre, "predeployment")
        elif stage == "baseline-offhost": self.offhost(self.pre)
        elif stage == "pre-release-reference": self.reference("pre", BASELINE)
        elif stage == "staged-deployment":
            self.source(); self.protections(); self.policies(); self.healthy("1.10.0", events=True)
            check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "main_changed_before_stage")
            check(self.git(base.PROD, "rev-parse", "HEAD") == BASELINE, "production_changed_before_stage")
            self.git(base.PROD, "fetch", "origin", BRANCH)
            check(self.git(base.PROD, "rev-parse", "FETCH_HEAD") == self.candidate, "candidate_fetch_identity")
            check(self.git(base.PROD, "merge-base", BASELINE, self.candidate) == BASELINE, "production_candidate_ancestry")
            base.write_record(ACTIVE_RELEASE, {"baseline": BASELINE, "candidate": self.candidate, "status": "staging"})
            self.mark(production_service_stop_attempted=True)
            self.run(["/usr/bin/systemctl", "stop", base.SERVICE], timeout=60)
            check(self.service_state() == "inactive", "service_not_stopped")
            self.mark(production_service_stop_completed=True)
            db = self.inspect_database()
            check(db["version"] == 2 and set(db["run_status_counts"]) <= {"completed"}, "new_work_before_stage")
            self.git(base.PROD, "merge", "--ff-only", self.candidate)
            self.mark(production_checkout_advanced=True)
            self.checkout_permissions(); self.service_source_readability()
            self.protected_unchanged()
            self.mark(production_service_restart_attempted=True)
            self.run(["/usr/bin/systemctl", "start", base.SERVICE], timeout=60)
            self.ready(API_VERSION); self.wait_watchdog(db["watchdog_sample_id"], 2)
            base.write_record(ACTIVE_RELEASE, {"baseline": BASELINE, "candidate": self.candidate, "status": "staged"})
        elif stage == "candidate-health-smoke":
            self.protections(); self.policies(); self.healthy(API_VERSION, events=True); self.audit_routes(candidate=True)
            self.smoke(); self.healthy(API_VERSION, events=True)
        elif stage == "candidate-backup":
            check(len(list(Path("/var/backups/optibrain").glob("optibrain-backup-*.tar.gz"))) < 7, "retention_headroom_required")
            self.post = self.archive(self.candidate, "postdeployment")
        elif stage == "candidate-restore": self.restored_drill(*self.post, "postdeployment")
        elif stage == "rollback-proof": self.rollback_proof()
        elif stage == "candidate-offhost": self.offhost(self.post)
        elif stage == "guarded-main-promotion":
            self.source(); self.protections(); self.policies(); self.healthy(API_VERSION, events=True)
            check(self.git(base.PROD, "rev-parse", "HEAD") == self.candidate, "candidate_not_staged")
            check(self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0] == BASELINE, "main_changed_before_promotion")
            if self.deploy_lock: self.deploy_lock.close(); self.deploy_lock = None
            self.mark(remote_main_promotion_attempted=True)
            try:
                self.git(REPO, "-c", "core.hooksPath=" + str(REPO / "ops/phase6/git-hooks"), "push", "origin", self.candidate + ":refs/heads/main")
            finally:
                observed = self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0]
                self.mark(remote_main_sha=observed, remote_main_promoted=observed == self.candidate)
            check(observed == self.candidate, "main_promotion_unverified")
            base.write_record(ACTIVE_RELEASE, {"baseline": BASELINE, "candidate": self.candidate, "status": "promoted"})
        elif stage == "ci-deploy-reconciliation":
            end = time.monotonic() + 1200
            while time.monotonic() < end:
                runs = self.github("actions/runs?head_sha=" + self.candidate + "&per_page=100")["workflow_runs"]
                selected = {name: next((r for r in runs if r["name"] == name and r["head_branch"] == "main"), None)
                            for name in ("Validate API Platform", "Deploy API Platform")}
                check(all(r is None or r["conclusion"] not in {"failure", "cancelled", "timed_out", "action_required"} for r in selected.values()), "ci_or_deploy_failed")
                if all(r and r["status"] == "completed" and r["conclusion"] == "success" for r in selected.values()):
                    self.mark(ci_deploy_runs={name: r["id"] for name, r in selected.items()}); break
                time.sleep(5)
            else: raise RuntimeError("ci_deploy_reconciliation_timeout")
        elif stage == "final-equality":
            self.protections(); self.policies(); self.healthy(API_VERSION, events=True)
            check(self.git(base.PROD, "rev-parse", "HEAD") == self.candidate == self.git(REPO, "ls-remote", "origin", "refs/heads/main").split()[0], "final_identity")
        elif stage == "post-release-reference": self.reference("post", self.candidate)
        elif stage == "final-backup-verification":
            self.verify_backup_receipt(self.post)
            base.write_record(ACTIVE_RELEASE, {"baseline": BASELINE, "candidate": self.candidate, "status": "complete"})
        else: raise RuntimeError("unknown_gate")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    check(bool(re.fullmatch(r"[a-f0-9]{40}", args.candidate)), "candidate_sha")
    if not args.execute:
        print(json.dumps({"mode": "plan_only", "candidate": args.candidate, "baseline": BASELINE,
                          "gates": STAGES, "authorization": str(AUTHORIZATION), "migration": False,
                          "provider_writes": "not authorized", "automatic_rollback": False})); return
    check(os.geteuid() == 0, "human_root_authentication_required")
    authorization = read_authorization(args.candidate)
    os.umask(0o077)
    parent = Path("/var/lib/optibrain/phase6")
    parent.mkdir(mode=0o700, exist_ok=True)
    info = parent.lstat()
    check(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700, "unsafe_recovery_root")
    root = parent / authorization["release_id"]
    root.mkdir(mode=0o700, exist_ok=False)  # Existing attempt can never be blindly rerun.
    campaign = Phase6Campaign(authorization, root)
    with (parent / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            execute_stages(campaign)
            result = dict(campaign.result, result="PASS", production_sha=campaign.candidate)
        except BaseException as error:
            result = campaign.blocked(error, campaign.stage)
            result.update(result="BLOCKED", recovery_category="phase6_preserve_observed_v2_state")
        finally:
            if campaign.deploy_lock: campaign.deploy_lock.close()
        base.write_record(root / "result.json", result)
    print(json.dumps(result))
    if result["result"] != "PASS": raise SystemExit(1)


if __name__ == "__main__": main()
