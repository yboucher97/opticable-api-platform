from __future__ import annotations

import hashlib
import importlib.util
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).parents[2] / "ops/admin/optibrain-admin-update.py"
SPEC = importlib.util.spec_from_file_location("optibrain_admin_update", SOURCE)
update = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update
SPEC.loader.exec_module(update)

CANDIDATE = b'''#!/usr/bin/python3 -I
ADMIN_POLICY_ID = "opticable-admin-helper-v1"
HELPER_VERSION = "candidate-2"
def parse_request(args):
    return args == ["--self-test"]
def _validate_command(argv):
    return argv == ["/usr/bin/systemctl", "is-active", "example.service"]
def sanitize_environment():
    return None
def main():
    import sys
    if sys.argv[1:] == ["--self-test"]:
        print("OPTIBRAIN_ADMIN_SELF_TEST_OK " + HELPER_VERSION)
if __name__ == "__main__":
    main()
'''
OLD_HELPER = b'''#!/usr/bin/python3
print("previous working helper")
'''


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        uid, gid = os.getuid(), os.getgid()
        self.incoming = root / "var" / "tmp" / "optibrain-admin-update" / "incoming"
        self.auth_dir = root / "etc" / "optibrain"
        self.bin_dir = root / "usr" / "local" / "sbin"
        self.state_dir = root / "var" / "lib" / "optibrain" / "admin-update"
        self.backup_dir = self.state_dir / "previous"
        for directory, mode in (
            (self.incoming.parent, 0o750), (self.incoming, 0o730),
            (self.auth_dir, 0o700), (self.bin_dir, 0o755),
            (self.state_dir, 0o700), (self.backup_dir, 0o700),
        ):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(mode)
        for directory, _subdirs, _files in os.walk(root):
            pathlib.Path(directory).chmod(0o755)
        root.chmod(0o700)
        for directory, mode in (
            (self.incoming.parent, 0o750), (self.incoming, 0o730),
            (self.auth_dir, 0o700), (self.bin_dir, 0o755),
            (self.state_dir, 0o700), (self.backup_dir, 0o700),
        ):
            directory.chmod(mode)
        self.helper_path = self.bin_dir / "optibrain-admin"
        self.helper_path.write_bytes(OLD_HELPER)
        self.helper_path.chmod(0o750)
        self.candidate_path = self.incoming / "candidate.py"
        self.candidate_path.write_bytes(CANDIDATE)
        self.candidate_path.chmod(0o440)
        self.digest_path = self.incoming / "candidate.sha256"
        self.digest_path.write_text(hashlib.sha256(CANDIDATE).hexdigest() + "\n")
        self.digest_path.chmod(0o440)
        self.pin_path = self.auth_dir / "admin-helper.sha256"
        self.pin_path.write_text(hashlib.sha256(CANDIDATE).hexdigest() + "\n")
        self.pin_path.chmod(0o440)
        self.paths = update.Paths(
            candidate=self.candidate_path,
            candidate_digest=self.digest_path,
            authorized_digest=self.pin_path,
            helper=self.helper_path,
            backup_dir=self.backup_dir,
            audit_dir=self.state_dir,
            audit_file=self.state_dir / "update-audit.jsonl",
            candidate_dir=self.incoming,
        )
        self.identity = update.Identity(uid, gid, uid, gid)
        self.updater = update.AdminHelperUpdater(
            self.paths, self.identity, approved_digest=hashlib.sha256(CANDIDATE).hexdigest())

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_installs_exact_authorized_bytes_and_preserves_backup(self):
        digest = self.updater.update()
        self.assertEqual(digest[0], hashlib.sha256(CANDIDATE).hexdigest())
        self.assertEqual(self.helper_path.read_bytes(), CANDIDATE)
        self.assertEqual(stat.S_IMODE(self.helper_path.stat().st_mode), 0o750)
        backups = list(self.backup_dir.glob("optibrain-admin-*.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), OLD_HELPER)

    def test_real_proposed_helper_passes_static_policy_validation(self):
        helper = pathlib.Path(__file__).parents[2] / "ops/admin/optibrain-admin.py"
        data = helper.read_bytes()
        update.AdminHelperUpdater._validate_helper(data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), update.APPROVED_HELPER_SHA256)

    def test_wrong_digest_is_rejected_without_mutation(self):
        self.pin_path.chmod(0o640)
        self.pin_path.write_text("0" * 64 + "\n")
        self.pin_path.chmod(0o440)
        with self.assertRaisesRegex(update.UpdateError, "root_authorization_mismatch"):
            self.updater.update()
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_new_generated_digest_does_not_expand_updater_release_allowlist(self):
        changed = CANDIDATE.replace(b"candidate-2", b"candidate-3")
        self.candidate_path.chmod(0o640)
        self.candidate_path.write_bytes(changed)
        self.candidate_path.chmod(0o440)
        changed_digest = hashlib.sha256(changed).hexdigest()
        for path in (self.digest_path, self.pin_path):
            path.chmod(0o640)
            path.write_text(changed_digest + "\n")
            path.chmod(0o440)
        with self.assertRaisesRegex(update.UpdateError, "helper_not_in_updater_release_allowlist"):
            self.updater.update()
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)
        self.assertEqual(list(self.backup_dir.iterdir()), [])

    def test_candidate_changed_after_digest_artifact_is_rejected(self):
        self.candidate_path.chmod(0o640)
        self.candidate_path.write_bytes(CANDIDATE + b"# changed\n")
        self.candidate_path.chmod(0o440)
        with self.assertRaisesRegex(update.UpdateError, "candidate_digest_mismatch"):
            self.updater.update()
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)

    def test_candidate_changed_after_authorized_bytes_are_captured_installs_captured_bytes(self):
        class RaceUpdater(update.AdminHelperUpdater):
            def _write_new_root_file(inner_self, destination, data, mode):
                if destination == inner_self.paths.helper:
                    inner_self.paths.candidate.unlink()
                    inner_self.paths.candidate.write_bytes(b"#!/usr/bin/python3\n# substituted\n")
                    inner_self.paths.candidate.chmod(0o440)
                return super()._write_new_root_file(destination, data, mode)

        updater = RaceUpdater(self.paths, self.identity,
                              approved_digest=hashlib.sha256(CANDIDATE).hexdigest())
        self.assertEqual(updater.update()[0], hashlib.sha256(CANDIDATE).hexdigest())
        self.assertEqual(self.helper_path.read_bytes(), CANDIDATE)

    def test_symlink_candidate_is_rejected(self):
        replacement = self.incoming / "replacement"
        replacement.write_bytes(CANDIDATE)
        replacement.chmod(0o440)
        self.candidate_path.unlink()
        self.candidate_path.symlink_to(replacement)
        with self.assertRaisesRegex(update.UpdateError, "unsafe_file"):
            self.updater.update()
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)

    def test_unsafe_candidate_owner_is_rejected(self):
        bad_identity = update.Identity(self.identity.root_uid, self.identity.root_gid,
                                       self.identity.candidate_uid + 1, self.identity.candidate_gid)
        with self.assertRaisesRegex(update.UpdateError, "unsafe_file"):
            update.AdminHelperUpdater(self.paths, bad_identity).update()
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)

    def test_arbitrary_destination_and_argument_injection_are_rejected(self):
        sentinel = pathlib.Path(self.tmp.name) / "unrelated-root-file"
        sentinel.write_text("unchanged")
        for argv in (["--destination", str(sentinel)], [";id"], ["--", "-c", "id"],
                     ["/etc/sudoers"], ["--candidate=/etc/shadow"]):
            with self.subTest(argv=argv), self.assertRaises(update.UpdateError):
                update.parse_cli_args(argv)
        self.assertEqual(sentinel.read_text(), "unchanged")
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)

    def test_audit_contains_only_fixed_nonsecret_fields(self):
        self.updater._audit("failure", "test_failure_code")
        record = self.paths.audit_file.read_text()
        self.assertIn('"operation": "admin_helper_update"', record)
        self.assertIn('"code": "test_failure_code"', record)
        self.assertNotIn(CANDIDATE.decode(), record)
        self.assertEqual(stat.S_IMODE(self.paths.audit_file.stat().st_mode), 0o600)

    def test_malformed_helper_is_rejected(self):
        with self.assertRaisesRegex(update.UpdateError, "malformed_candidate"):
            update.AdminHelperUpdater._validate_helper(b"#!/usr/bin/python3 -I\ndef broken(:\n")

    def test_candidate_policy_rejects_dynamic_shell_execution(self):
        bad = CANDIDATE + b"\nimport os\nos.system('id')\n"
        with self.assertRaisesRegex(update.UpdateError, "candidate_policy_forbidden_os_execution"):
            update.AdminHelperUpdater._validate_helper(bad)

    def test_candidate_policy_rejects_arbitrary_subprocess_interpreter(self):
        bad = CANDIDATE + b"\nimport subprocess\nsubprocess.run(['/bin/sh','-c','id'])\n"
        with self.assertRaisesRegex(update.UpdateError, "candidate_policy_unapproved_subprocess_target"):
            update.AdminHelperUpdater._validate_helper(bad)

    def test_candidate_policy_rejects_unapproved_command_array(self):
        bad = CANDIDATE + b"\ndef execute(op):\n    run(['/bin/sh','-c','id'])\n"
        with self.assertRaisesRegex(update.UpdateError, "candidate_policy_unapproved_command"):
            update.AdminHelperUpdater._validate_helper(bad)

    def test_failed_self_test_restores_and_verifies_previous_helper(self):
        def fail_selftest(_path):
            return b"unexpected output\\n"
        updater = update.AdminHelperUpdater(
            self.paths, self.identity, selftest_runner=fail_selftest,
            approved_digest=hashlib.sha256(CANDIDATE).hexdigest())
        with self.assertRaisesRegex(update.UpdateError, "self_test_result_invalid"):
            updater.update()
        self.assertEqual(self.helper_path.read_bytes(), OLD_HELPER)
        self.assertEqual(hashlib.sha256(self.helper_path.read_bytes()).digest(),
                         hashlib.sha256(OLD_HELPER).digest())
        self.assertEqual(len(list(self.backup_dir.glob("optibrain-admin-*.py"))), 1)


class SudoPolicyTests(unittest.TestCase):
    def test_sudoers_allows_only_fixed_updater_and_validating_helper(self):
        policy = pathlib.Path(__file__).parents[2] / "ops/admin/optibrain-admin-update.sudoers"
        text = policy.read_text()
        active = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(active, ['optibrain ALL=(root:root) NOSETENV: NOPASSWD: /usr/local/sbin/optibrain-admin-update "", /usr/local/sbin/optibrain-admin'])
        for forbidden in ("NOPASSWD: ALL", " NOPASSWD: /bin/sh", "NOPASSWD: /usr/bin/env",
                          "*", "python", "bash", "/etc/", "systemctl"):
            self.assertNotIn(forbidden, text)
        visudo = shutil.which("visudo")
        if visudo:
            result = subprocess.run([visudo, "-cf", str(policy)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
