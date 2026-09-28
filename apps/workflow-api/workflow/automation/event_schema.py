"""Explicit, transactional V1 -> V2 event migration. No live database repair."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from .models import AutomationEvent

SCHEMA_VERSION = 2

DDL = (
    """CREATE TABLE automation_event_ledger (
        event_id TEXT PRIMARY KEY REFERENCES automation_events(event_id),
        source_account TEXT NOT NULL,
        provider_event_id TEXT,
        dedupe_identity TEXT NOT NULL,
        content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
        envelope_json TEXT NOT NULL,
        received_at TEXT NOT NULL CHECK(received_at GLOB '????-??-??T??:??:??.??????Z'),
        replay_of TEXT REFERENCES automation_event_ledger(event_id),
        root_event_id TEXT NOT NULL REFERENCES automation_events(event_id)
    )""",
    """CREATE TABLE automation_event_dedupe (
        source TEXT NOT NULL, source_account TEXT NOT NULL, identity TEXT NOT NULL,
        event_id TEXT NOT NULL REFERENCES automation_event_ledger(event_id),
        PRIMARY KEY(source,source_account,identity)
    )""",
    """CREATE TABLE automation_event_processing (
        event_id TEXT PRIMARY KEY REFERENCES automation_event_ledger(event_id),
        status TEXT NOT NULL CHECK(status IN ('accepted','normalized','routed','quarantined')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
        last_error TEXT, normalized_json TEXT,
        first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        duplicate_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX idx_event_processing_pending ON automation_event_processing(status,updated_at,event_id)",
    "CREATE INDEX idx_event_ledger_received ON automation_event_ledger(received_at,event_id)",
    "CREATE INDEX idx_event_ledger_root ON automation_event_ledger(root_event_id,event_id)",
    """CREATE TABLE automation_event_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL REFERENCES automation_event_ledger(event_id),
        at TEXT NOT NULL, action TEXT NOT NULL, category TEXT
    )""",
    "CREATE INDEX idx_event_history_event ON automation_event_history(event_id,id)",
    """CREATE TABLE automation_event_routes (
        root_event_id TEXT NOT NULL REFERENCES automation_events(event_id),
        workflow_id TEXT NOT NULL REFERENCES automation_workflows(workflow_id),
        event_id TEXT NOT NULL REFERENCES automation_events(event_id),
        run_id TEXT NOT NULL REFERENCES automation_runs(run_id),
        PRIMARY KEY(root_event_id,workflow_id)
    )""",
    """CREATE TABLE automation_event_replays (
        request_key TEXT PRIMARY KEY, original_event_id TEXT NOT NULL REFERENCES automation_event_ledger(event_id),
        replay_event_id TEXT NOT NULL UNIQUE REFERENCES automation_event_ledger(event_id),
        actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
    """CREATE TABLE automation_sync_checkpoints (
        provider TEXT NOT NULL, source_account TEXT NOT NULL, stream TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('incremental','backfill')),
        cursor TEXT, page_token TEXT, revision INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK(status IN ('idle','syncing','backoff','resync_required','failed')),
        lease_token TEXT, lease_expires_at INTEGER,
        failures INTEGER NOT NULL DEFAULT 0,
        next_attempt_at INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
        notifications INTEGER NOT NULL DEFAULT 0,
        last_success_at TEXT, last_error TEXT,
        PRIMARY KEY(provider,source_account,stream,mode)
    )""",
    """CREATE TABLE automation_usage_daily (
        day TEXT NOT NULL, provider TEXT NOT NULL, metric TEXT NOT NULL,
        value INTEGER NOT NULL CHECK(value>=0), PRIMARY KEY(day,provider,metric)
    )""",
    "CREATE INDEX idx_usage_provider ON automation_usage_daily(provider)",
    """CREATE TRIGGER event_identity_immutable BEFORE UPDATE ON automation_events
        BEGIN SELECT RAISE(ABORT,'immutable event'); END""",
    """CREATE TRIGGER event_evidence_immutable BEFORE UPDATE ON automation_event_ledger
        BEGIN SELECT RAISE(ABORT,'immutable event evidence'); END""",
    """CREATE TRIGGER event_evidence_retained BEFORE DELETE ON automation_event_ledger
        BEGIN SELECT RAISE(ABORT,'event retention requires explicit policy'); END""",
    """CREATE TRIGGER event_identity_retained BEFORE DELETE ON automation_events
        BEGIN SELECT RAISE(ABORT,'event retention requires explicit policy'); END""",
    """CREATE TRIGGER event_dedupe_immutable BEFORE UPDATE ON automation_event_dedupe
        BEGIN SELECT RAISE(ABORT,'immutable event dedupe'); END""",
    """CREATE TRIGGER event_dedupe_retained BEFORE DELETE ON automation_event_dedupe
        BEGIN SELECT RAISE(ABORT,'event dedupe retention requires explicit policy'); END""",
)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def migrate_events(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    required = {
        "automation_events": {"event_id", "event_type", "source", "occurred_at", "correlation_id",
                              "causation_id", "idempotency_key", "depth", "payload_json", "created_at"},
        "automation_runs": {"run_id", "workflow_id", "event_id", "context_json", "status"},
        "automation_workflows": {"workflow_id", "definition_json", "enabled"},
    }
    for table, columns in required.items():
        actual = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not columns <= actual:
            raise RuntimeError(f"event migration legacy schema mismatch: {table}")
    if version == SCHEMA_VERSION:
        objects = {row[0]: row[1] for row in conn.execute("SELECT name,sql FROM sqlite_master")}
        for statement in DDL:
            name = re.match(r"CREATE (?:TABLE|INDEX|TRIGGER) ([a-z_]+)", statement)[1]
            normalized = lambda sql: re.sub(r"\s+", " ", sql.strip()).lower()
            if name not in objects or normalized(objects[name] or "") != normalized(statement):
                raise RuntimeError(f"incomplete event schema version 2: {name}")
        return
    if version != 1:
        raise RuntimeError(f"event migration requires version 1, got {version}")
    for statement in DDL:
        conn.execute(statement)
    # Preserve legacy event bytes and timestamps exactly. Never reroute history.
    rows = conn.execute("SELECT * FROM automation_events")
    for row in rows:
        envelope = {key: row[key] for key in ("event_id", "event_type", "source", "occurred_at",
                                             "correlation_id", "causation_id", "idempotency_key", "depth")}
        original_payload = json.loads(row["payload_json"])
        from .events import redact
        envelope["payload"] = redact(original_payload)
        if envelope["payload"] != original_payload and conn.execute(
                "SELECT 1 FROM automation_runs WHERE event_id=? AND status IN ('queued','claimed','running') LIMIT 1",
                (row["event_id"],)).fetchone():
            raise RuntimeError("legacy sensitive unresolved event requires review before migration")
        received_at = AutomationEvent.normalize_timestamp(row["created_at"])
        identity = "legacy:" + digest(row["idempotency_key"] or row["event_id"])
        conn.execute("INSERT INTO automation_event_ledger VALUES(?,?,?,?,?,?,?,?,?)",
                     (row["event_id"], "", None, identity, digest(original_payload), canonical(envelope),
                      received_at, None, row["event_id"]))
        conn.execute("INSERT INTO automation_event_dedupe VALUES(?,?,?,?)",
                     (row["source"], "", identity, row["event_id"]))
        conn.execute("INSERT INTO automation_event_processing(event_id,status,first_seen_at,last_seen_at,updated_at) "
                     "VALUES(?,'routed',?,?,?)", (row["event_id"], received_at, received_at, received_at))
    conn.execute("INSERT INTO automation_event_routes SELECT event_id,workflow_id,event_id,MIN(run_id) "
                 "FROM automation_runs GROUP BY event_id,workflow_id")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("event migration found broken foreign keys")
    conn.execute("PRAGMA user_version=2")
