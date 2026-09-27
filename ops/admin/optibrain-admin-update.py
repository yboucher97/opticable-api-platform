#!/usr/bin/python3 -I
"""Digest-pinned, fixed-path transactional updater for the OptiBrain admin helper."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
import pwd
import re
import resource
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

UPDATER_VERSION = "1"
CANDIDATE_DIR = Path("/var/tmp/optibrain-admin-update/incoming")
CANDIDATE = CANDIDATE_DIR / "candidate.py"
CANDIDATE_DIGEST = CANDIDATE_DIR / "candidate.sha256"
AUTHORIZED_DIGEST = Path("/etc/optibrain/admin-helper.sha256")
HELPER = Path("/usr/local/sbin/optibrain-admin")
BACKUP_DIR = Path("/var/lib/optibrain/admin-update/previous")
AUDIT_DIR = Path("/var/lib/optibrain/admin-update")
AUDIT_FILE = AUDIT_DIR / "update-audit.jsonl"
MAX_CANDIDATE_BYTES = 512 * 1024
CANDIDATE_MODE = 0o440
HELPER_MODE = 0o750
SELF_TEST_TIMEOUT_SECONDS = 8
SELF_TEST_LINE_RE = re.compile(rb"OPTIBRAIN_ADMIN_SELF_TEST_OK [A-Za-z0-9._-]{1,32}\n\Z")
APPROVED_POLICY_ID = b'ADMIN_POLICY_ID = "opticable-admin-helper-v1"'
# Exact helper source approved by this updater build. To change the helper, a
# human must review and install a new updater build with a new literal digest.
APPROVED_HELPER_SHA256 = "30aad73bb2b56a110e38348cce5babefb1816b7f1ffd7cd37449a51a0f1527c4"


class UpdateError(Exception):
    """Safe, non-sensitive update failure category."""


@dataclass(frozen=True)
class Paths:
    candidate: Path = CANDIDATE
    candidate_digest: Path = CANDIDATE_DIGEST
    authorized_digest: Path = AUTHORIZED_DIGEST
    helper: Path = HELPER
    backup_dir: Path = BACKUP_DIR
    audit_dir: Path = AUDIT_DIR
    audit_file: Path = AUDIT_FILE
    candidate_dir: Path = CANDIDATE_DIR


@dataclass(frozen=True)
class Identity:
    root_uid: int = 0
    root_gid: int = 0
    candidate_uid: int = pwd.getpwnam("optibrain").pw_uid
    candidate_gid: int = pwd.getpwnam("optibrain").pw_gid


class AdminHelperUpdater:
    """Updates one fixed helper path; injectable paths exist only for unit tests."""

    def __init__(self, paths: Paths = Paths(), identity: Identity = Identity(),
                 selftest_runner: Callable[[Path], bytes] | None = None,
                 approved_digest: str = APPROVED_HELPER_SHA256) -> None:
        self.paths = paths
        self.identity = identity
        self.selftest_runner = selftest_runner or self._run_selftest
        self.approved_digest = approved_digest

    @staticmethod
    def _lstat(path: Path) -> os.stat_result:
        try:
            return os.lstat(path)
        except OSError as exc:
            raise UpdateError("path_unavailable") from exc

    def _require_directory(self, path: Path, *, uid: int, gid: int, mode: int,
                           writable_bits_allowed: int = 0) -> None:
        st = self._lstat(path)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or st.st_gid != gid:
            raise UpdateError("unsafe_directory")
        actual = stat.S_IMODE(st.st_mode)
        if actual != mode or (actual & 0o022 & ~writable_bits_allowed):
            raise UpdateError("unsafe_directory_mode")

    def _require_safe_parent_chain(self, directory: Path) -> None:
        """Reject symlink or non-root-controlled parents, allowing only sticky /tmp ancestors."""
        trusted_owners = {0}
        if os.geteuid() != 0:  # unit tests run in an isolated user-owned tree
            trusted_owners.add(os.geteuid())
        for path in reversed(directory.parents):
            st = self._lstat(path)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid not in trusted_owners:
                raise UpdateError("unsafe_path_parent")
            mode = stat.S_IMODE(st.st_mode)
            sticky_root_temp = (mode == 0o1777 and bool(st.st_mode & stat.S_ISVTX)
                                and st.st_uid in {0, self.identity.root_uid})
            if mode & 0o022 and not sticky_root_temp:
                raise UpdateError("writable_path_parent")

    def _read_fixed_file(self, path: Path, *, uid: int, gid: int, mode: int,
                         limit: int) -> bytes:
        before = self._lstat(path)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_gid != gid
                or stat.S_IMODE(before.st_mode) != mode or before.st_nlink != 1):
            raise UpdateError("unsafe_file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise UpdateError("unsafe_file_open") from exc
        try:
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino, opened.st_uid, opened.st_gid, opened.st_nlink)
                    != (before.st_dev, before.st_ino, uid, gid, 1)
                    or not stat.S_ISREG(opened.st_mode)
                    or stat.S_IMODE(opened.st_mode) != mode):
                raise UpdateError("file_changed_during_open")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise UpdateError("file_too_large")
            after = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or total != after.st_size):
                raise UpdateError("file_changed_during_read")
            return b"".join(chunks)
        finally:
            os.close(fd)

    @staticmethod
    def _parse_digest(data: bytes) -> str:
        match = re.fullmatch(rb"([0-9a-f]{64})\n?", data)
        if not match:
            raise UpdateError("invalid_digest_artifact")
        return match.group(1).decode("ascii")

    @staticmethod
    def _validate_helper(candidate: bytes) -> None:
        if not candidate or len(candidate) > MAX_CANDIDATE_BYTES or b"\x00" in candidate:
            raise UpdateError("invalid_candidate_size")
        if not candidate.startswith(b"#!/usr/bin/python3 -I\n"):
            raise UpdateError("invalid_candidate_interpreter")
        try:
            source = candidate.decode("utf-8")
            tree = ast.parse(source, filename="optibrain-admin candidate", mode="exec")
        except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
            raise UpdateError("malformed_candidate") from exc
        required_policy_markers = (
            APPROVED_POLICY_ID.decode("ascii"), "def parse_request(args):",
            "def _validate_command(argv):", "def sanitize_environment():", "--self-test",
        )
        if any(marker not in source for marker in required_policy_markers):
            raise UpdateError("candidate_policy_marker_missing")
        class PolicyVisitor(ast.NodeVisitor):
            allowed_modules = {"datetime", "fcntl", "hashlib", "json", "os", "pwd", "re", "resource",
                               "secrets", "signal", "shutil", "sqlite3", "stat", "subprocess",
                               "sys", "tempfile", "urllib"}

            def __init__(self):
                self.function = ""

            def visit_Import(self, node):
                if any(alias.name.split(".", 1)[0] not in self.allowed_modules for alias in node.names):
                    raise UpdateError("candidate_policy_unapproved_import")
                self.generic_visit(node)

            def visit_ImportFrom(self, node):
                if node.module is None or node.module.split(".", 1)[0] not in self.allowed_modules:
                    raise UpdateError("candidate_policy_unapproved_import")
                self.generic_visit(node)

            def visit_FunctionDef(self, node):
                previous, self.function = self.function, node.name
                self.generic_visit(node)
                self.function = previous

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile"}:
                    raise UpdateError("candidate_policy_forbidden_dynamic_execution")
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    base, method = node.func.value.id, node.func.attr
                    if base == "os" and (method in {"system", "popen", "fork", "forkpty", "posix_spawn"}
                                          or method.startswith(("exec", "spawn"))):
                        raise UpdateError("candidate_policy_forbidden_os_execution")
                    if base == "subprocess" and method != "run":
                        raise UpdateError("candidate_policy_unapproved_subprocess_api")
                    if base == "subprocess" and method == "run":
                        if (self.function != "run" or not node.args
                                or not isinstance(node.args[0], ast.Name)
                                or node.args[0].id != "argv"):
                            raise UpdateError("candidate_policy_unapproved_subprocess_target")
                        if any(keyword.arg == "shell" and (not isinstance(keyword.value, ast.Constant)
                                                            or keyword.value.value is not False)
                               for keyword in node.keywords):
                            raise UpdateError("candidate_policy_shell_execution")
                if isinstance(node.func, ast.Name) and node.func.id == "run":
                    if self.function == "_run_manual_backup":
                        command = node.args[0] if node.args else None
                        if (not isinstance(command, ast.List) or len(command.elts) != 1
                                or not isinstance(command.elts[0], ast.Name)
                                or command.elts[0].id != "BACKUP_SCRIPT"):
                            raise UpdateError("candidate_policy_unapproved_command")
                    elif (self.function != "execute" or not node.args
                          or not isinstance(node.args[0], ast.List)):
                        raise UpdateError("candidate_policy_dynamic_command")
                    else:
                        command = node.args[0]
                    if self.function == "execute" and not command.elts:
                        raise UpdateError("candidate_policy_empty_command")
                    executable = command.elts[0]
                    allowed = {"/usr/bin/systemctl", "/usr/bin/df", "/usr/bin/sha256sum",
                               "/usr/bin/journalctl", "/usr/bin/python3"}
                    fixed_backup = (isinstance(executable, ast.Name)
                                    and executable.id == "BACKUP_SCRIPT")
                    fixed_restore = (
                        isinstance(executable, ast.Constant) and executable.value == "/usr/bin/python3"
                        and len(command.elts) > 2 and isinstance(command.elts[1], ast.Constant)
                        and command.elts[1].value == "-I"
                        and isinstance(command.elts[2], ast.Name)
                        and command.elts[2].id == "RESTORE_DRILL"
                    )
                    if (not fixed_backup and
                            (not isinstance(executable, ast.Constant)
                             or executable.value not in allowed)
                            and not fixed_restore):
                        raise UpdateError("candidate_policy_unapproved_command")
                self.generic_visit(node)

        PolicyVisitor().visit(tree)

    def _audit(self, outcome: str, code: str) -> None:
        self._require_safe_parent_chain(self.paths.audit_dir)
        self._require_directory(self.paths.audit_dir, uid=self.identity.root_uid,
                                gid=self.identity.root_gid, mode=0o700)
        record = {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "actor": re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("SUDO_USER", "root"))[:64],
            "operation": "admin_helper_update",
            "outcome": outcome,
            "code": code,
            "updater_version": UPDATER_VERSION,
        }
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.paths.audit_file, flags, 0o600)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != self.identity.root_uid or st.st_gid != self.identity.root_gid or stat.S_IMODE(st.st_mode) != 0o600:
                os.close(fd)
                raise UpdateError("unsafe_audit_file")
            os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
        except OSError as exc:
            raise UpdateError("audit_write_failed") from exc

    def _backup_current(self) -> tuple[bytes, Path]:
        self._require_directory(self.paths.backup_dir, uid=self.identity.root_uid,
                                gid=self.identity.root_gid, mode=0o700)
        current = self._read_fixed_file(self.paths.helper, uid=self.identity.root_uid,
                                        gid=self.identity.root_gid, mode=HELPER_MODE,
                                        limit=MAX_CANDIDATE_BYTES)
        digest = hashlib.sha256(current).hexdigest()
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.paths.backup_dir / f"optibrain-admin-{stamp}-{digest[:16]}.py"
        self._write_new_root_file(backup, current, HELPER_MODE)
        saved = self._read_fixed_file(backup, uid=self.identity.root_uid,
                                      gid=self.identity.root_gid, mode=HELPER_MODE,
                                      limit=MAX_CANDIDATE_BYTES)
        if hashlib.sha256(saved).digest() != hashlib.sha256(current).digest():
            raise UpdateError("backup_verification_failed")
        return current, backup

    def _write_new_root_file(self, destination: Path, data: bytes, mode: int) -> None:
        import tempfile
        fd = -1
        tmp_path: Path | None = None
        try:
            fd, tmp = tempfile.mkstemp(prefix=".optibrain-admin-update-", dir=destination.parent)
            tmp_path = Path(tmp)
            os.fchown(fd, self.identity.root_uid, self.identity.root_gid)
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            if destination == self.paths.helper:
                os.replace(tmp_path, destination)
            else:
                # Backup names are content-addressed and never overwrite prior evidence.
                os.link(tmp_path, destination, follow_symlinks=False)
                os.unlink(tmp_path)
            dir_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            raise UpdateError("atomic_write_failed") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if tmp_path is not None and tmp_path.exists():
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _run_selftest(self, helper_path: Path) -> bytes:
        def child_limits() -> None:
            resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
            resource.setrlimit(resource.RLIMIT_FSIZE, (256, 256))
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        try:
            with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
                result = subprocess.run(
                    [str(helper_path), "--self-test"], stdin=subprocess.DEVNULL,
                    stdout=stdout_file, stderr=stderr_file,
                    timeout=SELF_TEST_TIMEOUT_SECONDS, check=False, shell=False,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, close_fds=True,
                    preexec_fn=child_limits,
                )
                stdout_file.seek(0)
                stdout = stdout_file.read(129)
                stderr_file.seek(0)
                stderr = stderr_file.read(1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError("self_test_execution_failed") from exc
        if result.returncode != 0 or stderr or len(stdout) > 128:
            raise UpdateError("self_test_failed")
        return stdout

    def update(self) -> tuple[str, str]:
        for fixed_dir in (self.paths.candidate_dir, self.paths.candidate_dir.parent,
                          self.paths.authorized_digest.parent, self.paths.helper.parent,
                          self.paths.backup_dir, self.paths.audit_dir):
            self._require_safe_parent_chain(fixed_dir)
        self._require_directory(self.paths.candidate_dir, uid=self.identity.root_uid,
                                gid=self.identity.candidate_gid, mode=0o730,
                                writable_bits_allowed=0o020)
        self._require_directory(self.paths.candidate_dir.parent, uid=self.identity.root_uid,
                                gid=self.identity.root_gid, mode=0o750)
        self._require_directory(self.paths.authorized_digest.parent, uid=self.identity.root_uid,
                                gid=self.identity.root_gid, mode=0o700)
        helper_parent_stat = self._lstat(self.paths.helper.parent)
        if (not stat.S_ISDIR(helper_parent_stat.st_mode)
                or helper_parent_stat.st_uid != self.identity.root_uid
                or helper_parent_stat.st_gid != self.identity.root_gid
                or stat.S_IMODE(helper_parent_stat.st_mode) != 0o755):
            raise UpdateError("unsafe_helper_directory")
        self._require_directory(self.paths.audit_dir, uid=self.identity.root_uid,
                                gid=self.identity.root_gid, mode=0o700)
        self._require_directory(self.paths.backup_dir, uid=self.identity.root_uid,
                                gid=self.identity.root_gid, mode=0o700)
        candidate = self._read_fixed_file(self.paths.candidate, uid=self.identity.candidate_uid,
                                          gid=self.identity.candidate_gid, mode=CANDIDATE_MODE,
                                          limit=MAX_CANDIDATE_BYTES)
        workflow_digest_data = self._read_fixed_file(
            self.paths.candidate_digest, uid=self.identity.candidate_uid,
            gid=self.identity.candidate_gid, mode=CANDIDATE_MODE, limit=256)
        authorized_digest_data = self._read_fixed_file(
            self.paths.authorized_digest, uid=self.identity.root_uid,
            gid=self.identity.root_gid, mode=0o440, limit=256)
        digest = hashlib.sha256(candidate).hexdigest()
        if digest != self._parse_digest(workflow_digest_data):
            raise UpdateError("candidate_digest_mismatch")
        if digest != self._parse_digest(authorized_digest_data):
            raise UpdateError("root_authorization_mismatch")
        if digest != self.approved_digest:
            raise UpdateError("helper_not_in_updater_release_allowlist")
        self._validate_helper(candidate)
        current, backup = self._backup_current()
        previous_digest = hashlib.sha256(current).digest()
        try:
            self._write_new_root_file(self.paths.helper, candidate, HELPER_MODE)
            installed = self._read_fixed_file(self.paths.helper, uid=self.identity.root_uid,
                                              gid=self.identity.root_gid, mode=HELPER_MODE,
                                              limit=MAX_CANDIDATE_BYTES)
            if hashlib.sha256(installed).digest() != hashlib.sha256(candidate).digest():
                raise UpdateError("installed_digest_mismatch")
            self._validate_helper(installed)
            output = self.selftest_runner(self.paths.helper)
            if not SELF_TEST_LINE_RE.fullmatch(output):
                raise UpdateError("self_test_result_invalid")
        except Exception as exc:
            # Restore exact previously verified bytes atomically; preserve backup copy.
            try:
                self._write_new_root_file(self.paths.helper, current, HELPER_MODE)
                restored = self._read_fixed_file(self.paths.helper, uid=self.identity.root_uid,
                                                 gid=self.identity.root_gid, mode=HELPER_MODE,
                                                 limit=MAX_CANDIDATE_BYTES)
                if hashlib.sha256(restored).digest() != previous_digest:
                    raise UpdateError("rollback_verification_failed")
            except Exception as rollback_exc:
                raise UpdateError("rollback_failed") from rollback_exc
            if isinstance(exc, UpdateError):
                raise exc
            raise UpdateError("post_install_validation_failed") from exc
        return digest, str(backup)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    updater = AdminHelperUpdater()
    try:
        if not parse_cli_args(args):
            updater._audit("denied", "arguments_not_allowed")
            return 2
        if os.geteuid() != 0:
            updater._audit("failure", "root_required")
            return 1
        updater._audit("start", "update_started")
        digest, backup = updater.update()
        updater._audit("success", "verified_and_installed")
        print("OptiBrain admin helper updated and self-test passed; sha256=" + digest
              + "; preserved_previous=" + backup)
        return 0
    except UpdateError as exc:
        try:
            updater._audit("failure", str(exc))
        except UpdateError:
            pass
        print("optibrain-admin-update: update failed safely", file=sys.stderr)
        return 1
    except Exception:
        try:
            updater._audit("failure", "unexpected_failure")
        except UpdateError:
            pass
        print("optibrain-admin-update: update failed safely", file=sys.stderr)
        return 1


def parse_cli_args(args: list[str]) -> bool:
    if args:
        raise UpdateError("arguments_not_allowed")
    return True


if __name__ == "__main__":
    sys.exit(main())
