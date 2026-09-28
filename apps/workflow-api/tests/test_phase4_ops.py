from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from _phase4_fixtures import make_v1

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "ops/phase4/production_campaign.py"
spec = importlib.util.spec_from_file_location("phase4_campaign", SCRIPT)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class Phase4OperationsTests(unittest.TestCase):
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
