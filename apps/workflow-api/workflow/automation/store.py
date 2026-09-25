from __future__ import annotations

import json
import sqlite3
import threading
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

    def create_run(self, workflow_id: str, event_id: str, correlation_id: str) -> str:
        run_id = uuid4().hex
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) VALUES(?,?,?,?,?,?)",
                (run_id, workflow_id, event_id, correlation_id, "queued", now),
            )
        return run_id

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
