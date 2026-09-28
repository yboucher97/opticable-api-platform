"""Durable intake, normalization, routing and controlled event replay.

All cross-process invariants use SQLite transactions and unique constraints.
No provider handler runs inside these transactions.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from .event_schema import canonical, digest
from .models import AutomationEvent, WorkflowDefinition, utc_now_iso

if TYPE_CHECKING:
    from .store import AutomationStore

MAX_EVENT_BYTES = 1_048_576
METRICS = frozenset({
    "events_received", "events_accepted", "duplicates_suppressed", "dedupe_conflicts",
    "events_processed", "events_quarantined", "event_processor_failures", "replays",
    "workflow_runs", "workflow_duration_us", "provider_api_calls", "provider_failures",
    "provider_rate_limits", "provider_retries", "polling_cycles", "items_fetched",
    "sync_duration_us", "webhook_verification_failures", "webhook_rejections",
    "ai_invocations", "ai_input_tokens", "ai_output_tokens",
})
_SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|authorization|cookie|api[_-]?key|"
                         r"access[_-]?token|refresh[_-]?token|private[_-]?key|^token$)")
_SECRET_VALUE = re.compile(r"(?i)(Bearer\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----|\bsk-(?:proj-)?[A-Za-z0-9_-]{12,})")


class EventConflict(ValueError):
    pass


def redact(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> Any:
    budget = budget if budget is not None else [20_000]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise ValueError("event structure exceeds bounds")
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if _SECRET_KEY.search(str(k)) else
                redact(v, depth=depth + 1, budget=budget) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, depth=depth + 1, budget=budget) for v in value]
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return "[REDACTED]"
    return value


def safe_event(event: AutomationEvent) -> AutomationEvent:
    raw = event.model_dump()
    if len(canonical(raw).encode()) > MAX_EVENT_BYTES:
        raise ValueError("event exceeds size bound")
    raw["payload"] = redact(raw["payload"])
    allowed = {"delivery_id", "channel_id", "resource_id", "message_number", "server_time",
               "raw_sha256", "stream", "notification_type", "operation", "module"}
    raw["provider_evidence"] = redact({k: v for k, v in event.provider_evidence.items() if k in allowed})
    if len(canonical(raw["provider_evidence"]).encode()) > 8192:
        raise ValueError("event evidence exceeds size bound")
    raw["correlation_id"] = event.correlation_id or event.event_id
    return AutomationEvent.model_validate(raw)


def count(conn: sqlite3.Connection, provider: str, metric: str, value: int = 1,
          *, day: str | None = None) -> None:
    if metric not in METRICS or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", provider):
        raise ValueError("invalid usage dimension")
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10**15:
        raise ValueError("invalid usage value")
    known = conn.execute("SELECT 1 FROM automation_usage_daily WHERE provider=? LIMIT 1", (provider,)).fetchone()
    if not known and conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT provider FROM automation_usage_daily LIMIT 64)").fetchone()[0] >= 64:
        provider = "other"
    conn.execute("INSERT INTO automation_usage_daily VALUES(?,?,?,?) "
                 "ON CONFLICT(day,provider,metric) DO UPDATE SET value=value+excluded.value",
                 (day or utc_now_iso()[:10], provider, metric, value))


class EventLedger:
    def __init__(self, store: AutomationStore) -> None:
        self.store = store

    @staticmethod
    def _history(conn: sqlite3.Connection, event_id: str, action: str, category: str | None = None) -> None:
        conn.execute("INSERT INTO automation_event_history(event_id,at,action,category) VALUES(?,?,?,?)",
                     (event_id, utc_now_iso(), action, category))

    @staticmethod
    def _audit(conn: sqlite3.Connection, event_id: str, action: str, actor: str,
               metadata: dict[str, Any]) -> None:
        conn.execute("INSERT INTO automation_audit(at,category,action,actor,target,success,metadata_json) "
                     "VALUES(?,'event_control',?,?,?,?,?)",
                     (utc_now_iso(), action, actor, event_id, int(action not in {"replay_denied", "sync_failed"}), canonical(metadata)))

    def _capture(self, conn: sqlite3.Connection, event: AutomationEvent, *,
                 legacy_identity: bool = False, replay_of: str | None = None,
                 root_event_id: str | None = None) -> tuple[bool, str, str]:
        event = safe_event(event)
        if event.idempotency_key and (event.provider_event_id or event.dedupe_identity):
            raise ValueError("provider dedupe must be separate from internal idempotency")
        content_hash = digest({"event_type": event.event_type, "event_version": event.event_version,
                               "payload": event.payload, "subject_type": event.subject_type,
                               "subject_id": event.subject_id, "provider_timestamp": event.provider_timestamp,
                               "evidence": event.provider_evidence})
        identity = ("provider:" + digest(event.provider_event_id) if event.provider_event_id else
                    "dedupe:" + digest(event.dedupe_identity) if event.dedupe_identity else
                    "event:" + event.event_id if legacy_identity else "content:" + content_hash)
        count(conn, event.source, "events_received")
        existing = conn.execute("SELECT e.event_id,e.correlation_id,l.content_hash FROM automation_events e "
                                "JOIN automation_event_ledger l ON l.event_id=e.event_id WHERE e.event_id=?",
                                (event.event_id,)).fetchone()
        if event.idempotency_key and existing is None:
            existing = conn.execute("SELECT e.event_id,e.correlation_id,l.content_hash FROM automation_events e "
                                    "JOIN automation_event_ledger l ON l.event_id=e.event_id "
                                    "WHERE e.idempotency_key=?", (event.idempotency_key,)).fetchone()
        # A signed raw body digest is an additional replay barrier: delivery headers
        # are not signed by GitHub. Changing a delivery ID cannot bypass this key.
        identities = [identity]
        body_hash = event.provider_evidence.get("raw_sha256")
        if body_hash is not None:
            if not isinstance(body_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", body_hash):
                raise ValueError("invalid raw body digest")
            identities.append("body:" + body_hash)
        if existing is None:
            placeholders = ",".join("?" for _ in identities)
            existing = conn.execute(
                "SELECT e.event_id,e.correlation_id,l.content_hash FROM automation_event_dedupe d "
                "JOIN automation_events e ON e.event_id=d.event_id "
                "JOIN automation_event_ledger l ON l.event_id=e.event_id "
                f"WHERE d.source=? AND d.source_account=? AND d.identity IN ({placeholders}) LIMIT 1",
                (event.source, event.source_account, *identities)).fetchone()
        if existing is not None:
            # Existing Phase 3 idempotency identities intentionally ignore content
            # differences. Provider identities require identical immutable content.
            if (not legacy_identity or event.provider_event_id or event.dedupe_identity) and existing["content_hash"] != content_hash:
                raise EventConflict("provider event identity has conflicting content")
            now = utc_now_iso()
            conn.execute("UPDATE automation_event_processing SET last_seen_at=?,duplicate_count=duplicate_count+1 "
                         "WHERE event_id=?", (now, existing["event_id"]))
            count(conn, event.source, "duplicates_suppressed")
            return False, existing["event_id"], existing["correlation_id"]
        if event.causation_id:
            ancestor = event.causation_id
            for _ in range(33):
                if ancestor == event.event_id:
                    raise ValueError("circular event causation")
                parent = conn.execute("SELECT causation_id FROM automation_events WHERE event_id=?", (ancestor,)).fetchone()
                if parent is None or not parent[0]:
                    break
                ancestor = parent[0]
            else:
                raise ValueError("event lineage exceeds bounds")
        now = utc_now_iso()
        conn.execute("INSERT INTO automation_events VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (event.event_id, event.event_type, event.source, event.occurred_at,
                      event.correlation_id, event.causation_id, event.idempotency_key, event.depth,
                      canonical(event.payload), now))
        conn.execute("INSERT INTO automation_event_ledger VALUES(?,?,?,?,?,?,?,?,?)",
                     (event.event_id, event.source_account, event.provider_event_id, identity, content_hash,
                      canonical(event.model_dump()), now, replay_of, root_event_id or event.event_id))
        for dedupe_key in identities:
            conn.execute("INSERT INTO automation_event_dedupe VALUES(?,?,?,?)",
                         (event.source, event.source_account, dedupe_key, event.event_id))
        conn.execute("INSERT INTO automation_event_processing(event_id,status,first_seen_at,last_seen_at,updated_at) "
                     "VALUES(?,'accepted',?,?,?)", (event.event_id, now, now, now))
        self._history(conn, event.event_id, "accepted")
        count(conn, event.source, "events_accepted")
        return True, event.event_id, event.correlation_id or event.event_id

    def capture(self, event: AutomationEvent, *, legacy_identity: bool = False) -> tuple[bool, str, str]:
        try:
            with self.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                return self._capture(conn, event, legacy_identity=legacy_identity)
        except EventConflict:
            self.record_usage(event.source, "dedupe_conflicts")
            raise

    def _route(self, conn: sqlite3.Connection, event_id: str) -> list[tuple[str, WorkflowDefinition]]:
        row = conn.execute("SELECT l.*,p.status,p.attempts FROM automation_event_ledger l "
                           "JOIN automation_event_processing p USING(event_id) WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise LookupError("event not found")
        if row["status"] in {"routed", "quarantined"}:
            return []
        event = AutomationEvent.model_validate(json.loads(row["envelope_json"]))
        conn.execute("UPDATE automation_event_processing SET attempts=MIN(3,attempts+1) WHERE event_id=?", (event_id,))
        if event.event_version != 1:
            self._quarantine(conn, event_id, event.source, "unsupported_schema")
            return []
        if '[REDACTED]' in canonical(event.payload):
            self._quarantine(conn, event_id, event.source, "sensitive_payload_requires_review")
            return []
        normalized = event.model_dump()
        conn.execute("UPDATE automation_event_processing SET status='normalized',normalized_json=?,updated_at=? "
                     "WHERE event_id=?", (canonical(normalized), utc_now_iso(), event_id))
        self._history(conn, event_id, "normalized")
        matches: list[WorkflowDefinition] = []
        for candidate in conn.execute("SELECT definition_json FROM automation_workflows WHERE enabled=1 ORDER BY workflow_id"):
            definition = WorkflowDefinition.model_validate(json.loads(candidate[0]))
            if event.event_type not in definition.trigger.event_types and "*" not in definition.trigger.event_types:
                continue
            if definition.trigger.sources and event.source not in definition.trigger.sources:
                continue
            previous = conn.execute("SELECT run_id FROM automation_event_routes WHERE root_event_id=? AND workflow_id=?",
                                    (row["root_event_id"], definition.id)).fetchone()
            if previous is None:
                # Phase 3's low-level create_run path and controlled run redrive
                # must also fence event replay, even if a route record is absent.
                prior_run = conn.execute("SELECT r.run_id,r.event_id FROM automation_runs r "
                    "JOIN automation_event_ledger l USING(event_id) WHERE l.root_event_id=? AND r.workflow_id=? "
                    "ORDER BY r.created_at,r.run_id LIMIT 1", (row["root_event_id"], definition.id)).fetchone()
                if prior_run:
                    conn.execute("INSERT INTO automation_event_routes VALUES(?,?,?,?)",
                                 (row["root_event_id"], definition.id, prior_run["event_id"], prior_run["run_id"]))
                    previous = prior_run
            if previous is not None:
                self._history(conn, event_id, "route_suppressed", "existing_workflow_route")
                continue
            if row["replay_of"] and any(step.action not in {"core.set", "core.noop"} for step in definition.steps):
                self._quarantine(conn, event_id, event.source, "replay_external_route_requires_review")
                return []
            matches.append(definition)
        runs: list[tuple[str, WorkflowDefinition]] = []
        for definition in matches:
            run_id = uuid4().hex
            conn.execute("INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at,context_json) "
                         "VALUES(?,?,?,?,'queued',?,?)", (run_id, definition.id, event_id, event.correlation_id,
                         utc_now_iso(), canonical({"queued_definition": definition.model_dump(by_alias=True)})))
            conn.execute("INSERT INTO automation_event_routes VALUES(?,?,?,?)",
                         (row["root_event_id"], definition.id, event_id, run_id))
            runs.append((run_id, definition))
            count(conn, event.source, "workflow_runs")
        conn.execute("UPDATE automation_event_processing SET status='routed',last_error=NULL,updated_at=? WHERE event_id=?",
                     (utc_now_iso(), event_id))
        self._history(conn, event_id, "routed")
        count(conn, event.source, "events_processed")
        if row["replay_of"]:
            self._audit(conn, event_id, "replay_outcome", "event-router", {"run_count": len(runs), "status": "routed"})
        return runs

    def ingest_and_route(self, event: AutomationEvent) -> tuple[bool, str, str, list[tuple[str, WorkflowDefinition]]]:
        try:
            with self.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                accepted, event_id, correlation = self._capture(conn, event, legacy_identity=True)
                runs = self._route(conn, event_id) if accepted else []
                return accepted, event_id, correlation, runs
        except EventConflict:
            self.record_usage(event.source, "dedupe_conflicts")
            raise

    def process(self, event_id: str) -> list[tuple[str, WorkflowDefinition]]:
        try:
            with self.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                return self._route(conn, event_id)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            # Roll back ALL routing work. A separately committed bounded failure
            # counter prevents a deterministic poison event from looping forever.
            with self.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT p.status,p.attempts,e.source FROM automation_event_processing p "
                                   "JOIN automation_events e USING(event_id) WHERE event_id=?", (event_id,)).fetchone()
                if row and row["status"] not in {"routed", "quarantined"}:
                    attempts = min(3, row["attempts"] + 1)
                    conn.execute("UPDATE automation_event_processing SET attempts=?,last_error='processor_invalid',updated_at=? "
                                 "WHERE event_id=?", (attempts, utc_now_iso(), event_id))
                    self._history(conn, event_id, "processor_failed", "processor_invalid")
                    count(conn, row["source"], "event_processor_failures")
                    if attempts == 3:
                        self._quarantine(conn, event_id, row["source"], "poison_event")
            return []

    def process_pending(self, limit: int = 10) -> int:
        self._limit(limit)
        with self.store._connect() as conn:
            ids = [row[0] for row in conn.execute("SELECT event_id FROM automation_event_processing "
                    "WHERE status IN ('accepted','normalized') ORDER BY updated_at,event_id LIMIT ?", (limit,))]
        for event_id in ids:
            self.process(event_id)
        return len(ids)

    def _quarantine(self, conn: sqlite3.Connection, event_id: str, source: str, category: str) -> None:
        conn.execute("UPDATE automation_event_processing SET status='quarantined',last_error=?,updated_at=? WHERE event_id=?",
                     (category, utc_now_iso(), event_id))
        self._history(conn, event_id, "quarantined", category)
        count(conn, source, "events_quarantined")
        self._audit(conn, event_id, "quarantined", "event-router", {"category": category})
        replay = conn.execute("SELECT replay_of FROM automation_event_ledger WHERE event_id=?", (event_id,)).fetchone()
        if replay and replay[0]:
            self._audit(conn, event_id, "replay_outcome", "event-router", {"status": "quarantined", "category": category})

    @staticmethod
    def _limit(limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("event query limit must be 1-100")

    def inspect(self, event_id: str) -> dict[str, Any] | None:
        with self.store._connect() as conn:
            row = conn.execute("SELECT l.*,p.status,p.attempts,p.last_error,p.normalized_json,p.first_seen_at,"
                               "p.last_seen_at,p.duplicate_count FROM automation_event_ledger l "
                               "JOIN automation_event_processing p USING(event_id) WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["envelope"] = json.loads(result.pop("envelope_json"))
            result["normalized"] = json.loads(result.pop("normalized_json") or "null")
            result["history"] = [dict(r) for r in conn.execute("SELECT * FROM automation_event_history WHERE event_id=? "
                                                             "ORDER BY id DESC LIMIT 100", (event_id,))]
            result["routes"] = [dict(r) for r in conn.execute("SELECT t.workflow_id,t.run_id,r.status FROM automation_event_routes t "
                "JOIN automation_runs r USING(run_id) WHERE t.root_event_id=? ORDER BY t.workflow_id LIMIT 100",
                (row["root_event_id"],))]
            return result

    def list_events(self, *, limit: int = 50, after: str | None = None,
                    start: str | None = None, end: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        self._limit(limit)
        if start and end:
            beginning = datetime.fromisoformat(start.replace("Z", "+00:00"))
            ending = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if beginning.tzinfo is None or ending.tzinfo is None or beginning > ending:
                raise ValueError("invalid event time window")
        conditions, params = [], []
        if after is not None:
            conditions.append("l.event_id>?")
            params.append(after)
        for op, value in ((">=", start), ("<=", end)):
            if value is not None:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("query timestamp must include timezone")
                conditions.append(f"l.received_at{op}?")
                params.append(parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
        if status is not None:
            if status not in {"accepted", "normalized", "routed", "quarantined"}:
                raise ValueError("invalid event status")
            conditions.append("p.status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.store._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT l.event_id,l.received_at,l.replay_of,p.status,p.last_error "
                "FROM automation_event_ledger l JOIN automation_event_processing p USING(event_id)" + where +
                " ORDER BY l.event_id LIMIT ?", (*params, limit))]

    def replay(self, event_id: str, *, request_key: str, actor: str, reason: str) -> dict[str, Any]:
        try:
            return self._replay(event_id, request_key=request_key, actor=actor, reason=reason)
        except (LookupError, ValueError):
            if re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", actor) and 1 <= len(event_id) <= 128:
                with self.store._connect() as conn:
                    self._audit(conn, event_id, "replay_denied", actor, {"category": "ineligible_replay"})
            raise

    def _replay(self, event_id: str, *, request_key: str, actor: str, reason: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", actor) or not 8 <= len(reason.strip()) <= 500:
            raise ValueError("replay requires an actor and 8-500 character reason")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", request_key):
            raise ValueError("invalid replay request key")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT original_event_id,replay_event_id FROM automation_event_replays WHERE request_key=?",
                                    (request_key,)).fetchone()
            if previous:
                if previous["original_event_id"] != event_id:
                    raise ValueError("replay key is already bound to another event")
                return {"event_id": previous["replay_event_id"], "duplicate": True}
            row = conn.execute("SELECT l.*,p.status FROM automation_event_ledger l JOIN automation_event_processing p USING(event_id) "
                               "WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise LookupError("event not found")
            if row["replay_of"]:
                raise ValueError("replay of replay is prohibited")
            if row["status"] not in {"routed", "quarantined"}:
                raise ValueError("event must finish processing before replay")
            unsafe = conn.execute("SELECT 1 FROM automation_runs r JOIN automation_event_ledger l USING(event_id) "
                "WHERE l.root_event_id=? AND (r.status IN ('queued','claimed','running','human_action_required') "
                "OR EXISTS(SELECT 1 FROM automation_run_failures f WHERE f.run_id=r.run_id AND "
                "(f.category='ambiguous_external' OR f.human_required=1))) LIMIT 1", (row["root_event_id"],)).fetchone()
            if unsafe:
                raise ValueError("source event has unresolved or ambiguous execution; replay denied")
            original = AutomationEvent.model_validate(json.loads(row["envelope_json"]))
            replay_id = uuid4().hex
            event = original.model_copy(update={"event_id": replay_id, "causation_id": event_id,
                "idempotency_key": None, "provider_event_id": None,
                "dedupe_identity": "replay:" + request_key, "provider_evidence": {}})
            self._capture(conn, event, replay_of=event_id, root_event_id=row["root_event_id"])
            conn.execute("INSERT INTO automation_event_replays VALUES(?,?,?,?,?,?)",
                         (request_key, event_id, replay_id, actor, redact(reason.strip()), utc_now_iso()))
            self._audit(conn, replay_id, "replay_initiated", actor, {"original_event_id": event_id,
                                                                   "reason": redact(reason.strip())})
            count(conn, original.source, "replays")
            return {"event_id": replay_id, "duplicate": False}

    def record_usage(self, provider: str, metric: str, value: int = 1) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count(conn, provider, metric, value)

    def usage(self, days: int = 30) -> list[dict[str, Any]]:
        if not 1 <= days <= 365:
            raise ValueError("usage window must be 1-365 days")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        with self.store._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT provider,metric,SUM(value) value FROM automation_usage_daily "
                                                  "WHERE day>=? GROUP BY provider,metric ORDER BY provider,metric LIMIT 1000", (cutoff,))]

    def cleanup(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Immutable event evidence, dedupe tombstones, route guards and replay
            # audit are never automatically removed. Processing history is capped.
            deleted = conn.execute("DELETE FROM automation_usage_daily WHERE rowid IN "
                                   "(SELECT rowid FROM automation_usage_daily WHERE day<? LIMIT 1000)", (cutoff,)).rowcount
            deleted += conn.execute("DELETE FROM automation_event_history WHERE id IN "
                "(SELECT h.id FROM automation_event_history h JOIN automation_event_processing p USING(event_id) "
                "WHERE p.status IN ('routed','quarantined') AND h.id < "
                "COALESCE((SELECT id FROM automation_event_history x WHERE x.event_id=h.event_id "
                "ORDER BY id DESC LIMIT 1 OFFSET 19),0) LIMIT 1000)").rowcount
            deleted += conn.execute("DELETE FROM automation_audit WHERE id IN "
                "(SELECT id FROM automation_audit WHERE category='event_control' AND action IN "
                "('sync_page_committed','sync_failed') AND at<? LIMIT 1000)", (cutoff,)).rowcount
            return deleted

    def health(self) -> dict[str, Any]:
        with self.store._connect() as conn:
            counts = {r[0]: r[1] for r in conn.execute("SELECT status,COUNT(*) FROM automation_event_processing GROUP BY status")}
            oldest = conn.execute("SELECT MIN(first_seen_at) FROM automation_event_processing "
                                  "WHERE status IN ('accepted','normalized')").fetchone()[0]
            sync = [dict(r) for r in conn.execute("SELECT provider,source_account,stream,mode,status,revision,"
                "failures,updated_at,last_success_at,last_error,next_attempt_at FROM automation_sync_checkpoints "
                "ORDER BY provider,source_account,stream,mode LIMIT 100")]
            now = datetime.now(timezone.utc)
            age = lambda stamp: max(0, int((now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds())) if stamp else None
            for checkpoint in sync:
                checkpoint["cursor_age_seconds"] = age(checkpoint["last_success_at"] or checkpoint["updated_at"])
            return {"statuses": counts, "backlog": counts.get("accepted", 0) + counts.get("normalized", 0),
                    "oldest_unprocessed_at": oldest, "oldest_unprocessed_age_seconds": age(oldest),
                    "quarantined": counts.get("quarantined", 0),
                    "sync_checkpoints": sync, "usage": self.usage(1)}
