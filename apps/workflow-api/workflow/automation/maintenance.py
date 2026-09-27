from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .models import WorkflowDefinition, utc_now_iso
from .store import AutomationStore


_TERMINAL_STATUSES = {
    "completed",
    "partial",
    "failed",
    "dead_letter",
    "human_action_required",
}


class AutomationMaintenance:
    """Explicit bounded maintenance operations for Phase 3 execution control."""

    def __init__(self, store: AutomationStore) -> None:
        self.store = store

    @staticmethod
    def _validate_reason(reason: str) -> str:
        value = str(reason or "").strip()
        if not 8 <= len(value) <= 500:
            raise ValueError("maintenance reason must be 8-500 characters")
        return value

    def cleanup_terminal_claims(
        self,
        *,
        retention_days: int = 30,
        limit: int = 100,
        actor: str = "automation-maintenance",
        reason: str = "bounded terminal claim retention cleanup",
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Delete only old claims attached to already-terminal runs.

        Active, unresolved, queued, claimed, and running work is never selected.
        Failure history, run history, step history, and audit records are retained.
        """
        if not isinstance(retention_days, int) or isinstance(retention_days, bool) or not 1 <= retention_days <= 3650:
            raise ValueError("retention_days must be 1-3650")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("cleanup limit must be 1-1000")
        checked = now or datetime.now(timezone.utc)
        if checked.tzinfo is None:
            raise ValueError("cleanup clock must be timezone-aware")
        checked = checked.astimezone(timezone.utc)
        cutoff = (checked - timedelta(days=retention_days)).isoformat().replace("+00:00", "Z")
        safe_reason = self._validate_reason(reason)

        with self.store._lock, self.store._connect() as conn:  # package-internal maintenance boundary
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT c.run_id FROM automation_run_claims c "
                "JOIN automation_runs r ON r.run_id=c.run_id "
                "WHERE r.status IN ('completed','partial','failed','dead_letter','human_action_required') "
                "AND r.finished_at IS NOT NULL AND r.finished_at<=? "
                "ORDER BY r.finished_at,c.run_id LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in rows]
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                conn.execute(
                    f"DELETE FROM automation_run_claims WHERE run_id IN ({placeholders})",
                    run_ids,
                )
                conn.execute(
                    "INSERT INTO automation_audit(at,category,action,actor,success,metadata_json) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        utc_now_iso(),
                        "maintenance",
                        "terminal_claims_cleaned",
                        actor,
                        1,
                        json.dumps(
                            {
                                "count": len(run_ids),
                                "retention_days": retention_days,
                                "reason": safe_reason,
                            },
                            separators=(",", ":"),
                        ),
                    ),
                )
        return {"deleted_claims": len(run_ids)}

    def redrive(
        self,
        run_id: str,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, str]:
        """Create a new queued run only from explicitly redrive-safe evidence.

        The previous run remains immutable.  Human-review or ambiguous work is
        never redriven.  The exact queued workflow definition snapshot must be
        present; current workflow configuration is never substituted.
        """
        if not re.fullmatch(r"[0-9a-f]{32}", str(run_id or "")):
            raise ValueError("invalid run id")
        safe_actor = str(actor or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", safe_actor):
            raise ValueError("invalid redrive actor")
        safe_reason = self._validate_reason(reason)

        with self.store._lock, self.store._connect() as conn:  # package-internal execution-control boundary
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT run_id,workflow_id,event_id,correlation_id,status,context_json "
                "FROM automation_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise LookupError("automation run not found")
            if run["status"] not in {"failed", "dead_letter"}:
                raise ValueError("run status is not eligible for controlled redrive")

            failure = conn.execute(
                "SELECT category,reason_code,redrive_permitted,human_required "
                "FROM automation_run_failures WHERE run_id=? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if failure is None or not bool(failure["redrive_permitted"]):
                raise ValueError("latest failure does not permit redrive")
            if bool(failure["human_required"]) or failure["category"] in {
                "ambiguous_external",
                "authentication_expired",
                "unknown",
            }:
                raise ValueError("failure requires reconciliation and cannot be redriven")

            context = json.loads(run["context_json"] or "{}")
            queued_definition = context.get("queued_definition")
            if not isinstance(queued_definition, dict):
                raise ValueError("exact queued workflow definition snapshot is unavailable")
            definition = WorkflowDefinition.model_validate(queued_definition)
            if definition.id != run["workflow_id"]:
                raise ValueError("queued workflow snapshot identity mismatch")

            event = conn.execute(
                "SELECT event_type,source,occurred_at,correlation_id,depth,payload_json "
                "FROM automation_events WHERE event_id=?",
                (run["event_id"],),
            ).fetchone()
            if event is None:
                raise RuntimeError("original event is unavailable")

            new_event_id = uuid4().hex
            new_run_id = uuid4().hex
            now = utc_now_iso()
            correlation_id = str(run["correlation_id"] or event["correlation_id"] or new_event_id)
            idempotency_key = f"redrive:{run_id}:{new_run_id}"

            conn.execute(
                "INSERT INTO automation_events(event_id,event_type,source,occurred_at,correlation_id,"
                "causation_id,idempotency_key,depth,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    new_event_id,
                    event["event_type"],
                    event["source"],
                    event["occurred_at"],
                    correlation_id,
                    run["event_id"],
                    idempotency_key,
                    int(event["depth"]),
                    event["payload_json"],
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at,context_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    new_run_id,
                    definition.id,
                    new_event_id,
                    correlation_id,
                    "queued",
                    now,
                    json.dumps(
                        {
                            "queued_definition": definition.model_dump(by_alias=True),
                            "redrive_of_run_id": run_id,
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO automation_audit(at,category,action,actor,correlation_id,target,success,metadata_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    now,
                    "execution_control",
                    "controlled_redrive_created",
                    safe_actor,
                    correlation_id,
                    run_id,
                    1,
                    json.dumps(
                        {
                            "new_run_id": new_run_id,
                            "new_event_id": new_event_id,
                            "workflow_id": definition.id,
                            "workflow_version": definition.version,
                            "reason": safe_reason,
                            "failure_category": failure["category"],
                            "failure_reason_code": failure["reason_code"],
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                ),
            )

        return {
            "source_run_id": run_id,
            "run_id": new_run_id,
            "event_id": new_event_id,
            "status": "queued",
        }
