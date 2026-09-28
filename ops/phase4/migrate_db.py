#!/usr/bin/env python3
"""The tested V1 -> V2 migration, with legacy-row preservation verification."""
import argparse
import json
import sqlite3
from pathlib import Path

from isolated_drill import AutomationStore, check, inventory, snapshot, smoke_policy


def migrate(path: Path) -> dict:
    before = inventory(path.resolve())
    check(before["version"] == 1, "migration_requires_v1")
    AutomationStore(path)
    after = inventory(path.resolve())
    check(after["version"] == 2, "migration_version")
    check(before["counts"] == after["counts"] and before["hashes"] == after["hashes"], "migration_changed_legacy_rows")
    return {"result": "PASS", "previous_version": 1, "new_version": 2, "legacy_row_counts": after["counts"],
            "legacy_row_hashes": "PASS", "integrity": "PASS", "foreign_keys": "PASS"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--snapshot-to", type=Path)
    args = parser.parse_args()
    try:
        if args.inspect:
            result = inventory(args.db.resolve())
            with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                sample = conn.execute("SELECT id,at,success,metadata_json FROM automation_audit "
                                      "WHERE category='automation_health' AND action='sample' ORDER BY id DESC LIMIT 1").fetchone()
                result["run_status_counts"] = dict(conn.execute("SELECT status,COUNT(*) FROM automation_runs GROUP BY status"))
                result["smoke_policy"] = smoke_policy(conn)
            result["watchdog_sample_at"] = sample[1] if sample else None
            result["watchdog_sample_id"] = sample[0] if sample else 0
            metadata = json.loads(sample[3]) if sample else {}
            result["watchdog_sample_healthy"] = bool(sample and sample[2] == 1 and isinstance(metadata, dict)
                                                     and metadata.get("status") == "ok" and metadata.get("worker_healthy") is True)
        elif args.snapshot_to:
            check(not args.snapshot_to.exists() and args.snapshot_to.resolve() != args.db.resolve(), "snapshot_target_exists")
            snapshot(args.db.resolve(), args.snapshot_to.resolve())
            result = {"result": "PASS", "snapshot": "PASS"}
        else:
            result = migrate(args.db)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"result": "FAIL", "category": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}))
        raise SystemExit(1)
