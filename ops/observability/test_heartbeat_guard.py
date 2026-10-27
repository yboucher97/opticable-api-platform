"""Tests are offline, provider-free, and cannot mutate production."""
import copy
from datetime import datetime, timezone
import unittest

from heartbeat_guard import evaluate

NOW = datetime(2026, 10, 27, 5, 15, tzinfo=timezone.utc)


def fixture():
    roster = {"schema": 1, "jobs": [
        {"job_id": "cloudflare.cron", "scheduler": "cloudflare", "expected": "active", "max_silence_seconds": 1800},
        {"job_id": "customer.mail", "scheduler": "systemd", "expected": "disabled_intentionally"},
    ]}
    snapshot = {"schema": 1, "observed_at_utc": "2026-10-27T05:14:00Z", "jobs": [
        {"job_id": "cloudflare.cron", "scheduler": "cloudflare", "last_success_utc": "2026-10-27T05:10:00Z"},
        {"job_id": "customer.mail", "scheduler": "systemd", "last_success_utc": None},
    ]}
    return roster, snapshot


class HeartbeatGuardTests(unittest.TestCase):
    def test_complete_good_roster(self):
        roster, snap = fixture()
        result = evaluate(roster, snap, NOW)
        self.assertTrue(result["healthy"])
        self.assertEqual([j["status"] for j in result["jobs"]], ["OK", "EXPECTED_OFF"])

    def test_missed_heartbeat(self):
        roster, snap = fixture()
        snap["jobs"][0]["last_success_utc"] = "2026-10-27T03:10:00Z"
        result = evaluate(roster, snap, NOW)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["jobs"][0]["status"], "MISSED_HEARTBEAT")

    def test_missing_job_never_green(self):
        roster, snap = fixture()
        del snap["jobs"][0]
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_unrecognized_job_never_green(self):
        roster, snap = fixture()
        snap["jobs"].append({"job_id": "unapproved", "scheduler": "systemd"})
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_untrusted_snapshot_cannot_disable_job(self):
        roster, snap = fixture()
        snap["jobs"][0]["expected"] = "disabled_intentionally"
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_untrusted_snapshot_cannot_increase_deadline(self):
        roster, snap = fixture()
        snap["jobs"][0]["max_silence_seconds"] = 99999
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_no_proven_success(self):
        roster, snap = fixture()
        snap["jobs"][0]["last_success_utc"] = None
        self.assertEqual(evaluate(roster, snap, NOW)["jobs"][0]["status"], "NO_PROVEN_SUCCESS")

    def test_future_success_fails(self):
        roster, snap = fixture()
        snap["jobs"][0]["last_success_utc"] = "2026-10-27T06:15:00Z"
        self.assertEqual(evaluate(roster, snap, NOW)["jobs"][0]["status"], "IMPOSSIBLE_TIMESTAMP")

    def test_success_after_snapshot_fails(self):
        roster, snap = fixture()
        snap["jobs"][0]["last_success_utc"] = "2026-10-27T05:14:30Z"
        self.assertEqual(evaluate(roster, snap, NOW)["jobs"][0]["status"], "IMPOSSIBLE_TIMESTAMP")

    def test_duplicate_roster_rejected(self):
        roster, snap = fixture()
        roster["jobs"].append(copy.deepcopy(roster["jobs"][0]))
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_duplicate_snapshot_rejected(self):
        roster, snap = fixture()
        snap["jobs"].append(copy.deepcopy(snap["jobs"][0]))
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_mismatched_scheduler_rejected(self):
        roster, snap = fixture()
        snap["jobs"][0]["scheduler"] = "github"
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_stale_snapshot_rejected(self):
        roster, snap = fixture()
        snap["observed_at_utc"] = "2026-10-26T05:14:00Z"
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_future_snapshot_rejected(self):
        roster, snap = fixture()
        snap["observed_at_utc"] = "2026-10-28T05:14:00Z"
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_non_utc_timestamp_rejected(self):
        roster, snap = fixture()
        snap["observed_at_utc"] = "2026-10-27T01:14:00-04:00"
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_wrong_schema_rejected(self):
        roster, snap = fixture()
        roster["schema"] = 2
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_boolean_max_silence_rejected(self):
        roster, snap = fixture()
        roster["jobs"][0]["max_silence_seconds"] = True
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_max_silence_bounds(self):
        roster, snap = fixture()
        roster["jobs"][0]["max_silence_seconds"] = 1
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_invalid_now_rejected(self):
        roster, snap = fixture()
        with self.assertRaises(ValueError):
            evaluate(roster, snap, datetime(2026, 10, 27, 5, 15))

    def test_missing_job_id_rejected(self):
        roster, snap = fixture()
        del snap["jobs"][0]["job_id"]
        with self.assertRaises(ValueError):
            evaluate(roster, snap, NOW)

    def test_off_policy_controlled_by_roster_only(self):
        roster, snap = fixture()
        roster["jobs"][0]["expected"] = "disabled_intentionally"
        self.assertTrue(evaluate(roster, snap, NOW)["healthy"])
        self.assertEqual(evaluate(roster, snap, NOW)["jobs"][0]["status"], "EXPECTED_OFF")


if __name__ == "__main__":
    unittest.main()
