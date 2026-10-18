"""Regressions: GitHub's authenticated readiness watchdog must fail closed."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from readiness_guard import findings

SCRIPT = Path(__file__).with_name("readiness_guard.py")


class ReadinessGuardTests(unittest.TestCase):
    def test_healthy_and_nonaction_states(self):
        self.assertEqual(findings({"signals": [
            {"name": "Backup", "state": "OK"},
            {"name": "Queue", "state": "UNKNOWN"},
            {"name": "Timers", "state": "DEGRADED"}
        ]}), [])

    def test_action_required(self):
        self.assertEqual(findings({"signals": [
            {"name": "Backup", "state": "ACTION REQUIRED"},
            {"name": "Queue", "state": "ACTION REQUIRED"},
            {"name": "Disk", "state": "OK"}
        ]}), ["Backup", "Queue"])

    def test_malformed_or_unknown_envelope(self):
        inputs = [None, 1, [], {}, {"signals": None}, {"signals": {}},
                  {"signals": []}, {"signals": [None]}, {"signals": [{"name": "Disk"}]},
                  {"signals": [{"name": "", "state": "OK"}]},
                  {"signals": [{"name": "Disk", "state": 0}]},
                  {"signals": [{"name": "Disk", "state": "UNRECOGNIZED"}]},
                  {"signals": [{"name": "Disk\\nINJECT", "state": "OK"}]},
                  {"signals": [{"name": "Disk", "state": "OK"}, {"name": "Disk", "state": "OK"}]}]
        for payload in inputs:
            with self.subTest(payload=payload):
                self.assertTrue(findings(payload))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = Path(tmp) / "readiness.json"
            for raw, expected in [
                (json.dumps({"signals": [{"name": "Backup", "state": "OK"}]}), 0),
                (json.dumps({"signals": [{"name": "Backup", "state": "ACTION REQUIRED"}]}), 1),
                ('{not JSON', 2),
                ('{"signals":[]}', 1),
                ('{"signals":[{"name":"Disk","state":"UNKNOWN_STATE"}]}', 1),
            ]:
                response.write_text(raw, encoding="utf-8")
                with self.subTest(raw=raw):
                    result = subprocess.run([sys.executable, str(SCRIPT), str(response)],
                                            capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    if expected:
                        self.assertTrue(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
