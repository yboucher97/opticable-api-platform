from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import AutomationEvent, WorkflowDefinition, utc_now_iso


class AutomationStore:
    """Durable local store with a schema that can later be migrated to Postgres."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
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

                CREATE TABLE IF NOT EXISTS automation_run_claims (
                    run_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL UNIQUE,
                    claimed_at TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    action_started INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_automation_run_claims_expiry
                    ON automation_run_claims(lease_expires_at);

                CREATE TABLE IF NOT EXISTS automation_run_failures (
                    run_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    attempt_id TEXT,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id)
                );
                """
            )

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
        correlation_id = event.correlation_id or event.event_id
        with self._lock, self._connect() as conn:
            if event.idempotency_key:
                existing = conn.execute(
                    "SELECT event_id,correlation_id FROM automation_events WHERE idempotency_key=?",
                    (event.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return False, str(existing["event_id"]), str(existing["correlation_id"])
            try:
                conn.execute(
                    """
                    INSERT INTO automation_events(
                        event_id,event_type,source,occurred_at,correlation_id,causation_id,
                        idempotency_key,depth,payload_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        event.source,
                        event.occurred_at,
                        correlation_id,
                        event.causation_id,
                        event.idempotency_key,
                        event.depth,
                        json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False),
                        utc_now_iso(),
                    ),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT event_id,correlation_id FROM automation_events WHERE event_id=?",
                    (event.event_id,),
                ).fetchone()
                if existing is None:
                    raise
                return False, str(existing["event_id"]), str(existing["correlation_id"])
        return True, event.event_id, correlation_id

    def ingest_event_and_runs(
        self, event: AutomationEvent
    ) -> tuple[bool, str, str, list[tuple[str, WorkflowDefinition]]]:
        """Commit the event and every matching queued run in one SQLite transaction.

        This does not execute or replay a run. A crash after commit leaves a
        visible queued run for explicit recovery, rather than an orphan event.
        """
        correlation_id = event.correlation_id or event.event_id
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = None
            if event.idempotency_key:
                existing = conn.execute(
                    "SELECT event_id,correlation_id FROM automation_events WHERE idempotency_key=?",
                    (event.idempotency_key,),
                ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT event_id,correlation_id FROM automation_events WHERE event_id=?",
                    (event.event_id,),
                ).fetchone()
            if existing is not None:
                return False, str(existing["event_id"]), str(existing["correlation_id"]), []

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

            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO automation_events(
                    event_id,event_type,source,occurred_at,correlation_id,causation_id,
                    idempotency_key,depth,payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (event.event_id, event.event_type, event.source, event.occurred_at,
                 correlation_id, event.causation_id, event.idempotency_key, event.depth,
                 json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False), now),
            )
            runs: list[tuple[str, WorkflowDefinition]] = []
            for definition in matches:
                run_id = uuid4().hex
                conn.execute(
                    "INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (run_id, definition.id, event.event_id, correlation_id, "queued", now),
                )
                runs.append((run_id, definition))
        return True, event.event_id, correlation_id, runs

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

    def claim_run(self, run_id: str, worker_id: str, *, lease_seconds: int = 60,
                  now: datetime | None = None) -> str | None:
        """Atomically claim queued work. The returned attempt token fences later actions."""
        self._validate_lease(worker_id, lease_seconds)
        checked = self._claim_time(now)
        claimed_at = self._claim_iso(checked)
        expires_at = self._claim_iso(checked + timedelta(seconds=lease_seconds))
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
                             attempt: int, now: datetime | None = None) -> int | None:
        """Persist a pre-action marker before any handler call; fail closed on stale tokens."""
        checked_at = self._claim_iso(self._claim_time(now))
        if not step_id or not action or not 1 <= attempt <= 5:
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
            conn.execute("UPDATE automation_run_claims SET action_started=1 WHERE run_id=?", (run_id,))
            conn.execute("UPDATE automation_runs SET status='running',started_at=COALESCE(started_at,?) WHERE run_id=?",
                         (checked_at, run_id))
            cursor = conn.execute(
                "INSERT INTO automation_run_steps(run_id,step_id,action,attempt,status,started_at) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, step_id, action, attempt, "started", checked_at),
            )
            self._claim_audit(conn, "action_started", claim["worker_id"], run_id, attempt_id)
        return int(cursor.lastrowid)

    def renew_claim(self, run_id: str, attempt_id: str, *, lease_seconds: int = 60,
                    now: datetime | None = None) -> bool:
        """Extend only an unexpired active claim held by the same attempt token."""
        checked = self._claim_time(now)
        checked_at = self._claim_iso(checked)
        expires_at = self._claim_iso(checked + timedelta(seconds=lease_seconds))
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
                                now: datetime | None = None) -> bool:
        """Record an observed handler result; never clear human-review state."""
        finished_at = self._claim_iso(self._claim_time(now))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                "SELECT c.worker_id FROM automation_run_claims c JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE c.run_id=? AND c.attempt_id=? AND c.lease_expires_at>? AND r.status='running'",
                (run_id, attempt_id, finished_at),
            ).fetchone()
            if claim is None:
                return False
            cursor = conn.execute(
                "UPDATE automation_run_steps SET status=?,finished_at=?,error=?,result_json=? "
                "WHERE id=? AND run_id=? AND status='started'",
                ("completed" if succeeded else "failed", finished_at, error[:1000] if error else None,
                 json.dumps(result, separators=(",", ":"), ensure_ascii=False) if result is not None else None,
                 marker_id, run_id),
            )
            if cursor.rowcount != 1:
                return False
            self._claim_audit(conn, "action_completed" if succeeded else "action_failed",
                              claim["worker_id"], run_id, attempt_id, success=succeeded)
        return True

    def finish_claim(self, run_id: str, attempt_id: str, *, status: str,
                     error: str | None = None, failure_category: str | None = None,
                     reason_code: str | None = None, now: datetime | None = None) -> bool:
        """Persist a terminal result only when no action remains unconfirmed."""
        if status not in {"completed", "partial", "failed", "dead_letter"}:
            raise ValueError("invalid terminal claim status")
        if status in {"failed", "dead_letter"}:
            if not isinstance(failure_category, str) or failure_category not in {
                    "rate_limited", "network_timeout", "provider_unavailable",
                    "authentication_expired", "permanent", "unknown", "ambiguous_external"}:
                raise ValueError("invalid failure category")
            if not isinstance(reason_code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason_code):
                raise ValueError("invalid failure reason code")
        elif failure_category is not None or reason_code is not None:
            raise ValueError("success or partial result cannot carry a failure category")
        finished_at = self._claim_iso(self._claim_time(now))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                "SELECT c.worker_id FROM automation_run_claims c JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE c.run_id=? AND c.attempt_id=? AND c.lease_expires_at>? AND r.status='running'",
                (run_id, attempt_id, finished_at),
            ).fetchone()
            if claim is None or conn.execute(
                "SELECT 1 FROM automation_run_steps WHERE run_id=? AND status='started'",
                (run_id,),
            ).fetchone():
                return False
            conn.execute(
                "UPDATE automation_runs SET status=?,finished_at=?,error=? WHERE run_id=?",
                (status, finished_at, error[:1000] if error else None, run_id),
            )
            if failure_category is not None:
                conn.execute(
                    "INSERT INTO automation_run_failures(run_id,category,reason_code,attempt_id,recorded_at) "
                    "VALUES(?,?,?,?,?)",
                    (run_id, failure_category, reason_code, attempt_id, finished_at),
                )
            self._claim_audit(conn, "run_" + status, claim["worker_id"], run_id, attempt_id,
                              success=status == "completed")
        return True

    def recover_expired_claims(self, *, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
        """Requeue only claims with no action marker; isolate all ambiguous work."""
        if not 1 <= limit <= 100:
            raise ValueError("recovery limit must be 1–100")
        checked_at = self._claim_iso(self._claim_time(now))
        result = {"requeued": 0, "human_action_required": 0}
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            claims = conn.execute(
                "SELECT c.run_id,c.worker_id,c.attempt_id,c.action_started,r.status "
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
                        (checked_at, "Claim expired after an action may have started; reconcile external effects before redrive.",
                         claim["run_id"]),
                    )
                    conn.execute(
                        "INSERT INTO automation_run_failures(run_id,category,reason_code,attempt_id,recorded_at) "
                        "VALUES(?,?,?,?,?)",
                        (claim["run_id"], "ambiguous_external", "lease_expired_after_action",
                         claim["attempt_id"], checked_at),
                    )
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
                "SELECT step_id,action,attempt,status,started_at,finished_at,error,result_json FROM automation_run_steps WHERE run_id=? ORDER BY id",
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
                SELECT r.run_id,r.workflow_id,r.status,r.created_at,r.finished_at,
                       f.category AS failure_category,f.reason_code,
                       COUNT(s.id) AS step_attempts,MAX(s.started_at) AS last_attempt_at
                FROM automation_runs r
                LEFT JOIN automation_run_steps s ON s.run_id=r.run_id
                LEFT JOIN automation_run_failures f ON f.run_id=r.run_id
                WHERE r.status IN ('failed','dead_letter','human_action_required')
                GROUP BY r.run_id
                ORDER BY r.created_at DESC,r.run_id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def execution_health(self, *, now: datetime | None = None) -> dict[str, int]:
        """Return bounded aggregate state; never claim or replay a run."""
        checked_at = self._claim_time(now)
        queued_cutoff = self._claim_iso(checked_at - timedelta(minutes=15))
        running_cutoff = self._claim_iso(checked_at - timedelta(hours=1))
        now_iso = self._claim_iso(checked_at)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued,
                    SUM(CASE WHEN status='claimed' THEN 1 ELSE 0 END) AS claimed,
                    SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial,
                    SUM(CASE WHEN status='dead_letter' THEN 1 ELSE 0 END) AS dead_letter,
                    SUM(CASE WHEN status='human_action_required' THEN 1 ELSE 0 END) AS human_action_required,
                    SUM(CASE WHEN status='queued' AND created_at<=? THEN 1 ELSE 0 END) AS stale_queued,
                    SUM(CASE WHEN status='running' AND (started_at IS NULL OR started_at<=?) THEN 1 ELSE 0 END) AS stale_running,
                    SUM(CASE WHEN status IN ('claimed','running') AND c.lease_expires_at<=? THEN 1 ELSE 0 END) AS expired_leases,
                    MIN(CASE WHEN status='queued' THEN created_at END) AS oldest_queued_at,
                    MIN(CASE WHEN status='running' THEN COALESCE(started_at,created_at) END) AS oldest_running_at
                FROM automation_runs r LEFT JOIN automation_run_claims c ON c.run_id=r.run_id
                """,
                (queued_cutoff, running_cutoff, now_iso),
            ).fetchone()
        result = {key: int(row[key] or 0) for key in
                  ("total", "queued", "claimed", "running", "failed", "partial", "dead_letter",
                   "human_action_required", "stale_queued", "stale_running", "expired_leases")}
        for name in ("queued", "running"):
            value = row[f"oldest_{name}_at"]
            if value:
                started = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
