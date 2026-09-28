from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import sqlite3
import unittest
from unittest.mock import Mock, patch
from workflow.automation.store import AutomationStore
from _phase4_fixtures import make_v1

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "ops/phase4/production_campaign.py"
spec = importlib.util.spec_from_file_location("phase4_campaign", SCRIPT)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)
drill_spec = importlib.util.spec_from_file_location("phase4_isolated", REPO / "ops/phase4/isolated_drill.py")
drill = importlib.util.module_from_spec(drill_spec)
drill_spec.loader.exec_module(drill)


class Phase4OperationsTests(unittest.TestCase):
    def test_failed_cli_result_is_preserved_in_private_operation_record(self):
        with tempfile.TemporaryDirectory() as root:
            driver = object.__new__(campaign.Campaign)
            driver.root = Path(root)
            with self.assertRaisesRegex(RuntimeError, "fixed_operation_failed"):
                driver.run([sys.executable, "-c", "print('fixture_failure_category'); raise SystemExit(1)"])
            self.assertIn("fixture_failure_category", (driver.root / "operations.log").read_text())

    def test_live_smoke_policy_rejects_wildcard_and_external_routes(self):
        with tempfile.TemporaryDirectory() as root:
            store = AutomationStore(Path(root) / "policy.db")
            safe = {"id": "platform.smoke-test", "name": "Safe smoke",
                "trigger": {"event_types": ["system.automation.smoke_test"], "sources": ["internal"]},
                "steps": [{"id": "set", "action": "core.set"}, {"id": "emit", "action": "event.emit",
                    "with": {"event_type": "system.automation.smoke_test.completed", "source": "automation-engine"}}]}
            store.upsert_workflow(drill.WorkflowDefinition.model_validate(safe))
            with store._connect() as conn:
                self.assertTrue(drill.smoke_policy(conn)["safe"])
            store.upsert_workflow(drill.WorkflowDefinition.model_validate({"id": "unsafe", "name": "External route",
                "trigger": {"event_types": ["*"]}, "steps": [{"id": "external", "action": "fixture.external"}]}))
            with store._connect() as conn:
                self.assertFalse(drill.smoke_policy(conn)["safe"])

    def test_restored_unresolved_execution_never_launches_an_api(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.db"
            make_v1(source)
            with sqlite3.connect(source) as conn:
                conn.execute("INSERT INTO automation_workflows VALUES('fixture','Fixture',1,1,'{}',NULL,'2026-09-28T00:00:00Z')")
                conn.execute("INSERT INTO automation_events VALUES('fixture','fixture','fixture','2026-09-28T00:00:00Z',"
                             "'fixture',NULL,NULL,0,'{}','2026-09-28T00:00:00Z')")
                conn.execute("INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) "
                             "VALUES('fixture','fixture','fixture','fixture','queued','2026-09-28T00:00:00Z')")
            before = drill.inventory(source)
            with patch.object(drill, "api_drill") as launched, self.assertRaisesRegex(RuntimeError, "restored_unresolved_work"):
                drill.run(source, Path(root) / "drill")
            launched.assert_not_called()
            self.assertEqual(drill.inventory(source), before)

    def test_isolated_smoke_disables_restored_workflows_and_limits_scope(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            database = workspace / "candidate-v2.db"
            store = AutomationStore(database)
            with store._connect() as conn:
                conn.execute("INSERT INTO automation_workflows VALUES('external','External',1,1,'{}',NULL,'2026-09-28T00:00:00Z')")
            definitions = drill.prepare_smoke(workspace, database)
            self.assertEqual([p.name for p in definitions.iterdir()], ["platform-smoke-test.yaml"])
            with store._connect() as conn:
                self.assertEqual(conn.execute("SELECT enabled FROM automation_workflows").fetchone()[0], 0)
            with self.assertRaisesRegex(RuntimeError, "isolated_smoke_database_scope"):
                drill.prepare_smoke(workspace, workspace / "source.db")

    def test_restore_driver_uses_existing_positional_verifier_interface(self):
        driver = object.__new__(campaign.Campaign)
        driver.run = Mock(return_value=json.dumps({"result": "PASS", "source_sha256": "a" * 64}))
        result = driver.restore_archive(Path("/fixture/archive.tar.gz"), "a" * 64)
        self.assertEqual(result["result"], "PASS")
        driver.run.assert_called_once_with(["/usr/bin/python3", "-I",
            str(campaign.REPO / "ops/backup/optibrain-restore-drill.py"), "/fixture/archive.tar.gz", "a" * 64])
        driver.run.return_value = json.dumps({"result": "PASS", "source_sha256": "b" * 64})
        with self.assertRaises(RuntimeError):
            driver.restore_archive(Path("/fixture/archive.tar.gz"), "a" * 64)

    def test_environment_parser_preserves_literals_without_shell_execution(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "should-not-exist"
            value = campaign.parse_env('SITE_WORKFLOW_API_KEY="fixture key"\nOTHER="$(touch ' + str(target) + ')"\n')
            self.assertEqual(value["SITE_WORKFLOW_API_KEY"], "fixture key")
            self.assertFalse(target.exists())

    def test_environment_parser_refuses_duplicate_and_unsupported_values(self):
        for text in ("KEY=a\nKEY=b", "invalid-key=value", "KEY=a extra", "missing_assignment"):
            with self.subTest(text=text), self.assertRaises(RuntimeError): campaign.parse_env(text)

    def test_production_plan_requires_exact_commit_without_privileged_operations(self):
        response = subprocess.run(["/usr/bin/python3", "-I", str(SCRIPT), "--candidate", campaign.BASELINE, "--plan"],
                                  capture_output=True, text=True, check=True)
        plan = json.loads(response.stdout)
        self.assertEqual(plan["baseline"], "10e2d1feac9e724ee7d78ba3333a6242fde82898")
        self.assertIn("migration drill on restored production DB", plan["operations"])
        self.assertIn("encrypted offhost download verification", plan["operations"])

    def test_production_script_refuses_missing_root_authentication(self):
        response = subprocess.run(["/usr/bin/python3", "-I", str(SCRIPT), "--candidate", campaign.BASELINE],
                                  capture_output=True, text=True)
        self.assertNotEqual(response.returncode, 0)
        self.assertIn("human_root_authentication_required", response.stderr)

    def test_migration_cli_inspect_snapshot_and_verified_migration(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / "source.db", Path(root) / "snapshot.db"
            make_v1(source)
            command = [sys.executable, str(REPO / "ops/phase4/migrate_db.py"), "--db", str(source)]
            inspected = json.loads(subprocess.check_output([*command, "--inspect"]))
            self.assertEqual(inspected["version"], 1)
            self.assertIsNone(inspected["watchdog_sample_at"])
            self.assertEqual(inspected["run_status_counts"], {})
            json.loads(subprocess.check_output([*command, "--snapshot-to", str(destination)]))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            migrated = json.loads(subprocess.check_output([sys.executable, str(REPO / "ops/phase4/migrate_db.py"), "--db", str(destination)]))
            self.assertEqual(migrated["result"], "PASS")
            self.assertEqual(migrated["new_version"], 2)
            self.assertEqual(json.loads(subprocess.check_output([*command, "--inspect"]))["version"], 1)
