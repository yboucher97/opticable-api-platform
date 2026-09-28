from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import AutomationEvent, WorkflowDefinition, utc_now_iso

_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class AutomationStore:
    """Durable local store with a schema that can later be migrated to Postgres."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            # Inspect the version before WAL configuration or any schema statement.
            # Even a connection opened solely to reject a future schema must not
            # change database metadata.
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(f"unknown automation schema version: {version}")
            self._enable_wal(conn)
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            return conn
        except BaseException:
            conn.close()
            raise

    @staticmethod
    def _enable_wal(conn: sqlite3.Connection) -> None:
        # Changing journal mode can return SQLITE_BUSY immediately despite the
        # connection busy timeout during concurrent fresh startup. Retry only
        # this connection setup, never a migration transaction or action handler.
        deadline = time.monotonic() + 30
        while True:
            try:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                if mode != "wal":
                    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if mode != "wal":
                    raise RuntimeError("automation database requires WAL")
                return
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", 0) or 0
                if (code & 0xff) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _initialize(self) -> None:
        with self._connect() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS automation_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    depth INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_automation_events_type ON automation_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_automation_events_correlation ON automation_events(correlation_id);

                CREATE TABLE IF NOT EXISTS automation_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    definition_json TEXT NOT NULL,
                    source_path TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automation_runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    context_json TEXT,
                    FOREIGN KEY(workflow_id) REFERENCES automation_workflows(workflow_id),
                    FOREIGN KEY(event_id) REFERENCES automation_events(event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_automation_runs_event ON automation_runs(event_id);
                CREATE INDEX IF NOT EXISTS idx_automation_runs_workflow ON automation_runs(workflow_id);

                CREATE TABLE IF NOT EXISTS automation_run_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error TEXT,
                    result_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS automation_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    correlation_id TEXT,
                    target TEXT,
                    success INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_automation_audit_correlation ON automation_audit(correlation_id);

                """
                )
        self._migrate_execution_control()
        from .event_schema import migrate_events
        with self._connect() as conn:
            migrate_events(conn)

    def _migrate_execution_control(self) -> None:
        """Add only new execution metadata in one repeat-safe SQLite transaction."""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version in (1, 2):
                required = {
                    "automation_run_steps": {"action_identity", "provider_operation_id"},
                    "automation_run_claims": {"run_id", "worker_id", "attempt_id", "claimed_at", "lease_expires_at"},
                    "automation_run_failures": {"id", "run_id", "category", "reason_code", "recorded_at"},
                }
                complete = all(
                    columns <= {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                    for table, columns in required.items()
                )
                indexes = {row["name"] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
                if complete and {"idx_automation_run_steps_run", "idx_automation_run_claims_expiry",
                                 "idx_automation_run_failures_run"} <= indexes:
                    self._require_numeric_claim_clock(conn)
                    return
                if version == 2:
                    raise RuntimeError("incomplete execution schema version 2")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(automation_run_steps)")}
            if "action_identity" not in columns:
                conn.execute("ALTER TABLE automation_run_steps ADD COLUMN action_identity TEXT")
            if "provider_operation_id" not in columns:
                conn.execute("ALTER TABLE automation_run_steps ADD COLUMN provider_operation_id TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_run_steps_run "
                         "ON automation_run_steps(run_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS automation_run_claims (
                    run_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE,
                    claimed_at INTEGER NOT NULL,
                    lease_expires_at INTEGER NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_run_claims_expiry "
                         "ON automation_run_claims(lease_expires_at)")
            failure_columns = {row["name"] for row in conn.execute("PRAGMA table_info(automation_run_failures)")}
            if failure_columns and "id" not in failure_columns:
                conn.execute("ALTER TABLE automation_run_failures RENAME TO automation_run_failures_legacy")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS automation_run_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT,
                    attempt_id TEXT,
                    category TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    diagnostic_json TEXT NOT NULL DEFAULT '{}',
                    terminal_state TEXT,
                    redrive_permitted INTEGER NOT NULL DEFAULT 0,
                    human_required INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                )
            """)
            if failure_columns and "id" not in failure_columns:
                conn.execute(
                    "INSERT INTO automation_run_failures(run_id,attempt_id,category,reason_code,recorded_at,"
                    "terminal_state,human_required) "
                    "SELECT f.run_id,f.attempt_id,f.category,f.reason_code,f.recorded_at,r.status,"
                    "CASE WHEN r.status='human_action_required' THEN 1 ELSE 0 END "
                    "FROM automation_run_failures_legacy f JOIN automation_runs r ON r.run_id=f.run_id"
                )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_run_failures_run "
                         "ON automation_run_failures(run_id,id)")
            expected = {
                "automation_run_steps": {"run_id", "step_id", "attempt", "action_identity", "provider_operation_id"},
                "automation_run_claims": {"run_id", "worker_id", "attempt_id", "claimed_at", "lease_expires_at"},
                "automation_run_failures": {"id", "run_id", "attempt_id", "category", "reason_code",
                                            "recorded_at", "terminal_state", "redrive_permitted", "human_required"},
            }
            for table, required in expected.items():
                actual = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not required <= actual:
                    raise RuntimeError(f"automation migration schema mismatch: {table}")
            self._require_numeric_claim_clock(conn)
            conn.execute("PRAGMA user_version=1")

    @staticmethod
    def _require_numeric_claim_clock(conn: sqlite3.Connection) -> None:
        types = {row["name"]: row["type"].upper()
                 for row in conn.execute("PRAGMA table_info(automation_run_claims)")}
        if types.get("claimed_at") != "INTEGER" or types.get("lease_expires_at") != "INTEGER":
            raise RuntimeError("automation claim clock schema must use integer microseconds")

    def upsert_workflow(self, definition: WorkflowDefinition, source_path: str | None = None) -> None:
        payload = definition.model_dump(by_alias=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_workflows(workflow_id,name,version,enabled,definition_json,source_path,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    name=excluded.name,
                    version=excluded.version,
                    enabled=excluded.enabled,
                    definition_json=excluded.definition_json,
                    source_path=excluded.source_path,
                    updated_at=excluded.updated_at
                """,
                (
                    definition.id,
                    definition.name,
                    definition.version,
                    int(definition.enabled),
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    source_path,
                    utc_now_iso(),
                ),
            )

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workflow_id,name,version,enabled,source_path,updated_at FROM automation_workflows ORDER BY workflow_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT definition_json FROM automation_workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
        if row is None:
            return None
        return WorkflowDefinition.model_validate(json.loads(row["definition_json"]))

    def matching_workflows(self, event: AutomationEvent) -> list[WorkflowDefinition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT definition_json FROM automation_workflows WHERE enabled=1 ORDER BY workflow_id"
            ).fetchall()
        matches: list[WorkflowDefinition] = []
        for row in rows:
            definition = WorkflowDefinition.model_validate(json.loads(row["definition_json"]))
            if event.event_type not in definition.trigger.event_types and "*" not in definition.trigger.event_types:
                continue
            if definition.trigger.sources and event.source not in definition.trigger.sources:
                continue
            matches.append(definition)
        return matches

    def ingest_event(self, event: AutomationEvent) -> tuple[bool, str, str]:
        from .events import EventLedger
        return EventLedger(self).capture(event, legacy_identity=True)

    def ingest_event_and_runs(
        self, event: AutomationEvent
    ) -> tuple[bool, str, str, list[tuple[str, WorkflowDefinition]]]:
        from .events import EventLedger
        return EventLedger(self).ingest_and_route(event)

    def queued_envelopes(self, limit: int = 10) -> list[tuple[str, WorkflowDefinition, AutomationEvent]]:
        """Read only runs with an immutable queued definition snapshot for recovery."""
        if not 1 <= limit <= 100:
            raise ValueError("queue scan limit must be 1–100")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT r.run_id,r.context_json,l.envelope_json "
                "FROM automation_runs r JOIN automation_event_ledger l ON l.event_id=r.event_id "
                "WHERE r.status='queued' AND r.context_json IS NOT NULL "
                "ORDER BY r.created_at,r.run_id LIMIT ?", (limit,),
            ).fetchall()
        result = []
        for row in rows:
            snapshot = json.loads(row["context_json"])
            if "queued_definition" not in snapshot:
                continue
            definition = WorkflowDefinition.model_validate(snapshot["queued_definition"])
            event = AutomationEvent.model_validate(json.loads(row["envelope_json"]))
            result.append((row["run_id"], definition, event))
        return result

    def create_run(self, workflow_id: str, event_id: str, correlation_id: str) -> str:
        run_id = uuid4().hex
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) VALUES(?,?,?,?,?,?)",
                (run_id, workflow_id, event_id, correlation_id, "queued", now),
            )
        return run_id

    @staticmethod
    def _claim_time(now: datetime | None) -> datetime:
        checked = now or datetime.now(timezone.utc)
        if checked.tzinfo is None:
            raise ValueError("claim clock must be timezone-aware")
        return checked.astimezone(timezone.utc)

    @staticmethod
    def _claim_iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _claim_epoch_us(value: datetime) -> int:
        """Exact UTC microseconds; equality with expiry means the lease has expired."""
        delta = value - _UTC_EPOCH
        return ((delta.days * 86400 + delta.seconds) * 1_000_000
                + delta.microseconds)

    @staticmethod
    def _validate_lease(worker_id: str, lease_seconds: int) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", worker_id):
            raise ValueError("invalid worker identity")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 300:
            raise ValueError("claim lease must be 5–300 seconds")

    @staticmethod
    def _claim_audit(conn: sqlite3.Connection, action: str, worker_id: str, run_id: str,
                     attempt_id: str, *, success: bool = True) -> None:
        conn.execute(
            "INSERT INTO automation_audit(at,category,action,actor,target,success,metadata_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (utc_now_iso(), "run_claim", action, worker_id, run_id, int(success),
             json.dumps({"attempt_id": attempt_id}, separators=(",", ":"))),
        )

    @staticmethod
    def _insert_failure(conn: sqlite3.Connection, *, run_id: str, step_id: str | None,
                        attempt_id: str, category: str, reason_code: str, recorded_at: str,
                        diagnostic: dict[str, int | float] | None = None,
                        terminal_state: str | None = None, redrive_permitted: bool = False,
                        human_required: bool = False) -> None:
        if not isinstance(category, str) or category not in {
                "rate_limited", "network_timeout", "provider_unavailable",
                "authentication_expired", "permanent", "unknown", "ambiguous_external"}:
            raise ValueError("invalid failure category")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_code):
            raise ValueError("invalid failure reason code")
        safe = diagnostic or {}
        if set(safe) - {"http_status", "retry_delay_seconds"}:
            raise ValueError("unsafe diagnostic field")
        if "http_status" in safe and (not isinstance(safe["http_status"], int)
                                       or isinstance(safe["http_status"], bool)
                                       or not 100 <= safe["http_status"] <= 599):
            raise ValueError("invalid diagnostic HTTP status")
        if "retry_delay_seconds" in safe and (not isinstance(safe["retry_delay_seconds"], (int, float))
                                               or isinstance(safe["retry_delay_seconds"], bool)
                                               or not 0 <= safe["retry_delay_seconds"] <= 300):
            raise ValueError("invalid diagnostic retry delay")
        conn.execute(
            "INSERT INTO automation_run_failures(run_id,step_id,attempt_id,category,reason_code,"
            "recorded_at,diagnostic_json,terminal_state,redrive_permitted,human_required) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, step_id, attempt_id, category, reason_code, recorded_at,
             json.dumps(safe, separators=(",", ":")), terminal_state,
             int(redrive_permitted), int(human_required)),
        )

    def claim_run(self, run_id: str, worker_id: str, *, lease_seconds: int = 60,
                  now: datetime | None = None) -> str | None:
        """Atomically claim queued work. The returned attempt token fences later actions."""
        self._validate_lease(worker_id, lease_seconds)
        checked = self._claim_time(now)
        claimed_at = self._claim_epoch_us(checked)
        expires_at = self._claim_epoch_us(checked + timedelta(seconds=lease_seconds))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row["status"] != "queued":
                return None
            if conn.execute("SELECT 1 FROM automation_run_claims WHERE run_id=?", (run_id,)).fetchone():
                return None
            attempt_id = uuid4().hex
            conn.execute(
                "INSERT INTO automation_run_claims(run_id,worker_id,attempt_id,claimed_at,lease_expires_at) "
                "VALUES(?,?,?,?,?)",
                (run_id, worker_id, attempt_id, claimed_at, expires_at),
            )
            conn.execute("UPDATE automation_runs SET status='claimed' WHERE run_id=? AND status='queued'", (run_id,))
            self._claim_audit(conn, "claimed", worker_id, run_id, attempt_id)
        return attempt_id

    def begin_claimed_action(self, run_id: str, attempt_id: str, *, step_id: str, action: str,
                             action_identity: str, attempt: int, now: datetime | None = None) -> int | None:
        """Persist a pre-action marker before any handler call; fail closed on stale tokens."""
        checked = self._claim_time(now)
        checked_at = self._claim_epoch_us(checked)
        if (not step_id or not action or not 1 <= attempt <= 5
                or not re.fullmatch(r"[0-9a-f]{64}", action_identity)):
            raise ValueError("invalid step attempt")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                "SELECT worker_id,lease_expires_at FROM automation_run_claims WHERE run_id=? AND attempt_id=?",
                (run_id, attempt_id),
            ).fetchone()
            run = conn.execute("SELECT status FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if (claim is None or run is None or run["status"] not in {"claimed", "running"}
                    or claim["lease_expires_at"] <= checked_at):
                return None
            if conn.execute(
                "SELECT 1 FROM automation_run_steps WHERE run_id=? AND step_id=? AND attempt=?",
                (run_id, step_id, attempt),
            ).fetchone():
                return None
            if conn.execute(
                "SELECT 1 FROM automation_run_steps WHERE run_id=? AND status='started'",
                (run_id,),
            ).fetchone():
                return None
            if conn.execute(
                "SELECT 1 FROM automation_run_steps WHERE run_id=? AND action_identity=? AND status='completed'",
                (run_id, action_identity),
            ).fetchone():
                return None
            conn.execute("UPDATE automation_runs SET status='running',started_at=COALESCE(started_at,?) WHERE run_id=?",
                         (self._claim_iso(checked), run_id))
            cursor = conn.execute(
                "INSERT INTO automation_run_steps(run_id,step_id,action,action_identity,attempt,status,started_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (run_id, step_id, action, action_identity, attempt, "started", self._claim_iso(checked)),
            )
            self._claim_audit(conn, "action_started", claim["worker_id"], run_id, attempt_id)
            from .events import count
            provider = action.split(".")[0]
            if provider in {"zoho", "google", "github", "cloudflare", "ovh", "windsor", "apollo", "ai"}:
                count(conn, provider, "ai_invocations" if provider == "ai" else "provider_api_calls")
                if attempt > 1:
                    count(conn, provider, "provider_retries")
        return int(cursor.lastrowid)

    def renew_claim(self, run_id: str, attempt_id: str, *, lease_seconds: int = 60,
                    now: datetime | None = None) -> bool:
        """Extend only an unexpired active claim held by the same attempt token."""
        checked = self._claim_time(now)
        checked_at = self._claim_epoch_us(checked)
        expires_at = self._claim_epoch_us(checked + timedelta(seconds=lease_seconds))
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 300:
            raise ValueError("claim lease must be 5–300 seconds")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT c.worker_id,c.lease_expires_at FROM automation_run_claims c "
                "JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE c.run_id=? AND c.attempt_id=? AND c.lease_expires_at>? "
                "AND r.status IN ('claimed','running')",
                (run_id, attempt_id, checked_at),
            ).fetchone()
            if row is None:
                return False
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (max(expires_at, row["lease_expires_at"]), run_id))
            self._claim_audit(conn, "lease_renewed", row["worker_id"], run_id, attempt_id)
        return True

    def complete_claimed_action(self, run_id: str, attempt_id: str, marker_id: int, *,
                                succeeded: bool, result: Any = None, error: str | None = None,
                                provider_operation_id: str | None = None,
                                failure_category: str | None = None, reason_code: str | None = None,
                                diagnostic: dict[str, int | float] | None = None,
                                final_context: dict[str, Any] | None = None,
                                now: datetime | None = None) -> bool:
        """Record an observed result, atomically finishing the final successful step."""
        checked = self._claim_time(now)
        finished_at = self._claim_iso(checked)
        finished_at_us = self._claim_epoch_us(checked)
        if provider_operation_id is not None and (
                not isinstance(provider_operation_id, str)
                or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", provider_operation_id)):
            raise ValueError("invalid provider operation ID")
        if succeeded and (failure_category is not None or reason_code is not None or diagnostic):
            raise ValueError("successful action cannot carry failure evidence")
        if not succeeded and (failure_category is None or reason_code is None):
            raise ValueError("failed action requires failure evidence")
        if final_context is not None and not succeeded:
            raise ValueError("a failed action cannot complete a run")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                "SELECT c.worker_id FROM automation_run_claims c JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE c.run_id=? AND c.attempt_id=? AND c.lease_expires_at>? AND r.status='running'",
                (run_id, attempt_id, finished_at_us),
            ).fetchone()
            if claim is None:
                return False
            cursor = conn.execute(
                "UPDATE automation_run_steps SET status=?,finished_at=?,error=?,result_json=?,provider_operation_id=? "
                "WHERE id=? AND run_id=? AND status='started'",
                ("completed" if succeeded else "failed", finished_at, error[:1000] if error else None,
                 json.dumps(result, separators=(",", ":"), ensure_ascii=False) if result is not None else None,
                 provider_operation_id, marker_id, run_id),
            )
            if cursor.rowcount != 1:
                return False
            from .events import count
            action_row = conn.execute("SELECT action FROM automation_run_steps WHERE id=?", (marker_id,)).fetchone()
            provider = action_row["action"].split(".")[0]
            if not succeeded and provider in {"zoho", "google", "github", "cloudflare", "ovh", "windsor", "apollo", "ai"}:
                count(conn, provider, "provider_failures")
                if failure_category == "rate_limited":
                    count(conn, provider, "provider_rate_limits")
            if succeeded and provider == "ai" and isinstance(result, dict):
                raw = result.get("raw") or {}
                usage = raw.get("usage") or raw.get("usageMetadata") or {} if isinstance(raw, dict) else {}
                if isinstance(usage, dict):
                    for metric, keys in (("ai_input_tokens", ("input_tokens", "promptTokenCount")),
                                         ("ai_output_tokens", ("output_tokens", "candidatesTokenCount"))):
                        value = next((usage[k] for k in keys if k in usage), None)
                        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**9:
                            count(conn, "ai", metric, value)
            if not succeeded:
                step = conn.execute("SELECT step_id FROM automation_run_steps WHERE id=?", (marker_id,)).fetchone()
                self._insert_failure(conn, run_id=run_id, step_id=step["step_id"],
                                     attempt_id=attempt_id, category=failure_category,
                                     reason_code=reason_code, recorded_at=finished_at,
                                     diagnostic=diagnostic)
            if final_context is not None:
                conn.execute(
                    "UPDATE automation_runs SET status='completed',finished_at=?,error=NULL,context_json=? "
                    "WHERE run_id=? AND status='running'",
                    (finished_at, json.dumps(final_context, separators=(",", ":"), ensure_ascii=False), run_id),
                )
            self._claim_audit(conn, "action_completed" if succeeded else "action_failed",
                              claim["worker_id"], run_id, attempt_id, success=succeeded)
            if final_context is not None:
                self._claim_audit(conn, "run_completed", claim["worker_id"], run_id, attempt_id)
                duration = conn.execute("SELECT CAST(MAX(0,(julianday(finished_at)-julianday(started_at))*86400000000) AS INTEGER) "
                                        "FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()[0]
                count(conn, "internal", "workflow_duration_us", duration or 0)
        return True

    def finish_claim(self, run_id: str, attempt_id: str, *, status: str,
                     error: str | None = None, failure_category: str | None = None,
                     reason_code: str | None = None, redrive_permitted: bool = False,
                     human_required: bool = False, context: dict[str, Any] | None = None,
                     now: datetime | None = None) -> bool:
        """Persist a terminal result only when no action remains unconfirmed."""
        if status not in {"completed", "partial", "failed", "dead_letter", "human_action_required"}:
            raise ValueError("invalid terminal claim status")
        if status in {"failed", "dead_letter", "human_action_required"}:
            if not isinstance(failure_category, str) or failure_category not in {
                    "rate_limited", "network_timeout", "provider_unavailable",
                    "authentication_expired", "permanent", "unknown", "ambiguous_external"}:
                raise ValueError("invalid failure category")
            if not isinstance(reason_code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_code):
                raise ValueError("invalid failure reason code")
        elif failure_category is not None or reason_code is not None:
            raise ValueError("success or partial result cannot carry a failure category")
        if status == "human_action_required" and not human_required:
            raise ValueError("human review flag required")
        if status in {"completed", "partial"} and (redrive_permitted or human_required):
            raise ValueError("invalid success recovery flags")
        checked = self._claim_time(now)
        finished_at = self._claim_iso(checked)
        finished_at_us = self._claim_epoch_us(checked)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                "SELECT c.worker_id FROM automation_run_claims c JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE c.run_id=? AND c.attempt_id=? AND c.lease_expires_at>? AND r.status='running'",
                (run_id, attempt_id, finished_at_us),
            ).fetchone()
            if claim is None or conn.execute(
                "SELECT 1 FROM automation_run_steps WHERE run_id=? AND status='started'",
                (run_id,),
            ).fetchone():
                return False
            conn.execute(
                "UPDATE automation_runs SET status=?,finished_at=?,error=?,context_json=COALESCE(?,context_json) "
                "WHERE run_id=?",
                (status, finished_at, error[:1000] if error else None,
                 json.dumps(context, separators=(",", ":"), ensure_ascii=False) if context is not None else None,
                 run_id),
            )
            if failure_category is not None:
                self._insert_failure(conn, run_id=run_id, step_id=None, attempt_id=attempt_id,
                                     category=failure_category, reason_code=reason_code,
                                     recorded_at=finished_at, terminal_state=status,
                                     redrive_permitted=redrive_permitted, human_required=human_required)
            self._claim_audit(conn, "run_" + status, claim["worker_id"], run_id, attempt_id,
                              success=status == "completed")
        return True

    def recover_expired_claims(self, *, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
        """Requeue only claims with no action marker; isolate all ambiguous work."""
        if not 1 <= limit <= 100:
            raise ValueError("recovery limit must be 1–100")
        checked = self._claim_time(now)
        checked_at = self._claim_epoch_us(checked)
        checked_at_iso = self._claim_iso(checked)
        result = {"requeued": 0, "human_action_required": 0}
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claims = conn.execute(
                "SELECT c.run_id,c.worker_id,c.attempt_id,r.status,"
                "EXISTS(SELECT 1 FROM automation_run_steps s WHERE s.run_id=c.run_id) AS action_started "
                "FROM automation_run_claims c JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE c.lease_expires_at<=? AND r.status IN ('claimed','running') "
                "ORDER BY c.lease_expires_at,c.run_id LIMIT ?",
                (checked_at, limit),
            ).fetchall()
            for claim in claims:
                if claim["status"] == "claimed" and not claim["action_started"]:
                    conn.execute("UPDATE automation_runs SET status='queued',started_at=NULL WHERE run_id=?",
                                 (claim["run_id"],))
                    conn.execute("DELETE FROM automation_run_claims WHERE run_id=?", (claim["run_id"],))
                    action = "expired_before_action_requeued"
                    result["requeued"] += 1
                else:
                    conn.execute(
                        "UPDATE automation_runs SET status='human_action_required',finished_at=?,error=? WHERE run_id=?",
                        (checked_at_iso, "Claim expired after an action may have started; reconcile external effects before redrive.",
                         claim["run_id"]),
                    )
                    self._insert_failure(conn, run_id=claim["run_id"], step_id=None,
                                         attempt_id=claim["attempt_id"], category="ambiguous_external",
                                         reason_code="lease_expired_after_action", recorded_at=checked_at_iso,
                                         terminal_state="human_action_required", human_required=True)
                    action = "expired_ambiguous_escalated"
                    result["human_action_required"] += 1
                self._claim_audit(conn, action, claim["worker_id"], claim["run_id"], claim["attempt_id"],
                                  success=False)
        return result

    def set_run_status(self, run_id: str, status: str, *, error: str | None = None, context: dict[str, Any] | None = None) -> None:
        now = utc_now_iso()
        started_at = now if status == "running" else None
        finished_at = now if status in {"completed", "failed", "partial"} else None
        with self._connect() as conn:
            if status == "running":
                conn.execute(
                    "UPDATE automation_runs SET status=?,started_at=? WHERE run_id=?",
                    (status, started_at, run_id),
                )
            elif finished_at:
                conn.execute(
                    "UPDATE automation_runs SET status=?,finished_at=?,error=?,context_json=? WHERE run_id=?",
                    (
                        status,
                        finished_at,
                        error,
                        json.dumps(context or {}, separators=(",", ":"), ensure_ascii=False),
                        run_id,
                    ),
                )
            else:
                conn.execute("UPDATE automation_runs SET status=?,error=? WHERE run_id=?", (status, error, run_id))

    def append_step(self, *, run_id: str, step_id: str, action: str, attempt: int, status: str, started_at: str, error: str | None = None, result: Any = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_run_steps(run_id,step_id,action,attempt,status,started_at,finished_at,error,result_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    step_id,
                    action,
                    attempt,
                    status,
                    started_at,
                    utc_now_iso(),
                    error,
                    json.dumps(result, separators=(",", ":"), ensure_ascii=False) if result is not None else None,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            steps = conn.execute(
                "SELECT step_id,action,action_identity,attempt,status,started_at,finished_at,"
                "provider_operation_id,error,result_json FROM automation_run_steps WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        result = dict(row)
        if result.get("context_json"):
            result["context"] = json.loads(result.pop("context_json"))
        else:
            result.pop("context_json", None)
            result["context"] = None
        result["steps"] = []
        for step in steps:
            item = dict(step)
            if item.get("result_json"):
                item["result"] = json.loads(item.pop("result_json"))
            else:
                item.pop("result_json", None)
                item["result"] = None
            result["steps"].append(item)
        return result

    def run_exists(self, run_id: str) -> bool:
        """Check existence without loading a workflow snapshot or step results."""
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM automation_runs WHERE run_id=? LIMIT 1",
                                (run_id,)).fetchone() is not None

    def recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id,workflow_id,event_id,correlation_id,status,created_at,started_at,finished_at,error FROM automation_runs ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def failed_work(self, limit: int = 50) -> list[dict[str, Any]]:
        """Inspect terminal/reconciliation work without payloads or raw errors."""
        safe_limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH selected AS (
                    SELECT run_id,workflow_id,status,created_at,finished_at
                    FROM automation_runs
                    WHERE status IN ('failed','partial','dead_letter','human_action_required')
                    ORDER BY created_at DESC,run_id DESC LIMIT ?
                )
                SELECT r.run_id,r.workflow_id,r.status,r.created_at,r.finished_at,
                       f.category AS failure_category,f.reason_code,f.recorded_at AS failure_at,
                       f.redrive_permitted,f.human_required,
                       COUNT(s.id) AS step_attempts,MAX(s.started_at) AS last_attempt_at
                FROM selected r
                LEFT JOIN automation_run_steps s ON s.run_id=r.run_id
                LEFT JOIN automation_run_failures f ON f.id=(
                    SELECT MAX(last.id) FROM automation_run_failures last WHERE last.run_id=r.run_id)
                GROUP BY r.run_id
                ORDER BY r.created_at DESC,r.run_id DESC
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def failure_history(self, run_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return bounded, non-secret evidence for one run without raw exceptions."""
        if not 1 <= limit <= 100:
            raise ValueError("failure history limit must be 1–100")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,step_id,attempt_id,category,reason_code,recorded_at,diagnostic_json,"
                "terminal_state,redrive_permitted,human_required "
                "FROM automation_run_failures WHERE run_id=? ORDER BY id DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["diagnostic"] = json.loads(item.pop("diagnostic_json"))
            result.append(item)
        return result

    def execution_health(self, *, now: datetime | None = None) -> dict[str, int]:
        """Return bounded aggregate state; never claim or replay a run."""
        checked_at = self._claim_time(now)
        queued_cutoff = self._claim_iso(checked_at - timedelta(minutes=15))
        running_cutoff = self._claim_iso(checked_at - timedelta(hours=1))
        recent_cutoff = running_cutoff
        now_us = self._claim_epoch_us(checked_at)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued,
                    SUM(CASE WHEN status='claimed' THEN 1 ELSE 0 END) AS claimed,
                    SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial,
                    SUM(CASE WHEN status='dead_letter' THEN 1 ELSE 0 END) AS dead_letter,
                    SUM(CASE WHEN status='human_action_required' THEN 1 ELSE 0 END) AS human_action_required,
                    SUM(CASE WHEN status='queued' AND created_at<=? THEN 1 ELSE 0 END) AS stale_queued,
                    SUM(CASE WHEN status='running' AND (started_at IS NULL OR started_at<=?) THEN 1 ELSE 0 END) AS stale_running,
                    SUM(CASE WHEN status IN ('claimed','running') AND c.lease_expires_at<=? THEN 1 ELSE 0 END) AS expired_leases,
                    MIN(CASE WHEN status='queued' THEN created_at END) AS oldest_queued_at,
                    MIN(CASE WHEN status='running' THEN COALESCE(started_at,created_at) END) AS oldest_running_at,
                    MIN(CASE WHEN status IN ('claimed','running') THEN c.claimed_at END) AS oldest_claim_at
                FROM automation_runs r LEFT JOIN automation_run_claims c ON c.run_id=r.run_id
                """,
                (queued_cutoff, running_cutoff, now_us),
            ).fetchone()
            recent_failures = conn.execute(
                "SELECT COUNT(*) FROM automation_run_failures WHERE recorded_at>=?",
                (recent_cutoff,),
            ).fetchone()[0]
        result = {key: int(row[key] or 0) for key in
                  ("total", "queued", "claimed", "running", "completed", "failed", "partial", "dead_letter",
                   "human_action_required", "stale_queued", "stale_running", "expired_leases")}
        result["recent_failure_count"] = int(recent_failures)
        for name in ("queued", "running", "claim"):
            value = row[f"oldest_{name}_at"]
            if value:
                started = (_UTC_EPOCH + timedelta(microseconds=int(value)) if name == "claim"
                           else datetime.fromisoformat(value.replace("Z", "+00:00")))
                result[f"oldest_{name}_age_seconds"] = max(0, int((checked_at - started).total_seconds()))
            else:
                result[f"oldest_{name}_age_seconds"] = 0
        return result

    def audit(self, *, category: str, action: str, actor: str, success: bool, correlation_id: str | None = None, target: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO automation_audit(at,category,action,actor,correlation_id,target,success,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                (
                    utc_now_iso(), category, action, actor, correlation_id, target, int(success),
                    json.dumps(metadata or {}, separators=(",", ":"), ensure_ascii=False),
                ),
            )

    def recent_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,at,category,action,actor,correlation_id,target,success,metadata_json FROM automation_audit ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["success"] = bool(item["success"])
            item["metadata"] = json.loads(item.pop("metadata_json"))
            items.append(item)
        return items
