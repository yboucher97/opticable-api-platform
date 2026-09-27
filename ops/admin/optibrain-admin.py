#!/usr/bin/python3
"""Root-owned, fixed-operation OptiBrain maintenance interface."""
import datetime
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import urllib.request

AUDIT_DIR = "/var/log/optibrain"
AUDIT_FILE = AUDIT_DIR + "/admin-audit.jsonl"
BACKUP_DIR = "/var/backups/optibrain"
BACKUP_SCRIPT = "/usr/local/lib/optibrain-backup/optibrain-backup.sh"
UPLOAD_SERVICE = "optibrain-phase2a-upload.service"
TIMERS = ("optibrain-backup.timer", "optibrain-phase2a-upload.timer")
SERVICES = ("opticable-workflow-api.service", "opticable-password-pdf.service", "opticable-omada-site.service")
HEALTH_URLS = (
    "https://optibrain.opticable.ca/v1/system/health",
    "https://optibrain.opticable.ca/pdf/health",
    "https://optibrain.opticable.ca/omada/api/health",
)
HELPER_VERSION = "1"
RUNBOOK_CANDIDATE = "/var/tmp/optibrain-admin-update/incoming/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
RUNBOOK_CANDIDATE_DIGEST = "/var/tmp/optibrain-admin-update/incoming/master-runbook.sha256"
RUNBOOK_AUTHORIZED_DIGEST = "/etc/optibrain/master-runbook.sha256"
RUNBOOK_DESTINATION = "/opt/opticable-api-platform/docs/OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md"
RUNBOOK_BACKUP_DIR = "/var/lib/optibrain/admin-update/previous"


def parse_request(args):
    if args == ["--self-test"]:
        return ("--self-test",)
    if args in (["help"], ["health"], ["scheduler"], ["capacity"],
                ["backup"], ["verify-latest"], ["upload"], ["queue-status"],
                ["sync-master-runbook"]):
        return tuple(args)
    if len(args) == 2 and args[0] in ("service-status", "service-restart") and args[1] in SERVICES:
        return tuple(args)
    if len(args) == 2 and args[0] == "timer-status" and args[1] in TIMERS:
        return tuple(args)
    raise ValueError("unsupported operation")


def audit_start(operation):
    st = os.stat(AUDIT_DIR, follow_symlinks=False)
    if st.st_uid != 0 or st.st_mode & 0o022:
        raise RuntimeError("unsafe audit directory")
    fd = os.open(AUDIT_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fst = os.fstat(fd)
    if fst.st_uid != 0 or fst.st_mode & 0o077:
        os.close(fd)
        raise RuntimeError("unsafe audit file")
    entry = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "actor": re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("SUDO_USER", "root"))[:64],
             "operation": list(operation), "phase": "start"}
    os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode())
    os.fsync(fd)
    return fd


def audit_end(fd, operation, result):
    entry = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "actor": re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("SUDO_USER", "root"))[:64],
             "operation": list(operation), "phase": "finish", "result": result}
    os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode())
    os.fsync(fd)
    os.close(fd)


def run(argv, timeout=900, quiet=False):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False,
                            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})
    if result.returncode:
        raise RuntimeError("operation failed")
    if not quiet and result.stdout:
        sys.stdout.buffer.write(result.stdout)
    return result.stdout.decode("utf-8", "replace").strip()


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
        print(f"OPTIBRAIN_ADMIN_SELF_TEST_OK {HELPER_VERSION}")
    elif name == "help":
        print("health | scheduler | capacity | backup | verify-latest | upload | queue-status | sync-master-runbook | service-status SERVICE | service-restart SERVICE | timer-status TIMER")
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
        run([BACKUP_SCRIPT], timeout=3600, quiet=True)
        print("backup: completed")
    elif name == "verify-latest":
        files = [f for f in os.listdir(BACKUP_DIR) if re.fullmatch(r"optibrain-backup-[0-9]{8}T[0-9]{6}Z\.tar\.gz", f)]
        if not files:
            raise RuntimeError("no archive available")
        archive = os.path.join(BACKUP_DIR, max(files))
        run(["/usr/bin/sha256sum", "-c", archive + ".sha256"], quiet=True)
        run([BACKUP_SCRIPT, "--verify", archive], timeout=3600, quiet=True)
        print(f"archive verification: passed ({os.path.basename(archive)})")
    elif name == "upload":
        run(["/usr/bin/systemctl", "start", "--wait", UPLOAD_SERVICE], timeout=3600, quiet=True)
        print("off-host verification: completed")
    elif name == "queue-status":
        db = "/var/lib/opticable-workflow-api/output/automation/automation.db"
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
    else:
        raise ValueError("unsupported operation")


def main(args):
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
        backup_name = ("master-runbook-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                       + "-" + old_digest[:16] + ".md")
        backup_fd = os.open(os.path.join(RUNBOOK_BACKUP_DIR, backup_name),
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchown(backup_fd, 0, 0)
            offset = 0
            while offset < len(previous_content):
                offset += os.write(backup_fd, previous_content[offset:])
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)
        temp_name = ".OPTICABLE_AUTOMATION_MASTER_RUNBOOK.md." + secrets.token_hex(12)
        temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
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
            os.rename(temp_name, dest_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except Exception:
            # Restore the exact old bytes if the atomic publish/dir sync fails.
            restore_name = ".OPTICABLE_AUTOMATION_MASTER_RUNBOOK.restore." + secrets.token_hex(12)
            restore_fd = os.open(restore_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory_fd)
            try:
                os.fchown(restore_fd, 0, 0)
                os.fchmod(restore_fd, 0o644)
                offset = 0
                while offset < len(previous_content):
                    offset += os.write(restore_fd, previous_content[offset:])
                os.fsync(restore_fd)
            finally:
                os.close(restore_fd)
            os.rename(restore_name, dest_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
            raise
        return digest
    finally:
        os.close(directory_fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
