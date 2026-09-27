from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ADMIN_SOURCE = Path(__file__).parents[2] / "ops/admin/optibrain-admin.py"
SPEC = importlib.util.spec_from_file_location("optibrain_admin_restore", ADMIN_SOURCE)
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)

DRILL_SOURCE = Path(__file__).parents[2] / "ops/backup/optibrain-restore-drill.py"
GIT_SHA = "0123456789abcdef0123456789abcdef01234567"
TIMESTAMP = "20260927T130636Z"


def make_phase1_fixture(directory: Path) -> Path:
    """Create a representative, self-consistent Phase 1 archive fixture."""
    generation = directory / f"generation-{TIMESTAMP}"
    generation.mkdir()

    database = generation / "database/automation.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE fixture (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO fixture(value) VALUES ('recovery fixture')")

    critical_paths = (
        "system/etc/opticable-workflow-api.env",
        "system/etc/optibrain/github-app.pem",
        "system/etc/systemd/system/opticable-workflow-api.service",
    )
    for relative in critical_paths:
        path = generation / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("representative recovery fixture\n", encoding="utf-8")

    release = directory / f"opticable-api-platform-{GIT_SHA}"
    app = release / "apps/workflow-api/workflow/api.py"
    app.parent.mkdir(parents=True)
    app.write_text("API_VERSION = 'fixture'\n", encoding="utf-8")
    source_bundle = generation / f"source/opticable-api-platform-{GIT_SHA}.tar.gz"
    source_bundle.parent.mkdir(parents=True)
    with tarfile.open(source_bundle, "w:gz") as bundle:
        bundle.add(release, arcname=release.name)

    files = []
    for path in sorted(item for item in generation.rglob("*") if item.is_file()):
        content = path.read_bytes()
        files.append({
            "path": path.relative_to(generation).as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    source_metadata = []
    for relative in critical_paths:
        source_metadata.append({
            "backup_path": relative,
            "mode": "0600",
            "uid": os.getuid(),
            "gid": os.getgid(),
            "type": "file",
        })
    manifest = {
        "backup_format_version": "1",
        "backup_script_version": "1.0.1",
        "timestamp": TIMESTAMP,
        "production_git_sha": GIT_SHA,
        "files": files,
        "sqlite_databases": [{"backup_path": "database/automation.db"}],
        "source_metadata": source_metadata,
    }
    (generation / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    archive = directory / f"optibrain-backup-{TIMESTAMP}.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(generation, arcname=generation.name)
    archive.chmod(0o600)
    sidecar = subprocess.run(
        ["/usr/bin/sha256sum", str(archive)], check=True, capture_output=True
    ).stdout
    sidecar_path = Path(str(archive) + ".sha256")
    sidecar_path.write_bytes(sidecar)
    sidecar_path.chmod(0o600)
    return archive


class BackupSidecarTests(unittest.TestCase):
    def test_standard_absolute_sha256sum_record_is_bound_to_selected_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup_dir = Path(temporary)
            archive = backup_dir / f"optibrain-backup-{TIMESTAMP}.tar.gz"
            digest = b"a" * 64
            record = digest + b"  " + str(archive).encode("ascii") + b"\n"
            with mock.patch.object(admin, "BACKUP_DIR", str(backup_dir)):
                self.assertEqual(admin._parse_backup_sidecar(record, str(archive)), digest.decode())

                rejected = (
                    digest + b"  " + str(archive.with_name(
                        "optibrain-backup-20260927T130637Z.tar.gz")).encode() + b"\n",
                    digest + b"  " + str(backup_dir / "../outside.tar.gz").encode() + b"\n",
                    digest + b"  relative/archive.tar.gz\n",
                    digest + b"  ../../etc/shadow\n",
                    record + b"extra line\n",
                    record + record,
                    b"g" * 64 + b"  " + str(archive).encode() + b"\n",
                    digest.upper() + b"  " + str(archive).encode() + b"\n",
                    digest + b" " + str(archive).encode() + b"\n",
                    digest + b"   " + str(archive).encode() + b"\n",
                    digest + b"  " + archive.name.encode() + b"\n",  # basename-only legacy form
                    digest + b"  " + str(archive).encode(),  # missing final newline
                )
                for value in rejected:
                    with self.subTest(value=value), self.assertRaises(RuntimeError):
                        admin._parse_backup_sidecar(value, str(archive))

    def test_verify_latest_command_policy_still_accepts_only_fixed_archive_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = f"{temporary}/optibrain-backup-{TIMESTAMP}.tar.gz"
            with mock.patch.object(admin, "BACKUP_DIR", temporary):
                admin._validate_command(["/usr/bin/sha256sum", "-c", archive + ".sha256"])
                for bad in (
                    f"{temporary}/../other/optibrain-backup-{TIMESTAMP}.tar.gz.sha256",
                    f"/var/tmp/optibrain-backup-{TIMESTAMP}.tar.gz.sha256",
                ):
                    with self.subTest(path=bad), self.assertRaises(RuntimeError):
                        admin._validate_command(["/usr/bin/sha256sum", "-c", bad])

    def test_verify_latest_still_dispatches_checksum_and_archive_verification(self):
        archive = f"{admin.BACKUP_DIR}/optibrain-backup-{TIMESTAMP}.tar.gz"
        with mock.patch.object(admin, "_latest_archive", return_value=archive), \
             mock.patch.object(admin, "_validate_fixed_root_file"), \
             mock.patch.object(admin, "run") as run, \
             mock.patch.object(admin.sys, "stdout", io.StringIO()):
            admin.execute(("verify-latest",))
        self.assertEqual(run.call_args_list, [
            mock.call(["/usr/bin/sha256sum", "-c", archive + ".sha256"], quiet=True),
            mock.call([admin.BACKUP_SCRIPT, "--verify", archive], timeout=3600, quiet=True),
        ])

    def test_latest_archive_rejects_archive_or_sidecar_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup_dir = Path(temporary)
            backup_dir.chmod(0o700)
            real_archive = backup_dir / f"optibrain-backup-{TIMESTAMP}.tar.gz"
            real_archive.write_bytes(b"archive")
            real_archive.chmod(0o600)
            real_sidecar = Path(str(real_archive) + ".sha256")
            real_sidecar.write_bytes(b"sidecar")
            real_sidecar.chmod(0o600)
            linked_archive = backup_dir / "optibrain-backup-20260927T130637Z.tar.gz"
            linked_archive.symlink_to(real_archive)
            with mock.patch.object(admin, "BACKUP_DIR", temporary):
                with self.assertRaises(RuntimeError):
                    admin._latest_archive()
            linked_archive.unlink()
            real_sidecar.unlink()
            Path(str(real_sidecar)).symlink_to(backup_dir / "missing-sidecar")
            with mock.patch.object(admin, "BACKUP_DIR", temporary):
                with self.assertRaises(RuntimeError):
                    admin._latest_archive()

    def _execute_restore(self, backup_dir: Path, archive: Path, runner: Path) -> str:
        capture = io.BytesIO()
        stream = io.TextIOWrapper(capture, encoding="utf-8")
        with mock.patch.object(admin, "BACKUP_DIR", str(backup_dir)), \
             mock.patch.object(admin, "RESTORE_DRILL", str(runner)), \
             mock.patch.object(admin, "_validate_fixed_root_file"), \
             mock.patch.object(admin.sys, "stdout", stream):
            selected = admin._latest_archive()
            self.assertEqual(selected, str(archive))
            admin.execute(("restore-verify-latest",))
            stream.flush()
        return capture.getvalue().decode("utf-8")

    def _make_runner(self, directory: Path) -> Path:
        runner = directory / "isolated-restore-runner.py"
        runner.write_text(
            "import importlib.util, json, pathlib, sys\n"
            f"spec = importlib.util.spec_from_file_location('restore_drill', {str(DRILL_SOURCE)!r})\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "workspace = pathlib.Path(sys.argv[0]).parent / 'drill-workspace'\n"
            "workspace.mkdir(mode=0o700, exist_ok=True)\n"
            "result = module.validate(pathlib.Path(sys.argv[1]), sys.argv[2], workspace)\n"
            "print(json.dumps(result, sort_keys=True))\n",
            encoding="utf-8",
        )
        runner.chmod(0o750)
        return runner

    def test_restore_verify_reaches_real_isolated_verifier_with_phase1_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup_dir = Path(temporary)
            backup_dir.chmod(0o700)
            archive = make_phase1_fixture(backup_dir)
            runner = self._make_runner(backup_dir)
            output = self._execute_restore(backup_dir, archive, runner)
            result = json.loads(output)
            self.assertEqual(result["result"], "PASS")
            self.assertEqual(result["source_sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(result["databases_restored"], 1)
            self.assertEqual(result["critical_configs_restored"], 3)

    def test_wrong_digest_and_archive_substitution_fail_in_real_verifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            backup_dir = Path(temporary)
            backup_dir.chmod(0o700)
            archive = make_phase1_fixture(backup_dir)
            runner = self._make_runner(backup_dir)
            sidecar = Path(str(archive) + ".sha256")
            original_sidecar = sidecar.read_bytes()
            wrong_digest = b"0" * 64
            self.assertNotEqual(wrong_digest.decode(), hashlib.sha256(archive.read_bytes()).hexdigest())
            sidecar.write_bytes(wrong_digest + b"  " + str(archive).encode() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "operation failed"):
                self._execute_restore(backup_dir, archive, runner)

            sidecar.write_bytes(original_sidecar)
            replacement = backup_dir / "replacement.tar.gz"
            replacement.write_bytes(b"substituted archive content")
            replacement.chmod(0o600)
            original_run = admin.run

            def substitute_then_run(argv, timeout=900, quiet=False):
                os.replace(replacement, archive)
                return original_run(argv, timeout=timeout, quiet=quiet)

            capture = io.BytesIO()
            stream = io.TextIOWrapper(capture, encoding="utf-8")
            with mock.patch.object(admin, "BACKUP_DIR", str(backup_dir)), \
                 mock.patch.object(admin, "RESTORE_DRILL", str(runner)), \
                 mock.patch.object(admin, "_validate_fixed_root_file"), \
                 mock.patch.object(admin, "run", side_effect=substitute_then_run), \
                 mock.patch.object(admin.sys, "stdout", stream):
                with self.assertRaisesRegex(RuntimeError, "operation failed"):
                    admin.execute(("restore-verify-latest",))


if __name__ == "__main__":
    unittest.main()
