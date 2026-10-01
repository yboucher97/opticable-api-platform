"""Conservative Phase 12 business-action policy and durable Test Lab journal.

This boundary governs new Phase 12 actions. It does not grant legacy workflow
handlers new authority. CRM transport still requires its separate exact-call
grant; real CRM mutations and customer sends remain disabled here.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Callable, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
Ownership = Literal["TEST_ONLY", "PROTECTED", "REAL", "UNKNOWN"]
Choice = Literal["AUTO_EXECUTE", "APPROVAL_REQUIRED", "DENY", "DEFER", "RECONCILE"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
RISK = {
    "crm.read": "R0", "internal.observe": "R0", "internal.event": "R1",
    "local.folder.ensure": "R1", "crm.task.create": "R1",
    "crm.task.update": "R2", "crm.project.onboard": "R2",
    "crm.work.schedule": "R2", "crm.work.complete": "R2",
    "crm.service.update": "R2", "crm.lead.update": "R2",
    "email.draft.create": "R2", "email.send": "R3",
    "crm.lead.convert": "R3", "crm.merge": "R3",
    "crm.delete": "R3", "crm.bulk": "R3", "books.write": "R3",
    "financial.write": "R3", "provider.config.write": "R3",
    "infrastructure.write": "R3",
}
FORBIDDEN = frozenset({"crm.delete", "crm.bulk", "books.write", "financial.write",
                       "provider.config.write", "infrastructure.write"})
MUTATING = frozenset(x for x, tier in RISK.items() if tier != "R0")
_ID = re.compile(r"[0-9]{1,30}\Z")
_KEY = re.compile(r"[A-Za-z0-9._:-]{8,160}\Z")


def aware(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("Action time must be timezone-aware")
    return dt.astimezone(timezone.utc)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()).hexdigest()


def effect_summary(action: "Action") -> dict:
    """Only operator-safe, bounded fields; never journal email bodies or credentials."""
    permitted = {"Status", "purpose", "service_scope", "recipient", "subject", "body_hash"}
    return {key: str(value)[:160] for key, value in action.payload.items()
            if key in permitted and isinstance(value, (str, int, float, bool))}


def local_time(value: str | None) -> str | None:
    if not value:
        return None
    return aware(value).astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z")


@dataclass(frozen=True)
class Action:
    action_type: str
    target_module: str
    target_id: str
    request_key: str
    payload: dict
    expected_version: str | None = None
    expected_state: dict | None = None
    confidence: Confidence = "HIGH"
    provider: str = "zoho_crm"

    def __post_init__(self):
        if self.action_type not in RISK or not _KEY.fullmatch(self.request_key):
            raise ValueError("Unknown action or invalid replay identity")
        if self.target_id and not _ID.fullmatch(self.target_id):
            raise ValueError("Action target ID is invalid")
        if self.confidence not in {"HIGH", "MEDIUM", "LOW"}:
            raise ValueError("Action confidence is invalid")
        if not isinstance(self.payload, dict) or len(json.dumps(self.payload)) > 8192:
            raise ValueError("Action payload is absent or unbounded")
        if self.expected_version:
            aware(self.expected_version)

    @property
    def action_id(self) -> str:
        return sha256(("phase12-action-v1\0" + self.request_key).encode()).hexdigest()[:32]

    @property
    def payload_hash(self) -> str:
        return digest({"action": self.action_type, "module": self.target_module,
                       "target": self.target_id, "payload": self.payload,
                       "expected_version": self.expected_version,
                       "expected_state": self.expected_state, "provider": self.provider})


@dataclass(frozen=True)
class Policy:
    automatic_mutations: bool = False  # Production default and kill switch.
    auto_test_task: bool = False
    auto_test_project: bool = False
    auto_test_internal: bool = False
    auto_real_crm: bool = False
    auto_real_send: bool = False
    approved_test_send: bool = False

    @classmethod
    def from_environment(cls) -> "Policy":
        """Explicit opt-in for Test Lab automation; real mutations remain disabled."""
        enabled = lambda key: os.environ.get(key) == "1"
        return cls(automatic_mutations=enabled("OPTIBRAIN_BUSINESS_AUTO_WRITES"),
                   auto_test_task=enabled("OPTIBRAIN_AUTO_TEST_TASK"),
                   auto_test_project=enabled("OPTIBRAIN_AUTO_TEST_PROJECT"),
                   auto_test_internal=enabled("OPTIBRAIN_AUTO_TEST_INTERNAL"))


@dataclass(frozen=True)
class Decision:
    choice: Choice
    risk: str
    reason: str
    ownership: Ownership
    confidence: Confidence


def decide(action: Action, ownership: Ownership, policy: Policy) -> Decision:
    tier = RISK[action.action_type]
    def result(choice: Choice, reason: str) -> Decision:
        return Decision(choice, tier, reason, ownership, action.confidence)
    if ownership not in {"TEST_ONLY", "PROTECTED", "REAL", "UNKNOWN"}:
        return result("DENY", "invalid_target_classification")
    if action.action_type in FORBIDDEN:
        return result("DENY", "forbidden_business_action")
    if tier == "R0":
        return result("AUTO_EXECUTE", "read_only_observation")
    if ownership == "UNKNOWN":
        return result("DEFER", "target_ownership_unverified")
    if ownership == "PROTECTED":
        return result("DENY", "protected_baseline_read_only")
    if ownership == "REAL":
        return result("DENY", "real_business_mutations_disabled")
    if action.confidence != "HIGH":
        return result("DEFER", "identity_or_state_not_exact")
    if tier == "R3":
        return result("APPROVAL_REQUIRED", "consequential_test_action_needs_human")
    if not policy.automatic_mutations:
        return result("DEFER", "business_auto_write_kill_switch_off")
    enabled = ((action.action_type in {"internal.event", "local.folder.ensure"} and policy.auto_test_internal)
               or (action.action_type in {"crm.task.create", "crm.task.update"} and policy.auto_test_task)
               or (action.action_type == "crm.project.onboard" and policy.auto_test_project))
    if not enabled:
        return result("DEFER", "per_action_auto_flag_off")
    return result("AUTO_EXECUTE", "exact_owned_test_target")


def classify_crm_record(module: str, row: dict | None, *,
                        registered_test_ids: set[str], protected_ids: set[str]) -> Ownership:
    """Ownership requires registry membership plus live provider marker evidence."""
    identity = str((row or {}).get("id") or "")
    if not identity or not _ID.fullmatch(identity):
        return "UNKNOWN"
    if identity in protected_ids:
        return "PROTECTED"
    if identity in registered_test_ids:
        marker = ((row or {}).get("Subject") if module == "Tasks" else
                  (row or {}).get("Name") if module in {"Services", "Service_Locations", "Installations"} else
                  (row or {}).get("Description"))
        visible = str(marker or "").startswith("OPTIBRAIN TEST — PHASE ")
        flag = module in {"Tasks", "Installations", "Cases"} or row.get("OptiBrain_Test") is True
        return "TEST_ONLY" if visible and flag else "UNKNOWN"
    return "REAL"


class BusinessJournal:
    """SQLite journal with one-use approvals and crash-safe attempted markers."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS actions (
              action_id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
              action_type TEXT NOT NULL, target_module TEXT NOT NULL, target_id TEXT NOT NULL,
              ownership TEXT NOT NULL, risk TEXT NOT NULL, confidence TEXT NOT NULL,
              decision TEXT NOT NULL, reason TEXT NOT NULL, payload_hash TEXT NOT NULL,
              expected_version TEXT, provider TEXT NOT NULL, state TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0, provider_id TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS approvals (
              approval_id TEXT PRIMARY KEY, action_id TEXT NOT NULL,
              action_type TEXT NOT NULL, target_id TEXT NOT NULL,
              payload_hash TEXT NOT NULL, approver TEXT NOT NULL,
              issued_at TEXT NOT NULL, expires_at TEXT NOT NULL,
              state TEXT NOT NULL, consumed_at TEXT,
              FOREIGN KEY(action_id) REFERENCES actions(action_id));
            CREATE INDEX IF NOT EXISTS idx_phase12_actions_state ON actions(state,updated_at);
            CREATE INDEX IF NOT EXISTS idx_phase12_approvals_state ON approvals(state,expires_at);
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=DELETE")
            with db:
                yield db
        finally:
            db.close()

    def get(self, action_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
        return dict(row) if row else None

    def prepare(self, action: Action, decision: Decision) -> dict:
        now = utc_now()
        state = {"AUTO_EXECUTE": "proposed", "APPROVAL_REQUIRED": "approval_required",
                 "DENY": "denied", "DEFER": "deferred", "RECONCILE": "reconcile"}[decision.choice]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM actions WHERE action_id=?", (action.action_id,)).fetchone()
            if previous:
                if (previous["payload_hash"] != action.payload_hash or previous["action_type"] != action.action_type
                        or previous["target_id"] != action.target_id):
                    raise ValueError("Replay identity reused with changed action")
                return dict(previous)
            db.execute("""INSERT INTO actions(action_id,request_key,action_type,target_module,target_id,
                ownership,risk,confidence,decision,reason,payload_hash,expected_version,provider,
                state,created_at,updated_at,detail_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (action.action_id, action.request_key, action.action_type, action.target_module,
                 action.target_id, decision.ownership, decision.risk, decision.confidence,
                 decision.choice, decision.reason, action.payload_hash, action.expected_version,
                 action.provider, state, now, now,
                 json.dumps({"effect": effect_summary(action)}, separators=(",", ":"))))
        return self.get(action.action_id)

    def transition(self, action_id: str, *, from_states: tuple[str, ...], to: str,
                   provider_id: str | None = None, detail: dict | None = None,
                   attempt: bool = False) -> dict:
        if not from_states:
            raise ValueError("Expected state required")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
            if not row or row["state"] not in from_states:
                raise ValueError("Business action state changed or was already consumed")
            merged_detail = {**json.loads(row["detail_json"]), **(detail or {})}
            db.execute("UPDATE actions SET state=?,attempts=attempts+?,provider_id=COALESCE(?,provider_id),"
                       "detail_json=?,updated_at=? WHERE action_id=?",
                       (to, int(attempt), provider_id,
                        json.dumps(merged_detail, separators=(",", ":")), utc_now(), action_id))
        return self.get(action_id)

    def issue(self, action: Action, *, actor: str, expires_at: str,
              now: datetime | None = None) -> dict:
        return self.issue_by_id(action.action_id, action.payload_hash, actor=actor,
                                expires_at=expires_at, now=now)

    def issue_by_id(self, action_id: str, payload_hash: str, *, actor: str,
                    expires_at: str, now: datetime | None = None) -> dict:
        clock = aware(now or datetime.now(timezone.utc))
        expiry = aware(expires_at)
        if (not re.fullmatch(r"human:[A-Za-z0-9._:-]{1,128}", actor)
                or not clock < expiry <= clock + timedelta(hours=1)):
            raise ValueError("Exact human approval requires an expiry within one hour")
        entry = self.get(action_id)
        if (not entry or entry["state"] != "approval_required" or entry["ownership"] != "TEST_ONLY"
                or entry["payload_hash"] != payload_hash or entry["risk"] != "R3"):
            raise ValueError("Approval proposal is absent, changed, or ineligible")
        approval_id = uuid4().hex
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute("SELECT state,payload_hash FROM actions WHERE action_id=?", (action_id,)).fetchone()
            if not latest or latest["state"] != "approval_required" or latest["payload_hash"] != payload_hash:
                raise ValueError("Approval proposal changed")
            db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (approval_id, action_id, entry["action_type"], entry["target_id"],
                 payload_hash, actor, clock.isoformat(), expiry.isoformat(), "issued"))
        return {"approval_id": approval_id, "action_id": action_id,
                "expires_at": expiry.isoformat(), "state": "issued"}

    def claim_approval(self, approval_id: str, action: Action, *, actor: str,
                       now: datetime | None = None) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", approval_id): raise ValueError("Invalid approval ID")
        clock = aware(now or datetime.now(timezone.utc))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if (not row or row["state"] != "issued" or row["action_id"] != action.action_id
                    or row["action_type"] != action.action_type or row["target_id"] != action.target_id
                    or row["payload_hash"] != action.payload_hash or row["approver"] != actor
                    or not aware(row["issued_at"]) <= clock < aware(row["expires_at"])):
                raise ValueError("Approval expired, consumed, or binding changed")
            action_row = db.execute("SELECT state,payload_hash FROM actions WHERE action_id=?",
                                    (action.action_id,)).fetchone()
            if not action_row or action_row["state"] != "approval_required" or action_row["payload_hash"] != action.payload_hash:
                raise ValueError("Approval action is no longer eligible")
            db.execute("UPDATE approvals SET state='consuming',consumed_at=? WHERE approval_id=?",
                       (clock.isoformat(), approval_id))
            db.execute("UPDATE actions SET state='attempted',attempts=attempts+1,updated_at=? WHERE action_id=?",
                       (clock.isoformat(), action.action_id))
        return {"approval_id": approval_id, "action_id": action.action_id,
                "state": "consuming", "actor": actor}

    def finish_approval(self, approval_id: str, *, provider_id: str) -> None:
        if not provider_id:
            raise ValueError("Approval completion requires a verified provider result")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,action_id FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not row or row["state"] != "consuming":
                raise ValueError("Approval was not durably claimed")
            db.execute("UPDATE approvals SET state='consumed' WHERE approval_id=?", (approval_id,))
            changed = db.execute("UPDATE actions SET state='succeeded',provider_id=?,updated_at=?,"
                       "detail_json=? WHERE action_id=? AND state='attempted'",
                       (provider_id, utc_now(), '{"reconciliation":"exact_readback"}', row["action_id"]))
            if changed.rowcount != 1:
                raise ValueError("Approved action state changed")

    def close_approval(self, approval_id: str, *, state: str) -> None:
        if state not in {"stale", "reconcile"}:
            raise ValueError("Unsupported approval closure")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not row or row["state"] != "consuming":
                raise ValueError("Approval was not claimed")
            db.execute("UPDATE approvals SET state='consumed' WHERE approval_id=?", (approval_id,))

    def view(self, *, limit: int = 100) -> dict:
        safe = max(1, min(limit, 100))
        with self._db() as db:
            actions = [dict(r) for r in db.execute("SELECT * FROM actions ORDER BY updated_at DESC LIMIT ?", (safe,))]
            approvals = [dict(r) for r in db.execute("SELECT * FROM approvals ORDER BY issued_at DESC LIMIT ?", (safe,))]
            totals = {r["state"]: r["n"] for r in db.execute(
                "SELECT state,COUNT(*) AS n FROM actions GROUP BY state")}
        today = datetime.now(TORONTO).date()
        # SQLite string date is UTC; filter the bounded local-day interval precisely.
        start = datetime.combine(today, datetime.min.time(), tzinfo=TORONTO).astimezone(timezone.utc).isoformat()
        with self._db() as db:
            today_count = db.execute("SELECT COUNT(*) AS n FROM actions WHERE state='succeeded' "
                "AND risk!='R0' AND updated_at>=?", (start,)).fetchone()["n"]
        summary = {"auto_actions_today": today_count,
                   "waiting_approval": totals.get("approval_required", 0),
                   "exceptions": sum(totals.get(x, 0) for x in ("reconcile", "stale", "failed", "deferred")),
                   "denied": totals.get("denied", 0),
                   "unresolved": totals.get("reconcile", 0) + totals.get("failed", 0)}
        return {"summary": summary, "actions": actions, "approvals": approvals}


def dispatch(action: Action, *, ownership: Ownership, policy: Policy,
             journal: BusinessJournal, fresh: Callable[[], dict],
             execute: Callable[[], str], reconcile: Callable[[], str | None]) -> dict:
    """Execute once; uncertain provider results remain RECONCILE, never retried."""
    decision = decide(action, ownership, policy)
    row = journal.prepare(action, decision)
    if row["state"] != "proposed":
        return row
    if decision.risk == "R0":
        fresh()  # Read-only observer: no mutating callback or kill-switch dependency.
        return journal.transition(action.action_id, from_states=("proposed",), to="succeeded",
                                  detail={"reconciliation": "read_only_observation"})
    try:
        current = fresh()
        if (not isinstance(current, dict) or current.get("ownership") != "TEST_ONLY"
                or str(current.get("id")) != action.target_id):
            return journal.transition(action.action_id, from_states=("proposed",), to="stale",
                                      detail={"reason": "fresh_ownership_changed"})
        if (action.expected_version and aware(current.get("Modified_Time")) != aware(action.expected_version)):
            return journal.transition(action.action_id, from_states=("proposed",), to="stale",
                                      detail={"reason": "provider_version_changed"})
        if action.expected_state and any(current.get(k) != v for k, v in action.expected_state.items()):
            return journal.transition(action.action_id, from_states=("proposed",), to="stale",
                                      detail={"reason": "material_state_changed"})
    except (ValueError, TypeError, KeyError):
        return journal.transition(action.action_id, from_states=("proposed",), to="stale",
                                  detail={"reason": "fresh_evidence_unavailable"})
    journal.transition(action.action_id, from_states=("proposed",), to="attempted", attempt=True)
    try:
        provider_id = execute()
        if not provider_id:
            raise ValueError("Provider acknowledgement lacked exact ID")
        observed = reconcile()
        if observed != provider_id:
            raise ValueError("Provider readback did not prove intended state")
    except Exception as exc:
        # This branch also covers a timeout after a provider commit. No retry.
        return journal.transition(action.action_id, from_states=("attempted",), to="reconcile",
                                  detail={"reason": "provider_outcome_ambiguous", "error_type": type(exc).__name__})
    return journal.transition(action.action_id, from_states=("attempted",), to="succeeded",
                              provider_id=provider_id, detail={"reconciliation": "exact_readback"})


def reconcile_ambiguous(action: Action, journal: BusinessJournal,
                        observer: Callable[[], str | None]) -> dict:
    row = journal.get(action.action_id)
    if not row or row["state"] != "reconcile" or row["payload_hash"] != action.payload_hash:
        raise ValueError("No exact ambiguous action to reconcile")
    try:
        provider_id = observer()
    except Exception:
        provider_id = None
    if provider_id:
        if action.action_type == "crm.task.update" and provider_id != action.target_id:
            return row
        return journal.transition(action.action_id, from_states=("reconcile",), to="succeeded",
                                  provider_id=provider_id, detail={"reconciliation": "provider_state_proved"})
    return row  # Unknown remains an exception; no blind retry.


def dispatch_approved(action: Action, *, approval_id: str, actor: str,
                      journal: BusinessJournal, fresh: Callable[[], dict],
                      execute: Callable[[], str], reconcile: Callable[[], str | None]) -> dict:
    """Claim a Test Lab R3 approval before transport; exact readback or exception."""
    row = journal.get(action.action_id)
    if (not row or row["state"] != "approval_required" or row["risk"] != "R3"
            or row["ownership"] != "TEST_ONLY" or row["payload_hash"] != action.payload_hash):
        raise ValueError("Exact approved Test Lab proposal required")
    journal.claim_approval(approval_id, action, actor=actor)
    try:
        current = fresh()
        if (current.get("ownership") != "TEST_ONLY" or str(current.get("id")) != action.target_id or
            (action.expected_version and aware(current.get("Modified_Time")) != aware(action.expected_version)) or
            (action.expected_state and any(current.get(k) != v for k, v in action.expected_state.items()))):
            journal.close_approval(approval_id, state="stale")
            return journal.transition(action.action_id, from_states=("attempted",), to="stale",
                                      detail={"reason": "approved_action_became_stale"})
        provider_id = execute()
        if not provider_id or reconcile() != provider_id:
            raise ValueError("Approved action lacked exact provider readback")
    except Exception as exc:
        if journal.get(action.action_id)["state"] == "stale":
            return journal.get(action.action_id)
        journal.close_approval(approval_id, state="reconcile")
        return journal.transition(action.action_id, from_states=("attempted",), to="reconcile",
                                  detail={"reason": "approved_provider_outcome_ambiguous",
                                          "error_type": type(exc).__name__})
    journal.finish_approval(approval_id, provider_id=provider_id)
    return journal.get(action.action_id)


def render_dashboard(view: dict, *, section: str) -> str:
    if section not in {"autonomy", "approvals", "exceptions"}:
        raise ValueError("Unknown Phase 12 view")
    h = lambda value: escape(str(value if value is not None else "—"), quote=True)
    summary = view["summary"]
    if section == "approvals":
        rows = [x for x in view["actions"] if x["state"] == "approval_required"]
        title = "Business approvals"
    elif section == "exceptions":
        rows = [x for x in view["actions"] if x["state"] in {"reconcile", "stale", "failed", "deferred", "denied"}]
        title = "Business action exceptions"
    else:
        rows = view["actions"][:20]
        title = "Business autonomy"
    cards = []
    for x in rows:
        detail = json.loads(x["detail_json"])
        reason = detail.get("reason") or x["reason"]
        effect = detail.get("effect") or {}
        effect_line = " · ".join(f"{h(k)}: {h(v)}" for k, v in effect.items())
        approvals = [a for a in view["approvals"] if a["action_id"] == x["action_id"] and a["state"] == "issued"]
        expiry = f" · Approval expires {h(local_time(approvals[-1]['expires_at']))}" if approvals else ""
        recovery = ("Reconcile exact provider state; do not retry." if x["state"] == "reconcile" else
                    "Review the changed target before proposing a new action." if x["state"] == "stale" else
                    "Human review is required before any external effect." if x["state"] == "approval_required" else "")
        cards.append(f"<article><b>{h(x['action_type'])}</b> · {h(x['state'].replace('_',' ').upper())} · {h(x['risk'])}"
                     f"<p>{h(x['target_module'])} {h(x['target_id'])} · {h(reason)}</p>"
                     f"<p>{effect_line or 'Exact effect bound by payload hash'}{expiry}</p>"
                     f"<p>{h(recovery)}</p>"
                     f"<small>Action {h(x['action_id'])} · updated {h(local_time(x['updated_at']))}"
                     f" · payload SHA-256 {h(x['payload_hash'][:12])}</small></article>")
    counts = " · ".join(f"{h(k.replace('_',' ').title())}: {h(v)}" for k, v in summary.items())
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain autonomy</title>"
            "<style>body{font:16px/1.45 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#182536}"
            "article{border:1px solid #ccd;border-radius:.5rem;padding:1rem;margin:1rem 0}</style>"
            f"<h1>{h(title)}</h1><p>{counts}</p><p>Real CRM writes and customer sends are disabled."
            " Test Lab decisions are journaled; no email content or credentials appear here.</p>"
            + "".join(cards) + "</html>")
