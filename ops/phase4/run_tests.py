#!/usr/bin/env python3
"""Count tests and subtests explicitly; persist only an execution summary."""
import argparse
import json
from pathlib import Path
import sys
import unittest

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))


class CountedResult(unittest.TextTestResult):
    subtests = 0

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", default="test*.py")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(APP / "tests"), pattern=args.pattern)
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountedResult).run(suite)
    print(json.dumps({"tests": result.testsRun, "subtests": result.subtests, "failures": len(result.failures),
                      "errors": len(result.errors), "skipped": len(result.skipped), "passed": result.wasSuccessful()}, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
