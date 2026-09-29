"""Fail-closed release boundaries. All operations are disposable fixtures/fakes."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("phase6_gate_g_tests", ROOT / "ops/phase6/production_campaign.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
inspect_spec = importlib.util.spec_from_file_location("phase6_inventory_tests", ROOT / "ops/phase6/inspect_workflows.py")
inspector = importlib.util.module_from_spec(inspect_spec)
inspect_spec.loader.exec_module(inspector)
CANDIDATE = "b" * 40


class GateGCampaignTests(unittest.TestCase):
    def envelope(self):
        now = datetime.now(timezone.utc)
        return {"candidate": CANDIDATE, "validated_sha": CANDIDATE, "baseline": campaign.BASELINE,
                "branch": campaign.BRANCH, "approved_by": "human:fixture", "approved_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(), "campaign_sha256": "a" * 64,
                "ci_run_id": 1, "full_tests": 580, "subtests": 540, "focused_tests": 156,
                "failures": 0, "errors": 0, "skipped": 0, "release_id": "20260928-fixture"}

    def test_exact_human_authorization_accepts(self):
        self.assertEqual(campaign.validate_authorization(self.envelope(), CANDIDATE)["candidate"], CANDIDATE)

    def test_changed_identity_actor_counts_and_extra_authority_refuse(self):
        changes = {"candidate": "c" * 40, "validated_sha": "c" * 40, "baseline": "c" * 40,
                   "branch": "main", "approved_by": "automation:fixture", "full_tests": 579,
                   "focused_tests": 155, "subtests": 539, "failures": 1, "errors": 1, "skipped": 1,
                   "release_id": "../escape", "campaign_sha256": "bad"}
        for name, value in changes.items():
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                envelope = self.envelope(); envelope[name] = value
                campaign.validate_authorization(envelope, CANDIDATE)
        envelope = self.envelope(); envelope["allow_sends"] = True
        with self.assertRaises(RuntimeError): campaign.validate_authorization(envelope, CANDIDATE)

    def test_lifetime_timezone_expiry_and_future_approval_refuse(self):
        now = datetime.now(timezone.utc)
        for approved, expires in ((now.replace(tzinfo=None), now + timedelta(hours=1)),
                                  (now, (now + timedelta(hours=1)).replace(tzinfo=None)),
                                  (now - timedelta(hours=2), now - timedelta(hours=1)),
                                  (now, now + timedelta(hours=3)),
                                  (now + timedelta(minutes=1), now + timedelta(hours=1))):
            with self.subTest(approved=str(approved), expires=str(expires)), self.assertRaises(RuntimeError):
                envelope = self.envelope(); envelope.update(approved_at=approved.isoformat(), expires_at=expires.isoformat())
                campaign.validate_authorization(envelope, CANDIDATE, now)

    def test_every_failed_gate_prevents_all_later_operations(self):
        for failure in campaign.STAGES:
            with self.subTest(failure=failure):
                operations = []
                def perform(stage):
                    operations.append(stage)
                    if stage == failure: raise RuntimeError("fixture_gate_failed")
                backend = Mock(stage_start=Mock(), perform=Mock(side_effect=perform), mark=Mock())
                # A real backend carries authorization; this fixture intentionally does not.
                del backend.authorization
                with self.assertRaisesRegex(RuntimeError, "fixture_gate_failed"):
                    campaign.execute_stages(backend)
                self.assertEqual(operations, list(campaign.STAGES[:campaign.STAGES.index(failure) + 1]))
                if failure in campaign.STAGES[:campaign.STAGES.index("guarded-main-promotion")]:
                    self.assertNotIn("guarded-main-promotion", operations)
                self.assertFalse(any("rollback" in call.args[0] for call in backend.perform.call_args_list if "proof" not in call.args[0]))

    def test_success_requires_recovery_and_rollback_before_promotion(self):
        backend = Mock(); del backend.authorization
        gates = campaign.execute_stages(backend)
        self.assertLess(gates.index("candidate-offhost"), gates.index("guarded-main-promotion"))
        self.assertLess(gates.index("rollback-proof"), gates.index("guarded-main-promotion"))
        self.assertLess(gates.index("ci-deploy-reconciliation"), gates.index("post-release-reference"))

    def test_expired_authorization_stops_before_any_gate(self):
        backend = Mock(); backend.authorization = self.envelope(); backend.candidate = CANDIDATE
        backend.authorization["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.assertRaises(RuntimeError): campaign.execute_stages(backend)
        backend.stage_start.assert_not_called(); backend.perform.assert_not_called()

    def test_default_cli_is_read_only_plan(self):
        process = subprocess.run(["python3", "-I", str(ROOT / "ops/phase6/production_campaign.py"),
                                  "--candidate", CANDIDATE], capture_output=True, text=True, check=True)
        result = json.loads(process.stdout)
        self.assertEqual(result["mode"], "plan_only")
        self.assertFalse(result["migration"]); self.assertFalse(result["automatic_rollback"])

    def test_execute_without_human_root_refuses_before_workspace(self):
        with patch.object(campaign.os, "geteuid", return_value=1000), patch.object(campaign, "read_authorization") as read:
            with patch("sys.argv", ["campaign", "--candidate", CANDIDATE, "--execute"]), self.assertRaisesRegex(RuntimeError, "human_root"):
                campaign.main()
        read.assert_not_called()

    def test_api_send_conversion_and_other_mutations_refuse(self):
        driver = campaign.Phase6Campaign.__new__(campaign.Phase6Campaign)
        for path, body in (("/v1/lifecycle/leads", {}), ("/v1/automation/events", {"event_type": "send", "source": "internal"}),
                           ("/v1/automation/events", {"event_type": "system.automation.smoke_test", "source": "external"})):
            with self.subTest(path=path), patch.object(campaign.legacy.Phase5Campaign, "api", create=True) as provider:
                with self.assertRaisesRegex(RuntimeError, "unsafe_campaign_api_mutation"): driver.api(path, body)
                provider.assert_not_called()

    def test_migration_and_subscription_modes_never_reach_process(self):
        driver = campaign.Phase6Campaign.__new__(campaign.Phase6Campaign)
        for argv in (["python", "migrate_db.py", "--db", "fixture"], ["python", "provider.py", "--mode", "subscribe"]):
            with self.subTest(argv=argv), patch.object(campaign.legacy.Phase5Campaign, "run") as process:
                with self.assertRaises(RuntimeError): driver.run(argv)
                process.assert_not_called()

    def test_source_ancestry_mismatch_refuses_before_source_or_production_writes(self):
        driver = campaign.Phase6Campaign.__new__(campaign.Phase6Campaign); driver.candidate = CANDIDATE
        def git(repo, *args):
            if args[0] == "rev-parse": return CANDIDATE
            if args[0] == "branch": return campaign.BRANCH
            if args[0] == "status": return ""
            if args[0] == "ls-remote": return CANDIDATE + "\trefs/heads/" + campaign.BRANCH
            if args[0] == "merge-base": return "c" * 40
            raise AssertionError(args)
        driver.git = Mock(side_effect=git); driver.git_bytes = Mock()
        with self.assertRaisesRegex(RuntimeError, "candidate_not_descendant"): driver.source()
        driver.git_bytes.assert_not_called()

    def test_offhost_wrong_generation_never_verifies_or_promotes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive = root / "backup"; archive.write_bytes(b"fixture")
            state = root / "state.json"; state.write_text(json.dumps({"generation": "wrong", "source_sha256": campaign.base.sha(archive), "verification_status": "download_hash_verified"}))
            driver = campaign.Phase6Campaign.__new__(campaign.Phase6Campaign); driver.run = Mock()
            with patch.object(campaign.base, "OFFHOST_STATE", state), patch.object(campaign.base, "protected_file"):
                with self.assertRaisesRegex(RuntimeError, "offhost_wrong"): driver.verify_backup_receipt((archive, "expected", {}))
            driver.run.assert_not_called()

    def test_readonly_workflow_hash_detects_content_or_retry_change_without_disclosure(self):
        definition = {"id": "fixture", "name": "fixture", "trigger": {"event_types": ["fixture"]},
                      "steps": [{"id": "step", "action": "core.set", "with": {"text": "private-customer-body"}}]}
        first = inspector.definition_hash(definition)
        definition["steps"][0]["with"]["text"] = "changed-body"
        self.assertNotEqual(first, inspector.definition_hash(definition))
        self.assertNotIn("private", first); self.assertEqual(len(first), 64)

    def test_deploy_wrapper_refuses_unprivileged_and_malformed_requests(self):
        if os.geteuid() != 0:
            process = subprocess.run(["bash", str(ROOT / "deploy/production-root-command.sh"), CANDIDATE], capture_output=True)
            self.assertEqual(process.returncode, 64)
        text = (ROOT / "deploy/production-root-command.sh").read_text()
        self.assertNotIn("deploy/update-production.sh", text)
        self.assertNotIn("git show", text)
        self.assertIn("env -i", text)

    def test_automatic_phase6_deploy_guard_precedes_checkout_switch(self):
        text = (ROOT / "deploy/update-production.sh").read_text()
        self.assertLess(text.index('if [[ "${previous_sha}" == "${TARGET_SHA}" ]]'), text.index('Phase6 target is not already staged'))
        self.assertLess(text.index('Phase6 target is not already staged'), text.index('git -C "${INSTALL_DIR}" reset --hard "${TARGET_SHA}"'))

    def test_root_wrapper_wrong_remote_sha_cannot_materialize_or_execute_script(self):
        spec = importlib.util.spec_from_file_location('trust_fixture',ROOT/'ops/phase6/release_trust.py')
        trust = importlib.util.module_from_spec(spec); spec.loader.exec_module(trust)
        with patch.object(trust, 'protected', return_value={}), patch.object(trust.os,'geteuid',return_value=0), patch.object(trust,'run') as process:
            with self.assertRaises(RuntimeError): trust.reconcile('c'*40)
        process.assert_not_called()
        self.assertNotIn('deploy/update-production.sh', (ROOT/'deploy/production-root-command.sh').read_text())

    def test_inventory_reads_only_and_never_discloses_workflow_inputs(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "fixture.db"
            document = {"id": "fixture", "name": "fixture", "enabled": True,
                        "trigger": {"event_types": ["fixture"]},
                        "steps": [{"id": "step", "action": "core.set", "with": {"body": "private-body"}}]}
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE automation_workflows(workflow_id TEXT, enabled INTEGER, definition_json TEXT)")
                connection.execute("INSERT INTO automation_workflows VALUES(?,?,?)", ("fixture",1,json.dumps(document)))
            original = database.read_bytes()
            result = inspector.inspect(database)
            self.assertEqual(database.read_bytes(), original)
            self.assertNotIn("private-body", json.dumps(result))
            self.assertEqual(result[0]["actions"], ["core.set"])
            self.assertEqual(result[0]["definition_sha256"], inspector.definition_hash(document))

    def test_remote_candidate_changed_during_fetch_never_stops_service(self):
        driver = campaign.Phase6Campaign.__new__(campaign.Phase6Campaign)
        driver.candidate = CANDIDATE
        driver.source = driver.protections = driver.policies = driver.healthy = Mock()
        driver.run = Mock()
        def git(repo, *args):
            if args[0] == "ls-remote": return campaign.BASELINE + "\trefs/heads/main"
            if args[0] == "rev-parse": return "c" * 40 if args[1] == "FETCH_HEAD" else campaign.BASELINE
            if args[0] == "fetch": return ""
            raise AssertionError(args)
        driver.git = Mock(side_effect=git)
        with patch.object(campaign.base, "write_record") as write:
            with self.assertRaisesRegex(RuntimeError, "candidate_fetch_identity"):
                driver.perform("staged-deployment")
        driver.run.assert_not_called(); write.assert_not_called()

    def test_external_file_policy_blocks_before_reading_process_environment(self):
        driver = campaign.Phase6Campaign.__new__(campaign.Phase6Campaign)
        driver.run = Mock()
        for name in ("OPTIBRAIN_CRM_LEAD_WRITES", "OPTIBRAIN_SALES_DRAFTS", "OPTIBRAIN_OUTBOUND_SENDS"):
            with self.subTest(name=name):
                driver.environment = {name: "phase6-sales-v1"}
                with self.assertRaisesRegex(RuntimeError, "external_policy_enabled"): driver.policies()
        driver.run.assert_not_called()

    def cleanliness_fixture(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); self.clean_repo = root / "repo"; self.clean_repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(self.clean_repo), *args], check=True, capture_output=True)
        self.clean_git = git
        git("init", "-q"); git("config", "user.email", "fixture@example.invalid"); git("config", "user.name", "Fixture")
        (self.clean_repo / "tracked").write_text("original")
        git("add", "."); git("commit", "-qm", "fixture")
        source = (ROOT / "deploy/update-production.sh").read_text()
        function = source[source.index("production_cleanliness() {"):source.index("main() {")]
        self.clean_script = root / "check.sh"
        self.clean_script.write_text('set -Eeuo pipefail\nINSTALL_DIR=$1\nfail() { echo "$*" >&2; exit 1; }\n' + function + 'production_cleanliness\n')
        return root

    def cleanliness_check(self):
        return subprocess.run(["bash", str(self.clean_script), str(self.clean_repo)], capture_output=True, text=True)

    def test_deploy_cleanliness_rejects_tracked_and_staged_changes_without_repair(self):
        self.cleanliness_fixture()
        self.assertEqual(self.cleanliness_check().returncode, 0)
        tracked = self.clean_repo / "tracked"; tracked.write_text("changed")
        self.assertNotEqual(self.cleanliness_check().returncode, 0)
        self.assertEqual(tracked.read_text(), "changed")
        self.clean_git("add", "tracked")
        self.assertNotEqual(self.cleanliness_check().returncode, 0)
        self.assertEqual(tracked.read_text(), "changed")

    def test_deploy_cleanliness_rejects_unexpected_untracked_and_wrong_diagnostic(self):
        self.cleanliness_fixture()
        extra = self.clean_repo / "unexpected"; extra.write_text("fixture")
        self.assertNotEqual(self.cleanliness_check().returncode, 0)
        self.assertEqual(extra.read_text(), "fixture"); extra.unlink()
        diagnostic = self.clean_repo / "ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
        diagnostic.parent.mkdir(parents=True); diagnostic.write_text("wrong")
        result = self.cleanliness_check()
        self.assertNotEqual(result.returncode, 0); self.assertIn("hash mismatch", result.stderr)
        self.assertEqual(diagnostic.read_text(), "wrong")

    def test_deploy_cleanliness_accepts_exact_fixture_exception_only(self):
        import hashlib
        self.cleanliness_fixture()
        diagnostic = self.clean_repo / "ops/backup/optibrain-cloudflare-auth-diagnostic.sh"
        diagnostic.parent.mkdir(parents=True); diagnostic.write_bytes(b"diagnostic-fixture")
        fixture_hash = hashlib.sha256(diagnostic.read_bytes()).hexdigest()
        # Substitute only the expected digest for disposable fixture content.
        self.clean_script.write_text(self.clean_script.read_text().replace(
            "7b2a45b141ea8983e761fdc548e25690fe89bf15ee20b994be2bf4855f701000", fixture_hash))
        original = diagnostic.stat()
        self.assertEqual(self.cleanliness_check().returncode, 0)
        self.assertEqual(diagnostic.stat().st_mtime_ns, original.st_mtime_ns)
        (diagnostic.parent / "extra").write_text("unexpected")
        self.assertNotEqual(self.cleanliness_check().returncode, 0)


    def test_disabled_stored_workflow_tampering_is_not_ignored(self):
        import yaml
        path=ROOT/'apps/workflow-api/config/automation/workflows/customer-lifecycle-qualify-promote.yaml'
        expected=yaml.safe_load(path.read_text())
        driver=campaign.Phase6Campaign.__new__(campaign.Phase6Campaign)
        driver.mark=Mock()
        row={'workflow_id':expected['id'],'enabled':False,'definition_sha256':'f'*64,'actions':['lifecycle.crm_promote_lead']}
        driver.run=Mock(return_value=json.dumps({'workflows':[row]}))
        with self.assertRaisesRegex(RuntimeError,'unreviewed_workflow_definition'):
            driver.audit_routes(candidate=True)
        driver.mark.assert_not_called()
        row['definition_sha256']=inspector.definition_hash(expected)
        driver.run.return_value=json.dumps({'workflows':[row]})
        driver.audit_routes(candidate=True)
        driver.mark.assert_called_once()


if __name__ == "__main__": unittest.main()
