"""Append-only, replay-stable lifecycle evidence for verified Test Lab changes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

KINDS = {
    "active_project:deal": ("ACTIVE_PROJECT",),
    "cabling_cross_sell:deal": ("PROJECT_COMPLETED", "CROSS_SELL_IDENTIFIED"),
    "camera_maintenance:deal": ("PROJECT_COMPLETED", "MAINTENANCE_DUE"),
    "recurring_service:deal": ("PROJECT_COMPLETED", "RECURRING_SERVICE_STARTED"),
    "renewal_due:deal": ("PROJECT_COMPLETED", "RECURRING_SERVICE_STARTED"),
    "dormant:deal": ("PROJECT_COMPLETED", "DORMANT_CUSTOMER"),
    "camera_upsell:deal": ("PROJECT_COMPLETED", "UPSELL_IDENTIFIED"),
    "no_action:deal": ("PROJECT_COMPLETED",),
    "negative:dormant": ("DORMANCY_CLEARED",),
    "negative:camera_maintenance": ("MAINTENANCE_CURRENT",),
    "negative:renewal_due": ("RENEWAL_DUE",),
    "restore:dormant": ("DORMANT_CUSTOMER",),
    "restore:camera_maintenance": ("MAINTENANCE_DUE",),
}


def sync_verified_lab_events(state, view, path):
    if view.get("scope") != "lab" or view.get("writes_enabled") is not False:
        raise ValueError("Lifecycle events require a read-only Test Lab projection")
    by_account = {row["account_id"]: row for row in view["rows"]}
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS lifecycle_events ("
                   "event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, account_id TEXT NOT NULL, "
                   "deal_id TEXT NOT NULL, occurred_at_utc TEXT NOT NULL, source TEXT, "
                   "evidence_hash TEXT NOT NULL, test_only INTEGER NOT NULL CHECK(test_only=1))")
        added = 0
        for key, kinds in KINDS.items():
            operation = state.get("operations", {}).get(key)
            scenario_name = key.split(":")[-1] if key.startswith(("negative:", "restore:")) else key.split(":")[0]
            scenario = state.get("scenarios", {}).get(scenario_name)
            if not operation or operation.get("state") != "verified" or not scenario:
                continue
            account_id, deal_id = scenario["account_id"], scenario["deal_id"]
            row = by_account.get(account_id)
            if (not row or row.get("test_only") is not True
                    or deal_id not in row.get("deal_ids", [])):
                raise ValueError("Verified lifecycle event relationship changed")
            for kind in kinds:
                proof = json.dumps([key, kind, operation["payload_hash"], deal_id],
                                   separators=(",", ":"), ensure_ascii=False)
                digest = hashlib.sha256(proof.encode()).hexdigest()
                event_id = "OB-L-" + digest[:24].upper()
                prior = db.execute("SELECT evidence_hash FROM lifecycle_events WHERE event_id=?",
                                   (event_id,)).fetchone()
                if prior:
                    if prior[0] != digest:
                        raise ValueError("Lifecycle event replay conflicts")
                    continue
                db.execute("INSERT INTO lifecycle_events VALUES (?,?,?,?,?,?,?,1)",
                           (event_id, kind, account_id, deal_id, operation["at_utc"],
                            row["source"]["first"], digest))
                added += 1
        total = db.execute("SELECT count(*) FROM lifecycle_events").fetchone()[0]
        db.commit()
    return {"added": added, "total": total}
