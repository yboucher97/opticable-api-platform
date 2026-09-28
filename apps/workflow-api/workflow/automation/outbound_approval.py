"""Durable, single-use Phase 6 outbound approval envelopes.

Issuance is deliberately not registered as an automation action. A human-facing
control plane may call this ledger later; automation can only inspect/consume an
already-issued approval. Approval state is stored in the existing audit table so
Phase 6 requires no schema migration.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .event_schema import digest


CATEGORY = "outbound_approval_v1"
POLICY_VERSION = "phase6-sales-v1"
MAX_LIFETIME = timedelta(hours=24)
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,255}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")
_INTERNAL_DOMAINS = {"opticable.ca", "opti-plex.ca"}
BINDING_FIELDS = frozenset({"approval_id", "action_type", "source_type", "source_id", "source_version",
                            "account_id", "message_id", "recipient", "from_address",
                            "subject_hash", "content_hash", "policy_version"})


def _aware(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError(f"{field} must be an exact timezone-bearing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _clock(now=None):
    value = now if now is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("approval clock must include a timezone")
    return value.astimezone(timezone.utc)


def _human(value):
    # The future authenticated control plane must derive this subject from its
    # human session. A caller-supplied string is not an authentication mechanism.
    if not isinstance(value, str) or not re.fullmatch(r"human:[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value):
        raise ValueError("approval issuance requires an explicit human:<subject> actor")
    if re.match(r"(?:automation|system|optibrain|agent|ai|service)(?:[._-]|$)", value[6:], re.I):
        raise ValueError("machine actors cannot issue outbound approval")
    return value


def _email(value):
    if not isinstance(value, str) or value != value.strip() or len(value) > 254 or not _EMAIL.fullmatch(value):
        raise ValueError("A single valid email address is required")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Invalid email local part")
    if any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in domain.split(".")):
        raise ValueError("Invalid email domain")
    # Preserve local-part case: approval binds the address actually sent.
    return local + "@" + domain.lower()


def _internal(address):
    domain = address.rsplit("@", 1)[1]
    return any(domain == owned or domain.endswith("." + owned) for owned in _INTERNAL_DOMAINS)


def _source_version(value, source_type):
    if not isinstance(value, str):
        raise ValueError("Invalid source version")
    if source_type == "lead" or re.match(r"\d{4}-\d{2}-\d{2}", value):
        return _aware(value, field="source_version").isoformat()
    if not _ID.fullmatch(value):
        raise ValueError("Invalid opaque source version")
    return value


def validate_text(subject, content):
    # Hash and transmit exactly these strings, including meaningful whitespace.
    if (not isinstance(subject, str) or not subject.strip() or len(subject) > 500
            or any(ord(c) < 32 or ord(c) == 127 for c in subject)
            or not isinstance(content, str) or not content.strip() or len(content) > 12000
            or any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in content)):
        raise ValueError("Outbound subject/content are missing, unsafe or out of bounds")
    return subject, content


class OutboundApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    actor: str = Field(min_length=1, max_length=128)
    approved_at: str
    expires_at: str
    action_type: Literal["send_new_email", "reply_email"]
    source_type: Literal["lead", "message", "draft"]
    source_id: str = Field(min_length=1, max_length=255)
    source_version: str = Field(min_length=1, max_length=255)
    account_id: str = Field(min_length=1, max_length=30)
    message_id: str | None = Field(default=None, max_length=30)
    recipient: str = Field(min_length=3, max_length=254)
    from_address: str = Field(min_length=3, max_length=254)
    subject_hash: str = Field(min_length=64, max_length=64)
    content_hash: str = Field(min_length=64, max_length=64)
    policy_version: Literal["phase6-sales-v1"] = POLICY_VERSION

    @field_validator("recipient", "from_address")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("subject_hash", "content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        cleaned = value
        if not _HEX64.fullmatch(cleaned):
            raise ValueError("approval hashes must be lowercase SHA-256")
        return cleaned

    @field_validator("source_id")
    @classmethod
    def validate_source_identity(cls, value: str) -> str:
        cleaned = value
        if not _ID.fullmatch(cleaned):
            raise ValueError("invalid outbound source identity")
        return cleaned

    @field_validator("account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        cleaned = value
        if not re.fullmatch(r"[0-9]{1,30}", cleaned):
            raise ValueError("invalid mailbox account id")
        return cleaned

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value):
        return _human(value)

    @field_validator("approved_at", "expires_at")
    @classmethod
    def validate_time(cls, value):
        return _aware(value, field="approval timestamp").isoformat()

    @model_validator(mode="before")
    @classmethod
    def canonical_version(cls, value):
        if isinstance(value, dict):
            value = {**value, "source_version": _source_version(value.get("source_version"), value.get("source_type"))}
        return value

    @model_validator(mode="after")
    def validate_reply_identity(self) -> "OutboundApproval":
        lifetime = _aware(self.expires_at, field="expires_at") - _aware(self.approved_at, field="approved_at")
        if not timedelta(0) < lifetime <= MAX_LIFETIME:
            raise ValueError("approval lifetime must be positive and at most 24 hours")
        if self.from_address.rsplit("@", 1)[1] not in _INTERNAL_DOMAINS or _internal(self.recipient):
            raise ValueError("approval requires an owned sender and external customer recipient")
        if self.action_type == "reply_email":
            if not self.message_id or not re.fullmatch(r"[0-9]{1,30}", self.message_id):
                raise ValueError("reply approval requires a numeric message_id")
        elif self.message_id is not None:
            raise ValueError("send_new_email approval must not include message_id")
        return self


class OutboundApprovalLedger:
    """Audit-backed approval state with one cross-process consumption lock."""

    def __init__(self, store):
        self.store = store
        self._thread_lock = threading.Lock()
        self._lock_owner = None
        self._lock_path = Path(store.db_path).resolve().with_suffix(".outbound-approval.lock")

    @contextmanager
    def lock(self):
        if not self._thread_lock.acquire(blocking=False):
            raise ValueError("outbound_approval_in_progress")
        fd = None
        try:
            fd = os.open(
                self._lock_path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            meta = os.fstat(fd)
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                    or meta.st_nlink != 1 or stat.S_IMODE(meta.st_mode) != 0o600):
                raise ValueError("unsafe_outbound_approval_lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("outbound_approval_in_progress") from None
            self._lock_owner = threading.get_ident()
            yield
        finally:
            self._lock_owner = None
            if fd is not None:
                os.close(fd)
            self._thread_lock.release()

    def _require_lock(self):
        if self._lock_owner != threading.get_ident():
            raise ValueError("outbound approval transition requires the consumption lock")

    def _latest(self, approval_id: str) -> dict | None:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT action,actor,at,metadata_json FROM automation_audit "
                "WHERE category=? AND target=? ORDER BY id DESC LIMIT 1",
                (CATEGORY, approval_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "state": row["action"],
            "actor": row["actor"],
            "at": row["at"],
            "approval": json.loads(row["metadata_json"]),
        }

    def inspect(self, approval_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{32}", str(approval_id or "")):
            raise ValueError("invalid approval id")
        return self._latest(approval_id)

    def _record(self, action: str, approval: OutboundApproval, actor: str, *, extra: dict | None = None) -> None:
        metadata = approval.model_dump()
        metadata.update(extra or {})
        self.store.audit(
            category=CATEGORY,
            action=action,
            actor=actor,
            success=action in {"issued", "consumed"},
            target=approval.approval_id,
            metadata=metadata,
        )

    def issue(
        self,
        *,
        actor: str,
        action_type: Literal["send_new_email", "reply_email"],
        source_type: Literal["lead", "message", "draft"],
        source_id: str,
        source_version: str,
        account_id: str,
        recipient: str,
        from_address: str,
        subject: str,
        content: str,
        message_id: str | None = None,
        expires_at: str,
        now: datetime | None = None,
        approval_id: str | None = None,
    ) -> OutboundApproval:
        """Issue one explicit approval. This method is never an automation action."""

        human = _human(actor)
        clock = _clock(now)
        expiry = _aware(expires_at, field="expires_at")
        if expiry <= clock or expiry - clock > MAX_LIFETIME:
            raise ValueError("approval expiry must be within the next 24 hours")
        sender = _email(from_address)
        recipient_address = _email(recipient)
        subject_value, content_value = validate_text(subject, content)
        identity = uuid4().hex if approval_id is None else approval_id
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("approval id must be a 32-character lowercase hex id")
        envelope = OutboundApproval(
            approval_id=identity,
            actor=human,
            approved_at=clock.isoformat(),
            expires_at=expiry.isoformat(),
            action_type=action_type,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
            account_id=account_id,
            message_id=message_id,
            recipient=recipient_address,
            from_address=sender,
            subject_hash=digest(subject_value),
            content_hash=digest(content_value),
        )
        with self.lock():
            if self._latest(identity) is not None:
                raise ValueError("approval id already exists")
            self._record("issued", envelope, human)
        return envelope

    @staticmethod
    def expected(
        *,
        approval_id: str,
        action_type: Literal["send_new_email", "reply_email"],
        source_type: Literal["lead", "message", "draft"],
        source_id: str,
        source_version: str,
        account_id: str,
        recipient: str,
        from_address: str,
        subject: str,
        content: str,
        message_id: str | None = None,
    ) -> dict:
        """Return only the immutable fields that a send must bind exactly."""
        subject, content = validate_text(subject, content)
        return {
            "approval_id": approval_id,
            "action_type": action_type,
            "source_type": source_type,
            "source_id": source_id,
            "source_version": _source_version(source_version, source_type),
            "account_id": account_id,
            "message_id": message_id,
            "recipient": _email(recipient),
            "from_address": _email(from_address),
            "subject_hash": digest(subject),
            "content_hash": digest(content),
            "policy_version": POLICY_VERSION,
        }

    def require_issued(self, expected: dict, *, now: datetime | None = None) -> OutboundApproval:
        if set(expected) != BINDING_FIELDS:
            raise ValueError("complete exact outbound binding required")
        approval_id = str(expected.get("approval_id") or "")
        state = self.inspect(approval_id)
        if state is None:
            raise ValueError("outbound approval not found")
        if state["state"] != "issued":
            raise ValueError("outbound approval is not reusable")
        approval = OutboundApproval.model_validate(state["approval"])
        clock = _clock(now)
        if not _aware(approval.approved_at, field="approved_at") <= clock < _aware(approval.expires_at, field="expires_at"):
            raise ValueError("outbound approval expired")
        bound = approval.model_dump()
        for key, value in expected.items():
            if bound.get(key) != value:
                raise ValueError("outbound approval binding mismatch")
        return approval

    def _require_current(self, approval, states):
        self._require_lock()
        # Revalidation rejects unchecked model_copy/model_construct envelopes.
        approval = OutboundApproval.model_validate(approval.model_dump())
        current = self._latest(approval.approval_id)
        if current is None or current["state"] not in states or current["approval"] != approval.model_dump():
            raise ValueError("outbound approval state or envelope changed")
        return approval

    def mark_consuming(self, approval: OutboundApproval) -> None:
        approval = self._require_current(approval, {"issued"})
        bound = {key: approval.model_dump()[key] for key in BINDING_FIELDS}
        self.require_issued(bound)
        self._record("consuming", approval, "automation-engine")

    def require_consuming(self, approval):
        self._require_current(approval, {"consuming"})
        clock = _clock()
        if not _aware(approval.approved_at, field="approved_at") <= clock < _aware(approval.expires_at, field="expires_at"):
            raise ValueError("outbound approval expired before provider call")

    def mark_consumed(self, approval: OutboundApproval, *, provider_operation_id: str, request_id: str | None = None) -> None:
        approval = self._require_current(approval, {"consuming"})
        if not re.fullmatch(r"[0-9]{1,30}", provider_operation_id):
            raise ValueError("invalid provider operation id")
        extra = {"provider_operation_id": provider_operation_id}
        if request_id is not None:
            extra["request_id_hash"] = digest(str(request_id))
        self._record("consumed", approval, "automation-engine", extra=extra)

    def mark_manual(self, approval: OutboundApproval, *, error: str) -> None:
        approval = self._require_current(approval, {"issued", "consuming"})
        if error not in {"provider_unconfirmed", "policy_disabled", "preflight_changed"}:
            raise ValueError("invalid approval error category")
        self._record("manual", approval, "automation-engine", extra={"error": error})
