#!/usr/bin/env python3
"""Evaluate independently collected OptiBrain job heartbeats, without side effects.

IMPORTANT: This module does not collect health, establish trust, send alerts,
modify provider state, or schedule itself. Do NOT treat it as deployed monitoring.
Call with a TRUSTED, separately maintained roster and a fresh collector snapshot.
Neither document should carry secrets, tokens, email addresses or customer data.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_VALID_EXPECTED = frozenset(("active", "disabled_intentionally"))
_MAX_SNAPSHOT_AGE_SECONDS = 900


def _utc(value):
    """UTC-Z only; reject local, naive, numeric, or ambiguous timestamps."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamp must end with Z")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("Invalid UTC offset")
    return dt


def _name(value, label):
    if not isinstance(value, str) or not _SAFE_NAME.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _items(doc, label):
    if not isinstance(doc, dict) or type(doc.get("schema")) is not int or doc["schema"] != 1:
        raise ValueError(f"Invalid {label} schema")
    jobs = doc.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(f"{label} jobs must be nonempty")
    if len(jobs) > 1000:
        raise ValueError(f"{label} jobs exceed maximum")
    out = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError(f"Invalid {label} job")
        ident = _name(job.get("job_id"), "job_id")
        if ident in out:
            raise ValueError(f"Duplicate {label} job_id")
        out[ident] = job
    return out


def evaluate(roster, snapshot, now, *, maximum_snapshot_age_seconds=_MAX_SNAPSHOT_AGE_SECONDS):
    """Return failure statuses only from an independently approved job roster.

    A snapshot missing even one expected job NEVER silently passes. Roster controls
    intentional OFF state; the observed snapshot cannot declare a job disabled.
    last_success_utc must be actual successful completion evidence, not a cron tick.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise ValueError("now must be timezone-aware UTC")
    if type(maximum_snapshot_age_seconds) is not int or maximum_snapshot_age_seconds < 1:
        raise ValueError("Invalid maximum snapshot age")
    expected = _items(roster, "roster")
    observed = _items(snapshot, "snapshot")
    observed_time = _utc(snapshot.get("observed_at_utc"))
    age = (now - observed_time).total_seconds()
    if age < -5 or age > maximum_snapshot_age_seconds:
        raise ValueError("Snapshot stale or future-dated")
    # Reject unknown as well as missing, preventing green status on partial inventory.
    if set(expected) != set(observed):
        raise ValueError("Snapshot job roster is incomplete or unexpected")

    outcomes = []
    for ident in sorted(expected):
        config, record = expected[ident], observed[ident]
        scheduler = _name(config.get("scheduler"), "scheduler")
        if record.get("scheduler") != scheduler:
            raise ValueError("Snapshot scheduler does not match trusted roster")
        mode = config.get("expected")
        if not isinstance(mode, str) or mode not in _VALID_EXPECTED:
            raise ValueError("Unrecognized expected state in trusted roster")
        # A reported disabled state cannot weaken the authoritative expected state.
        if "expected" in record or "max_silence_seconds" in record:
            raise ValueError("Snapshot may not override expected job policy")
        if mode == "disabled_intentionally":
            # OFF jobs still need a valid roster entry but don't require a run.
            status, seconds = "EXPECTED_OFF", None
        else:
            limit = config.get("max_silence_seconds")
            if type(limit) is not int or not 60 <= limit <= 30 * 86400:
                raise ValueError("Invalid maximum silence in roster")
            raw = record.get("last_success_utc")
            if raw is None:
                status, seconds = "NO_PROVEN_SUCCESS", None
            else:
                success_time = _utc(raw)
                seconds = int((now - success_time).total_seconds())
                if success_time > observed_time or seconds < -5:
                    status = "IMPOSSIBLE_TIMESTAMP"
                elif seconds > limit:
                    status = "MISSED_HEARTBEAT"
                else:
                    status = "OK"
        outcomes.append({"job_id": ident, "scheduler": scheduler,
                         "status": status, "seconds_since_success": seconds})
    bad = sum(x["status"] not in ("OK", "EXPECTED_OFF") for x in outcomes)
    return {"healthy": bad == 0, "failures": bad,
            "observed_at_utc": snapshot["observed_at_utc"], "jobs": outcomes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roster", type=Path, help="Trusted independent expected-job inventory JSON")
    parser.add_argument("snapshot", type=Path, help="Independent collector snapshot JSON")
    parser.add_argument("--now-utc", help="UTC fixture override; do not use in live monitoring")
    args = parser.parse_args(argv)
    try:
        now = _utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
        result = evaluate(json.loads(args.roster.read_text(encoding="utf-8")),
                          json.loads(args.snapshot.read_text(encoding="utf-8")), now)
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        # No customer, credential, or raw snapshot content is exposed.
        print(json.dumps({"healthy": False, "failures": 1,
                          "reason": "heartbeat_evidence_unverifiable",
                          "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
