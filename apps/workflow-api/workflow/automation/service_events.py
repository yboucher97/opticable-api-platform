"""Idempotent lifecycle transitions from fresh, read-only CRM Service evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def reconcile_service_events(view, path, *, now=None):
    if view.get("scope") != "lab" or view.get("writes_enabled") is not False:
        raise ValueError("Automated service events require the isolated read-only Lab view")
    clock = now or datetime.now(timezone.utc)
    if clock.utcoffset() is None:
        raise ValueError("Lifecycle event clock must be timezone-aware")
    accounts = {str(row["account_id"]) for row in view["rows"] if row["test_only"] is True}
    rows = view.get("service_rows") or []
    if len({str(row["id"]) for row in rows}) != len(rows):
        raise ValueError("Service event inventory has duplicate identities")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    inserted = 0
    with sqlite3.connect(target) as db:
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("CREATE TABLE IF NOT EXISTS service_state ("
                   "service_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS service_events ("
                   "event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, service_id TEXT NOT NULL, "
                   "account_id TEXT NOT NULL, occurred_at_utc TEXT NOT NULL, evidence_hash TEXT NOT NULL, "
                   "test_only INTEGER NOT NULL CHECK(test_only=1))")
        db.execute("BEGIN IMMEDIATE")
        for row in rows:
            if row.get("test_only") is not True or row.get("account_id") not in accounts:
                raise ValueError("Lifecycle event escaped Test Lab relationship")
            sid = str(row["id"])
            prior = db.execute("SELECT state_json FROM service_state WHERE service_id=?", (sid,)).fetchone()
            old = json.loads(prior[0]) if prior else {}
            state = {key: row.get(key) for key in (
                "installed_on", "active_recurring", "maintenance_status", "maintenance_due_on",
                "last_service_on", "renewal_status", "renewal_on", "contract_signed_at")}
            events = []
            if state["installed_on"] and state["installed_on"] != old.get("installed_on"):
                events.append(("SERVICE_INSTALLED", state["installed_on"]))
            if state["active_recurring"] and not old.get("active_recurring"):
                events.append(("RECURRING_SERVICE_STARTED", state["contract_signed_at"] or state["installed_on"]))
            if state["maintenance_status"] == "DUE" and (
                    old.get("maintenance_status") != "DUE" or
                    old.get("maintenance_due_on") != state["maintenance_due_on"]):
                events.append(("MAINTENANCE_DUE", state["maintenance_due_on"]))
            if (old.get("maintenance_status") == "DUE" and state["maintenance_status"] == "CURRENT"
                    and state["last_service_on"] != old.get("last_service_on")
                    and state["last_service_on"] and state["last_service_on"] >= old["maintenance_due_on"]):
                events.append(("MAINTENANCE_COMPLETED", state["last_service_on"]))
            if state["renewal_status"] in {"DUE", "OVERDUE"} and (
                    old.get("renewal_status") not in {"DUE", "OVERDUE"} or
                    old.get("renewal_on") != state["renewal_on"]):
                events.append(("RENEWAL_DUE", state["renewal_on"]))
            if state["renewal_status"] == "OVERDUE" and old.get("renewal_status") != "OVERDUE":
                events.append(("RENEWAL_OVERDUE", state["renewal_on"]))
            if (old.get("renewal_status") in {"DUE", "OVERDUE"}
                    and state["renewal_status"] == "MONITOR" and state["renewal_on"]
                    and state["renewal_on"] > old["renewal_on"]
                    and state["contract_signed_at"] != old.get("contract_signed_at")
                    and state["contract_signed_at"]):
                events.append(("RENEWED", state["contract_signed_at"]))
            for kind, evidence in events:
                proof = json.dumps([sid, kind, evidence, row["account_id"]], separators=(",", ":"))
                digest = hashlib.sha256(proof.encode()).hexdigest()
                event_id = "OB-L-" + digest[:24].upper()
                cur = db.execute("INSERT OR IGNORE INTO service_events VALUES (?,?,?,?,?,?,1)",
                                 (event_id, kind, sid, row["account_id"],
                                  clock.astimezone(timezone.utc).isoformat(), digest))
                inserted += cur.rowcount
            db.execute("INSERT INTO service_state(service_id,state_json) VALUES (?,?) "
                       "ON CONFLICT(service_id) DO UPDATE SET state_json=excluded.state_json",
                       (sid, json.dumps(state, sort_keys=True)))
        total = db.execute("SELECT count(*) FROM service_events").fetchone()[0]
        db.commit()
    return {"added": inserted, "total": total, "service_count": len(rows)}
