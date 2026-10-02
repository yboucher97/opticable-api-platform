#!/usr/bin/env python3
"""Portable fake-provider regression; no production accounts/environment needed."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def main():
    if os.geteuid() == 0:
        # Fixtures deliberately exercise unprivileged authentication and Git.
        # A root invocation runs the SAME suite as the checkout owner, never
        # skips those assertions or imports candidate code with root authority.
        import pwd
        uid=ROOT.stat().st_uid
        if uid == 0:
            raise SystemExit('Validate an unprivileged isolated checkout, not root-owned production')
        user=pwd.getpwuid(uid).pw_name
        os.execve('/usr/sbin/runuser',['runuser','-u',user,'--',sys.executable,'-I',str(Path(__file__).resolve()),*sys.argv[1:]],
                  {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("focused", "full", "approval"), default="full")
    parser.add_argument('--pattern', action='append', help='Explicit changed-area patterns; requires --suite focused')
    args = parser.parse_args()
    if args.pattern and args.suite!='focused':parser.error('--pattern requires --suite focused')
    os.environ.clear()
    os.environ.update(PATH="/usr/bin:/bin", LANG="C.UTF-8", PYTHONDONTWRITEBYTECODE="1")
    sys.dont_write_bytecode = True
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append(1)
        raise AssertionError("Network access prohibited in fake-provider validation")
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = blocked
    socket.create_connection = socket.getaddrinfo = blocked
    # The API's default relative outputs are isolated even if imported by a test.
    with tempfile.TemporaryDirectory(prefix="optibrain-phase6-tests-") as temporary:
        os.chdir(temporary)
        app = ROOT / "apps/workflow-api"
        sys.path.insert(0, str(app))
        spec = importlib.util.spec_from_file_location("phase6_counted_runner", ROOT / "ops/phase4/run_tests.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = unittest.TestSuite()
        patterns = ["test*.py"] if args.suite == "full" else (
            ["test_phase6_outbound_approval.py"] if args.suite == "approval" else ["test_phase6*.py"])
        if args.pattern:patterns=args.pattern
        for pattern in patterns:
            suite.addTests(unittest.defaultTestLoader.discover(str(app / "tests"), pattern=pattern))
        result = unittest.TextTestRunner(verbosity=2, resultclass=module.CountedResult).run(suite)
        passed = result.wasSuccessful() and not result.skipped and not attempts
        print(json.dumps({"tests": result.testsRun, "subtests": result.subtests,
                          "failures": len(result.failures), "errors": len(result.errors),
                          "skipped": len(result.skipped), "blocked_network_attempts": len(attempts), "passed": passed}))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
