#!/usr/bin/python3 -I
"""Root-owned, fixed-operation OptiBrain maintenance interface."""
import datetime
import fcntl
import hashlib
import json
import os
import pwd
import re
import resource
import secrets
import signal
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import urllib.request

AUDIT_DIR = "/var/log/optibrain"
AUDIT_FILE = AUDIT_DIR + "/admin-audit.jsonl"
BACKUP_DIR = "/var/backups/optibrain"
BACKUP_SCRIPT = "/usr/local/lib/optibrain-backup/optibrain-backup.sh"
UPLOAD_SERVICE = "optibrain-phase2a-upload.service"
TIMERS = ("optibrain-backup.timer", "optibrain-phase2a-upload.timer")
SERVICES = ("opticable-workflow-api.service", "opticable-password-pdf.service", "opticable-omada-site.service")
LOG_SERVICES = SERVICES + ("optibrain-backup.service", "optibrain-phase2a-upload.service")
HEALTH_URLS = (
    "https://optibrain.opticable.ca/v1/system/health",
    "https://optibrain.opticable.ca/pdf/health",
    "https://optibrain.opticable.ca/omada/api/health",
)
HELPER_VERSION = "1"
ADMIN_POLICY_ID = "opticable-admin-helper-v1"
RUNBOOK_CANDIDATE = "/var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
RUNBOOK_CANDIDATE_DIGEST = "/var/tmp/optibrain-admin-update/incoming/master-runbook.sha256"
RUNBOOK_AUTHORIZED_DIGEST = "/etc/optibrain/master-runbook.sha256"
RUNBOOK_DESTINATION = "/opt/opticable-api-platform/docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
RUNBOOK_BACKUP_DIR = "/var/lib/optibrain/admin-update/previous"
RESTORE_DRILL = "/usr/local/lib/optibrain-backup/optibrain-restore-drill.py"
BACKUP_LOCK = "/run/lock/optibrain-admin-backup.lock"
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
_ACTOR = "root"
_SECRET_ASSIGNMENT = re.compile(
    r'''(?i)((?:"|')?[A-Za-z0-9_-]{1,128}(?:"|')?\s*[:=]\s*)(?:"[^"\r\n]{0,4096}"|'[^'\r\n]{0,4096}'|[^\s,;]{1,4096})'''
)
_SECRET_KEY_PARTS = ("authorization", "cookie", "password", "passwd", "secret", "token",
                     "credential", "api_key", "api-key", "private_key", "private-key")
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL)


def parse_request(args):
    if args == ["--self-test"]:
        return ("--self-test",)
    if args in (["help"], ["health"], ["scheduler"], ["capacity"],
                ["backup"], ["verify-latest"], ["upload"], ["queue-status"],
                ["restore-verify-latest"], ["sync-master-runbook"]):
        return tuple(args)
    if len(args) == 2 and args[0] in ("service-status", "service-restart", "service-reload") and args[1] in SERVICES:
        return tuple(args)
    if len(args) == 2 and args[0] == "timer-status" and args[1] in TIMERS:
        return tuple(args)
    if len(args) in (2, 3) and args[0] == "logs" and args[1] in LOG_SERVICES:
        if len(args) == 2:
            return ("logs", args[1], "50")
        if re.fullmatch(r"[1-9][0-9]{0,2}", args[2]) and 1 <= int(args[2]) <= 200:
            return ("logs", args[1], args[2])
    raise ValueError("unsupported operation")


def audit_start(operation):
    st = os.stat(AUDIT_DIR, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        raise RuntimeError("unsafe audit directory")
    fd = os.open(AUDIT_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fst = os.fstat(fd)
    if (not stat.S_ISREG(fst.st_mode) or fst.st_uid != 0 or fst.st_gid != 0
            or stat.S_IMODE(fst.st_mode) != 0o600 or fst.st_nlink != 1):
        os.close(fd)
        raise RuntimeError("unsafe audit file")
    entry = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "actor": _ACTOR,
             "operation": list(operation), "phase": "start"}
    os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode())
    os.fsync(fd)
    return fd


def audit_end(fd, operation, result):
    entry = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "actor": _ACTOR,
             "operation": list(operation), "phase": "finish", "result": result}
    os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode())
    os.fsync(fd)
    os.close(fd)


def run(argv, timeout=900, quiet=False):
    _validate_command(argv)
    if argv[0] == "/usr/bin/journalctl":
        def child_limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
            resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with tempfile.TemporaryFile(mode="w+b") as output:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.DEVNULL, timeout=min(timeout, 30),
                                    check=False, env={"PATH": SAFE_PATH, "LANG": "C.UTF-8",
                                                      "LC_ALL": "C.UTF-8"},
                                    close_fds=True, shell=False, preexec_fn=child_limits)
            output.seek(0)
            captured = output.read(65536)
            if result.returncode not in (0, -signal.SIGXFSZ):
                raise RuntimeError("fixed log query failed")
            text = _redact(captured)
            if result.returncode == -signal.SIGXFSZ:
                text += "\n[log output truncated at 65536 bytes]"
            if not quiet:
                sys.stdout.write(text)
            return text.strip()
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False,
                            env={"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                            close_fds=True, shell=False)
    if result.returncode:
        raise RuntimeError("operation failed")
    if not quiet and result.stdout:
        sys.stdout.buffer.write(_redact(result.stdout).encode("utf-8"))
    return result.stdout.decode("utf-8", "replace").strip()


def _validate_command(argv):
    """Second-line allowlist: this helper never acts as a generic command runner."""
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
        raise RuntimeError("invalid fixed command")
    executable, *args = argv
    if executable == "/usr/bin/systemctl":
        if len(args) == 2 and args[0] in ("is-active", "is-enabled") and args[1] in SERVICES + TIMERS:
            return
        if len(args) == 2 and args[0] in ("restart", "reload") and args[1] in SERVICES:
            return
        if args == ["start", "--wait", UPLOAD_SERVICE]:
            return
    elif executable == "/usr/bin/df" and args == ["-h", "/var/backups/optibrain", "/var/lib/optibrain"]:
        return
    elif executable == "/usr/bin/sha256sum" and len(args) == 2 and args[0] == "-c":
        if re.fullmatch(r"/var/backups/optibrain/optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz\.sha256", args[1]):
            return
    elif executable == BACKUP_SCRIPT:
        if args == []:
            return
        if len(args) == 2 and args[0] == "--verify" and re.fullmatch(
                r"/var/backups/optibrain/optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz", args[1]):
            return
    elif executable == "/usr/bin/journalctl":
        if (len(args) == 7 and args[0:3] == ["--no-pager", "--output=short-iso", "--unit"]
                and args[3] in LOG_SERVICES and args[4] == "--lines"
                and re.fullmatch(r"[1-9][0-9]{0,2}", args[5]) is not None
                and int(args[5]) <= 200 and args[6] == "--quiet"):
            return
    elif executable == "/usr/bin/python3" and len(args) == 4 and args[0] == "-I" and args[1] == RESTORE_DRILL:
        if (re.fullmatch(r"/var/backups/optibrain/optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz", args[2])
                and re.fullmatch(r"[0-9a-f]{64}", args[3])):
            return
    raise RuntimeError("command is outside the fixed OptiBrain command policy")


def _redact(data):
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    text = _PRIVATE_KEY_BLOCK.sub("[REDACTED PRIVATE KEY BLOCK]", text)
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    def redact_assignment(match):
        key = match.group(1).split(":", 1)[0].split("=", 1)[0].strip(" \t\"'").lower()
        if any(part in key for part in _SECRET_KEY_PARTS):
            return match.group(1) + "[REDACTED]"
        return match.group(0)
    text = _SECRET_ASSIGNMENT.sub(redact_assignment, text)
    return text[:65536]


def _validate_fixed_root_file(path, mode):
    parent = os.path.dirname(path)
    while parent != "/":
        parent_stat = os.lstat(parent)
        if (not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != 0
                or stat.S_IMODE(parent_stat.st_mode) & 0o022):
            raise RuntimeError("fixed OptiBrain path parent policy mismatch")
        parent = os.path.dirname(parent)
    item = os.lstat(path)
    if (not stat.S_ISREG(item.st_mode) or item.st_uid != 0 or item.st_gid != 0
            or stat.S_IMODE(item.st_mode) != mode or item.st_nlink != 1):
        raise RuntimeError("fixed OptiBrain executable/configuration policy mismatch")


def _retention_limit(config_text):
    values = []
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("OPTIBRAIN_BACKUP_RETENTION"):
            match = re.fullmatch(r"OPTIBRAIN_BACKUP_RETENTION=([1-9][0-9]*)", stripped)
            if not match:
                raise RuntimeError("backup retention configuration is not fixed")
            values.append(int(match.group(1)))
    if len(values) > 1:
        raise RuntimeError("duplicate backup retention configuration")
    return values[0] if values else 7


def _require_backup_headroom():
    with open("/etc/optibrain/backup.conf", "r", encoding="ascii") as handle:
        configured = _retention_limit(handle.read())
    if configured != 7:
        raise RuntimeError("backup retention differs from reviewed seven-generation policy")
    directory = os.lstat(BACKUP_DIR)
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0
            or stat.S_IMODE(directory.st_mode) != 0o700):
        raise RuntimeError("backup directory policy mismatch")
    pattern = re.compile(r"optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz")
    count = sum(1 for name in os.listdir(BACKUP_DIR) if pattern.fullmatch(name))
    # Keep two slots so one timer run racing this manual run cannot trigger cleanup.
    if count >= configured - 1:
        raise RuntimeError("manual backup paused: insufficient non-destructive retention headroom")


def _run_manual_backup():
    parent_stat = os.lstat(os.path.dirname(BACKUP_LOCK))
    if (not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != 0 or parent_stat.st_gid != 0
            or stat.S_IMODE(parent_stat.st_mode) & 0o022):
        raise RuntimeError("unsafe backup coordination directory")
    fd = os.open(BACKUP_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        lock_stat = os.fstat(fd)
        if (not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != 0 or lock_stat.st_gid != 0
                or stat.S_IMODE(lock_stat.st_mode) != 0o600 or lock_stat.st_nlink != 1):
            raise RuntimeError("unsafe backup coordination lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("manual backup already running") from exc
        _require_backup_headroom()
        run([BACKUP_SCRIPT], timeout=3600, quiet=True)
    finally:
        os.close(fd)


def execute(op):
    name = op[0]
    if name == "--self-test":
        if not parse_request(["health"]) or not parse_request(["verify-latest"]):
            raise RuntimeError("self-test failed")
        try:
            parse_request(["shell", "-c", "id"])
        except ValueError:
            pass
        else:
            raise RuntimeError("self-test failed")
        try:
            _validate_command(["/bin/sh", "-c", "id"])
        except RuntimeError:
            pass
        else:
            raise RuntimeError("self-test failed")
        print(f"OPTIBRAIN_ADMIN_SELF_TEST_OK {HELPER_VERSION}")
    elif name == "help":
        print("health | scheduler | capacity | backup | verify-latest | restore-verify-latest | upload | queue-status | logs SERVICE [LINES] | sync-master-runbook | service-status SERVICE | service-restart SERVICE | service-reload SERVICE | timer-status TIMER")
    elif name == "health":
        for url in HEALTH_URLS:
            req = urllib.request.Request(url, headers={"User-Agent": "optibrain-admin/1"})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError("health check failed")
                print(f"{url.split('/')[2]}: HTTP {response.status}")
    elif name == "scheduler":
        for timer in TIMERS:
            active = run(["/usr/bin/systemctl", "is-active", timer])
            enabled = run(["/usr/bin/systemctl", "is-enabled", timer])
            print(f"{timer}: active={active} enabled={enabled}")
    elif name == "timer-status":
        print(f"{op[1]}: active={run(['/usr/bin/systemctl','is-active',op[1]])} enabled={run(['/usr/bin/systemctl','is-enabled',op[1]])}")
    elif name == "capacity":
        run(["/usr/bin/df", "-h", "/var/backups/optibrain", "/var/lib/optibrain"])
        usage = shutil.disk_usage("/var/backups/optibrain")
        print(f"backup_bytes={usage.total} used_bytes={usage.used} free_bytes={usage.free}")
    elif name == "backup":
        _validate_fixed_root_file(BACKUP_SCRIPT, 0o750)
        _validate_fixed_root_file("/etc/optibrain/backup.conf", 0o640)
        _run_manual_backup()
        print("backup: completed")
    elif name == "verify-latest":
        archive = _latest_archive()
        _validate_fixed_root_file(BACKUP_SCRIPT, 0o750)
        run(["/usr/bin/sha256sum", "-c", archive + ".sha256"], quiet=True)
        run([BACKUP_SCRIPT, "--verify", archive], timeout=3600, quiet=True)
        print(f"archive verification: passed ({os.path.basename(archive)})")
    elif name == "restore-verify-latest":
        archive = _latest_archive()
        _validate_fixed_root_file(RESTORE_DRILL, 0o750)
        sidecar = archive + ".sha256"
        with open(sidecar, "r", encoding="ascii") as handle:
            match = re.fullmatch(r"([0-9a-f]{64})  optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz\n", handle.read())
        if not match:
            raise RuntimeError("backup digest sidecar invalid")
        run(["/usr/bin/python3", "-I", RESTORE_DRILL, archive, match.group(1)], timeout=3600, quiet=False)
    elif name == "upload":
        run(["/usr/bin/systemctl", "start", "--wait", UPLOAD_SERVICE], timeout=3600, quiet=True)
        print("off-host verification: completed")
    elif name == "queue-status":
        db = "/var/lib/opticable-workflow-api/output/automation/automation.db"
        db_stat = os.lstat(db)
        if not stat.S_ISREG(db_stat.st_mode) or db_stat.st_nlink != 1:
            raise RuntimeError("unsafe queue database")
        con = sqlite3.connect("file:" + db + "?mode=ro", uri=True, timeout=5)
        rows = con.execute("SELECT status,COUNT(*) FROM automation_runs GROUP BY status").fetchall()
        con.close()
        print("run_counts=" + json.dumps({str(state): count for state, count in rows}, sort_keys=True))
    elif name == "sync-master-runbook":
        digest = sync_master_runbook()
        print(f"master runbook synchronized: sha256={digest}")
    elif name == "service-status":
        print(f"{op[1]}: {run(['/usr/bin/systemctl','is-active',op[1]])}")
    elif name == "service-restart":
        run(["/usr/bin/systemctl", "restart", op[1]], timeout=180, quiet=True)
        print(f"{op[1]}: restart completed")
    elif name == "service-reload":
        run(["/usr/bin/systemctl", "reload", op[1]], timeout=180, quiet=True)
        print(f"{op[1]}: reload completed")
    elif name == "logs":
        output = run(["/usr/bin/journalctl", "--no-pager", "--output=short-iso", "--unit", op[1], "--lines", op[2], "--quiet"], timeout=30, quiet=True)
        print(_redact(output))
    else:
        raise ValueError("unsupported operation")


def main(args):
    sanitize_environment()
    try:
        op = parse_request(args)
    except ValueError:
        print("optibrain-admin: unsupported operation", file=sys.stderr)
        try:
            rejected = ("rejected",)
            fd = audit_start(rejected)
            audit_end(fd, rejected, "denied")
        except Exception:
            pass
        return 2
    if op in (("help",), ("--self-test",)):
        execute(op)
        return 0
    fd = audit_start(op)
    result = "success"
    try:
        execute(op)
    except Exception:
        result = "failure"
        print("optibrain-admin: operation failed; inspect root audit and service state", file=sys.stderr)
        return 1
    finally:
        audit_end(fd, op, result)
    return 0


def sanitize_environment():
    global _ACTOR
    _ACTOR = re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("SUDO_USER", "root"))[:64]
    os.environ.clear()
    os.environ.update({"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    os.umask(0o077)


def _read_pinned_file(path, *, uid, gid, mode, limit):
    st = os.lstat(path)
    if (not os.path.isfile(path) or os.path.islink(path) or st.st_uid != uid
            or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode or st.st_nlink != 1):
        raise RuntimeError("unsafe fixed input")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
            raise RuntimeError("input changed")
        content = bytearray()
        while len(content) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(fd)
        if len(content) > limit or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError("input changed or too large")
        return bytes(content)
    finally:
        os.close(fd)


def sync_master_runbook():
    """Publish only the root-authorized fixed runbook to its fixed repository path."""
    _validate_runbook_staging()
    uid = pwd.getpwnam("optibrain").pw_uid
    gid = pwd.getpwnam("optibrain").pw_gid
    candidate = _read_pinned_file(RUNBOOK_CANDIDATE, uid=uid, gid=gid, mode=0o440, limit=1024 * 1024)
    submitted = _read_pinned_file(RUNBOOK_CANDIDATE_DIGEST, uid=uid, gid=gid, mode=0o440, limit=128)
    authorized = _read_pinned_file(RUNBOOK_AUTHORIZED_DIGEST, uid=0, gid=0, mode=0o440, limit=128)
    digest = hashlib.sha256(candidate).hexdigest()
    digest_pattern = re.compile(rb"([0-9a-f]{64})\n?")
    submitted_match = digest_pattern.fullmatch(submitted)
    authorized_match = digest_pattern.fullmatch(authorized)
    if (not submitted_match or not authorized_match
            or digest.encode() != submitted_match.group(1)
            or digest.encode() != authorized_match.group(1)):
        raise RuntimeError("runbook digest authorization failed")
    try:
        text = candidate.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("runbook encoding invalid") from exc
    if b"\x00" in candidate or not text.startswith("# Opticable Automation Master Runbook\n"):
        raise RuntimeError("runbook format validation failed")

    # Walk every component with openat/O_NOFOLLOW. The directory fd pins the exact
    # docs directory even if a non-root owner renames it concurrently.
    directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        expected_dirs = (("opt", 0, 0, 0o755),
                         ("opticable-api-platform", uid, gid, 0o755),
                         ("docs", uid, gid, 0o775))
        for component, expected_uid, expected_gid, expected_mode in expected_dirs:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=directory_fd)
            opened_dir_stat = os.fstat(next_fd)
            if (opened_dir_stat.st_uid != expected_uid or opened_dir_stat.st_gid != expected_gid
                    or stat.S_IMODE(opened_dir_stat.st_mode) != expected_mode):
                os.close(next_fd)
                raise RuntimeError("runbook path ownership or mode mismatch")
            os.close(directory_fd)
            directory_fd = next_fd
        directory_stat = os.fstat(directory_fd)
        if directory_stat.st_uid != uid or directory_stat.st_gid != gid or stat.S_IMODE(directory_stat.st_mode) != 0o775:
            raise RuntimeError("runbook destination directory policy mismatch")
        dest_name = "OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
        current_fd = os.open(dest_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        try:
            current_stat = os.fstat(current_fd)
            if (not stat.S_ISREG(current_stat.st_mode) or current_stat.st_uid != 0
                    or current_stat.st_gid != 0 or stat.S_IMODE(current_stat.st_mode) != 0o644
                    or current_stat.st_nlink != 1):
                raise RuntimeError("runbook destination is not the expected root-owned file")
            previous_content = bytearray()
            while len(previous_content) <= 1024 * 1024:
                chunk = os.read(current_fd, min(65536, 1024 * 1024 + 1 - len(previous_content)))
                if not chunk:
                    break
                previous_content.extend(chunk)
            if len(previous_content) > 1024 * 1024:
                raise RuntimeError("runbook destination exceeds backup limit")
        finally:
            os.close(current_fd)
        old_digest = hashlib.sha256(previous_content).hexdigest()
        backup_dir_stat = os.lstat(RUNBOOK_BACKUP_DIR)
        if (not stat.S_ISDIR(backup_dir_stat.st_mode) or backup_dir_stat.st_uid != 0
                or backup_dir_stat.st_gid != 0 or stat.S_IMODE(backup_dir_stat.st_mode) != 0o700):
            raise RuntimeError("runbook recovery directory policy mismatch")
        state_fd = os.open(RUNBOOK_BACKUP_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        state_stat = os.fstat(state_fd)
        if state_stat.st_dev != directory_stat.st_dev:
            os.close(state_fd)
            raise RuntimeError("runbook atomic path crosses filesystems")
        backup_name = ("master-runbook-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                       + "-" + old_digest[:16] + ".md")
        backup_fd = os.open(backup_name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                            0o600, dir_fd=state_fd)
        try:
            os.fchown(backup_fd, 0, 0)
            offset = 0
            while offset < len(previous_content):
                offset += os.write(backup_fd, previous_content[offset:])
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)
        backup_read_fd = os.open(backup_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=state_fd)
        try:
            backup_content = bytearray()
            while len(backup_content) <= 1024 * 1024:
                chunk = os.read(backup_read_fd, min(65536, 1024 * 1024 + 1 - len(backup_content)))
                if not chunk:
                    break
                backup_content.extend(chunk)
            if hashlib.sha256(backup_content).hexdigest() != old_digest:
                raise RuntimeError("runbook recovery copy verification failed")
        finally:
            os.close(backup_read_fd)
        temp_name = ".OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md." + secrets.token_hex(12)
        temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=state_fd)
        try:
            os.fchown(temp_fd, 0, 0)
            os.fchmod(temp_fd, 0o644)
            offset = 0
            while offset < len(candidate):
                offset += os.write(temp_fd, candidate[offset:])
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)
        try:
            os.replace(temp_name, dest_name, src_dir_fd=state_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
            verify_fd = os.open(dest_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
            try:
                verify_stat = os.fstat(verify_fd)
                if (not stat.S_ISREG(verify_stat.st_mode) or verify_stat.st_uid != 0
                        or verify_stat.st_gid != 0 or stat.S_IMODE(verify_stat.st_mode) != 0o644
                        or verify_stat.st_nlink != 1):
                    raise RuntimeError("published runbook metadata verification failed")
                written = bytearray()
                while len(written) <= 1024 * 1024:
                    chunk = os.read(verify_fd, min(65536, 1024 * 1024 + 1 - len(written)))
                    if not chunk:
                        break
                    written.extend(chunk)
                if len(written) > 1024 * 1024 or hashlib.sha256(written).hexdigest() != digest:
                    raise RuntimeError("published runbook verification failed")
            finally:
                os.close(verify_fd)
        except Exception:
            # Restore the exact old bytes if the atomic publish/dir sync fails.
            restore_name = ".OPTICABLE_AUTOMATION_MASTER_RUNBOOK.restore." + secrets.token_hex(12)
            restore_fd = os.open(restore_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=state_fd)
            try:
                os.fchown(restore_fd, 0, 0)
                os.fchmod(restore_fd, 0o644)
                offset = 0
                while offset < len(previous_content):
                    offset += os.write(restore_fd, previous_content[offset:])
                os.fsync(restore_fd)
            finally:
                os.close(restore_fd)
            os.replace(restore_name, dest_name, src_dir_fd=state_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
            raise
        finally:
            os.close(state_fd)
        return digest
    finally:
        os.close(directory_fd)


def _validate_runbook_staging():
    """Require exact root-owned staging/auth parents before privileged reads."""
    expected = (
        ("/var", 0, 0, 0o755), ("/var/tmp", 0, 0, 0o1777),
        ("/var/tmp/optibrain-admin-update", 0, 0, 0o750),
        ("/var/tmp/optibrain-admin-update/incoming", 0, pwd.getpwnam("optibrain").pw_gid, 0o730),
        ("/etc/optibrain", 0, 0, 0o700),
        ("/var/lib/optibrain/admin-update/previous", 0, 0, 0o700),
    )
    for path, uid, gid, mode in expected:
        item = os.lstat(path)
        if not stat.S_ISDIR(item.st_mode) or item.st_uid != uid or item.st_gid != gid or stat.S_IMODE(item.st_mode) != mode:
            raise RuntimeError("runbook fixed staging path policy mismatch")


def _latest_archive():
    directory_stat = os.lstat(BACKUP_DIR)
    if (not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != 0
            or stat.S_IMODE(directory_stat.st_mode) != 0o700):
        raise RuntimeError("backup directory policy mismatch")
    files = [f for f in os.listdir(BACKUP_DIR) if re.fullmatch(r"optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz", f)]
    if not files:
        raise RuntimeError("no archive available")
    archive = os.path.join(BACKUP_DIR, max(files))
    for path in (archive, archive + ".sha256"):
        item = os.lstat(path)
        if (not stat.S_ISREG(item.st_mode) or item.st_uid != 0 or item.st_nlink != 1):
            raise RuntimeError("unsafe fixed backup input")
    return archive


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
