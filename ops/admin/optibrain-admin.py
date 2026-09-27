#!/usr/bin/python3
"""Root-owned, fixed-operation OptiBrain maintenance interface."""
import datetime
import json
import os
import re
import shutil
import sqlite3
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


def parse_request(args):
    if args in (["help"], ["health"], ["scheduler"], ["capacity"],
                ["backup"], ["verify-latest"], ["upload"], ["queue-status"]):
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
    if name == "help":
        print("health | scheduler | capacity | backup | verify-latest | upload | queue-status | service-status SERVICE | service-restart SERVICE | timer-status TIMER")
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
    if op == ("help",):
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
