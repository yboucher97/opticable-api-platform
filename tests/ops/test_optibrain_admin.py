import importlib.util
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import types
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).parents[2] / "ops/admin/optibrain-admin.py"
spec = importlib.util.spec_from_file_location("optibrain_admin", PATH)
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class RequestValidationTests(unittest.TestCase):
    def test_fixed_operations(self):
        self.assertEqual(admin.parse_request(["backup"]), ("backup",))
        self.assertEqual(admin.parse_request(["service-status", "opticable-workflow-api.service"]),
                         ("service-status", "opticable-workflow-api.service"))

    def test_rejects_shell_and_arbitrary_paths(self):
        for args in (["sh"], ["bash", "-c", "id"], ["run", "/etc/shadow"],
                     ["service-restart", "ssh.service"],
                     ["service-status", "opticable-workflow-api.service;id"],
                     ["timer-status", "arbitrary.timer"], ["backup", "--output-dir", "/tmp"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                admin.parse_request(args)

    def test_root_runbook_sync_has_no_path_or_argument_override(self):
        self.assertEqual(admin.parse_request(["sync-master-runbook"]), ("sync-master-runbook",))
        for args in (["sync-master-runbook", "/etc/passwd"],
                     ["sync-master-runbook;id"], ["sync-master-runbook", "--destination=/etc/shadow"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                admin.parse_request(args)

    def test_only_fixed_privileged_operations_and_bounded_arguments_are_accepted(self):
        self.assertEqual(admin.parse_request(["logs", "opticable-workflow-api.service", "200"]),
                         ("logs", "opticable-workflow-api.service", "200"))
        self.assertEqual(admin.parse_request(["service-reload", "opticable-password-pdf.service"]),
                         ("service-reload", "opticable-password-pdf.service"))
        for args in (
            ["logs", "opticable-workflow-api.service", "201"],
            ["logs", "opticable-workflow-api.service", "1;id"],
            ["logs", "../../etc/shadow"],
            ["service-restart", "ssh.service"],
            ["service-reload", "opticable-workflow-api.service;id"],
            ["restore-verify-latest", "/etc/shadow"],
            ["backup", "--retention", "0"],
            ["upload", "--public"],
            ["queue-status", "--database", "/etc/shadow"],
            ["sync-master-runbook", "../../etc/sudoers"],
            ["--", "python", "-c", "id"],
            ["age", "--identity", "/offline/identity"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                admin.parse_request(args)

    def test_internal_command_policy_rejects_escape_and_only_allows_fixed_targets(self):
        admin._validate_command(["/usr/bin/systemctl", "restart", "opticable-workflow-api.service"])
        admin._validate_command(["/usr/bin/systemctl", "start", "--wait", admin.UPLOAD_SERVICE])
        attacks = (
            ["/bin/sh", "-c", "id"],
            ["/usr/bin/systemctl", "disable", "optibrain-backup.timer"],
            ["/usr/bin/systemctl", "restart", "ssh.service"],
            ["/usr/bin/systemctl", "set-environment", "PATH=/tmp"],
            ["/usr/bin/install", "-m", "0644", "/tmp/x", "/etc/sudoers"],
            ["/usr/bin/python3", "-c", "import os; os.system('id')"],
            ["/usr/bin/python3", "/etc/shadow", "0" * 64],
            [admin.BACKUP_SCRIPT, "--output-dir", "/tmp"],
            ["/usr/bin/systemctl", "set-property", admin.UPLOAD_SERVICE, "PublicAccess=true"],
            ["/usr/bin/age", "--decrypt", "--identity", "/offline/identity"],
            ["/usr/bin/journalctl", "--no-pager", "--unit", "ssh.service", "--lines", "10"],
        )
        for argv in attacks:
            with self.subTest(argv=argv), self.assertRaises(RuntimeError):
                admin._validate_command(argv)

    def test_environment_is_replaced_with_minimal_fixed_environment(self):
        original = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update({"SUDO_USER": "optibrain;id", "PYTHONPATH": "/tmp/evil",
                               "LD_PRELOAD": "/tmp/evil.so", "HTTP_PROXY": "http://attacker",
                               "AGE_IDENTITY": "/tmp/identity", "PATH": "/tmp"})
            admin.sanitize_environment()
            self.assertEqual(dict(os.environ), {"PATH": admin.SAFE_PATH,
                                               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
            self.assertEqual(admin._ACTOR, "optibrain_id")
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_installed_python_isolation_ignores_environment_injection(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = pathlib.Path(temporary) / "optibrain-admin"
            shutil.copyfile(PATH, executable)
            executable.chmod(0o750)
            env = {"PATH": "/tmp", "PYTHONPATH": "/tmp/evil", "PYTHONHOME": "/tmp/evil",
                   "LD_PRELOAD": "/tmp/evil.so", "HTTP_PROXY": "http://attacker", "SUDO_USER": "test"}
            result = subprocess.run([str(executable), "--self-test"], capture_output=True,
                                    text=True, env=env, timeout=5, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OPTIBRAIN_ADMIN_SELF_TEST_OK 1")

    def test_bounded_log_redaction_hides_secret_values(self):
        source = b'Authorization: Bearer abc.def; password=hunter2 api_key=secret123 AWS_SECRET_ACCESS_KEY=aws987 "refresh_token": "refresh value"\nordinary status\n'
        result = admin._redact(source)
        for secret in ("abc.def", "hunter2", "secret123", "aws987", "refresh value"):
            self.assertNotIn(secret, result)
        self.assertIn("ordinary status", result)
        self.assertLessEqual(len(result.encode()), 65536)

    def test_log_subprocess_has_fixed_env_and_hard_output_cap(self):
        def fake_run(argv, **kwargs):
            self.assertEqual(argv[0], "/usr/bin/journalctl")
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["env"], {"PATH": admin.SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
            kwargs["stdout"].write(b"token=not-for-output\n" + b"x" * 70000)
            return type("Result", (), {"returncode": -admin.signal.SIGXFSZ})()
        command = ["/usr/bin/journalctl", "--no-pager", "--output=short-iso", "--unit",
                   "opticable-workflow-api.service", "--lines", "200", "--quiet"]
        with mock.patch.object(admin.subprocess, "run", side_effect=fake_run):
            output = admin.run(command, quiet=True)
        self.assertNotIn("not-for-output", output)
        self.assertIn("truncated at 65536 bytes", output)
        self.assertLessEqual(len(output.encode()), 65600)

    def test_backup_retention_gate_fails_closed(self):
        self.assertEqual(admin._retention_limit("# config\nOPTIBRAIN_BACKUP_RETENTION=7\n"), 7)
        self.assertEqual(admin._retention_limit("# default policy\n"), 7)
        for config in ("OPTIBRAIN_BACKUP_RETENTION=0\n", "OPTIBRAIN_BACKUP_RETENTION=$(id)\n",
                       "OPTIBRAIN_BACKUP_RETENTION=5\nOPTIBRAIN_BACKUP_RETENTION=7\n"):
            with self.subTest(config=config), self.assertRaises(RuntimeError):
                admin._retention_limit(config)

    def test_manual_backup_uses_fixed_root_owned_nonblocking_lock(self):
        fake_stat = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0,
                                          st_gid=0, st_nlink=1)
        fake_parent = types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
        with mock.patch.object(admin.os, "lstat", return_value=fake_parent), \
             mock.patch.object(admin.os, "open", return_value=123), \
             mock.patch.object(admin.os, "fstat", return_value=fake_stat), \
             mock.patch.object(admin.os, "close") as close, \
             mock.patch.object(admin.fcntl, "flock") as flock, \
             mock.patch.object(admin, "_require_backup_headroom") as headroom, \
             mock.patch.object(admin, "run") as run:
            admin._run_manual_backup()
        self.assertEqual(admin.BACKUP_LOCK, "/run/lock/optibrain-admin-backup.lock")
        self.assertEqual(flock.call_args.args, (123, admin.fcntl.LOCK_EX | admin.fcntl.LOCK_NB))
        headroom.assert_called_once_with()
        run.assert_called_once_with([admin.BACKUP_SCRIPT], timeout=3600, quiet=True)
        close.assert_called_once_with(123)

    def test_runbook_fixed_reader_rejects_symlinks_and_wrong_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "candidate.md"
            source.write_text("# Opticable Automation Master Runbook\n")
            source.chmod(0o440)
            admin._read_pinned_file(str(source), uid=os.getuid(), gid=os.getgid(), mode=0o440, limit=1024)
            link = root / "candidate-link.md"
            link.symlink_to(source)
            with self.assertRaises(RuntimeError):
                admin._read_pinned_file(str(link), uid=os.getuid(), gid=os.getgid(), mode=0o440, limit=1024)
            with self.assertRaises(RuntimeError):
                admin._read_pinned_file(str(source), uid=os.getuid() + 1, gid=os.getgid(), mode=0o440, limit=1024)


if __name__ == "__main__":
    unittest.main()
