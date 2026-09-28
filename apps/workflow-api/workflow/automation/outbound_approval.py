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
from .models import utc_now_iso


CATEGORY = "outbound_approval_v1"
POLICY_VERSION = "phase6-sales-v1"
MAX_LIFETIME = timedelta(hours=24)
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,255}")


def _aware(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _email(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) > 254 or not _EMAIL.fullmatch(cleaned):
        raise ValueError("A valid email address is required")
    return cleaned


class OutboundApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=32, max_length=64)
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
    policy_version: str = POLICY_VERSION

    @field_validator("recipient", "from_address")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _email(value)

    @field_validator("subject_hash", "content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        cleaned = str(value or "").strip().lower()
        if not _HEX64.fullmatch(cleaned):
            raise ValueError("approval hashes must be lowercase SHA-256")
        return cleaned

    @field_validator("source_id", "source_version")
    @classmethod
    def validate_source_identity(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not _ID.fullmatch(cleaned):
            raise ValueError("invalid outbound source identity")
        return cleaned

    @field_validator("account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not re.fullmatch(r"[0-9]{1,30}", cleaned):
            raise ValueError("invalid mailbox account id")
        return cleaned

    @model_validator(mode="after")
    def validate_reply_identity(self) -> "OutboundApproval":
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
        self._lock_path = Path(store.db_path).with_suffix(".outbound-approval.lock")

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
            yield
        finally:
            if fd is not None:
                os.close(fd)
            self._thread_lock.release()

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

        human = str(actor or "").strip()
        if not human or human.casefold() in {"automation-engine", "system", "optibrain"}:
            raise ValueError("approval issuance requires an explicit human actor")
        clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = _aware(expires_at, field="expires_at")
        if expiry <= clock or expiry - clock > MAX_LIFETIME:
            raise ValueError("approval expiry must be within the next 24 hours")
        sender = _email(from_address)
        if sender.rsplit("@", 1)[1] not in {"opticable.ca", "opti-plex.ca"}:
            raise ValueError("approval sender must use an Opticable-owned domain")
        recipient_address = _email(recipient)
        if recipient_address.rsplit("@", 1)[1] in {"opticable.ca", "opti-plex.ca"}:
            raise ValueError("outbound customer approval cannot target an internal domain")
        subject_value = str(subject or "").strip()
        content_value = str(content or "").strip()
        if not subject_value or len(subject_value) > 500 or not content_value or len(content_value) > 12000:
            raise ValueError("approval subject/content are missing or out of bounds")
        identity = approval_id or uuid4().hex
        if not re.fullmatch(r"[0-9a-f]{32}", identity):
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
        actor: str = "human-placeholder",
        expires_at: str = "2999-01-01T00:00:00+00:00",
    ) -> dict:
        """Return only the immutable fields that a send must bind exactly."""
        return {
            "approval_id": approval_id,
            "action_type": action_type,
            "source_type": source_type,
            "source_id": str(source_id).strip(),
            "source_version": str(source_version).strip(),
            "account_id": str(account_id).strip(),
            "message_id": str(message_id).strip() if message_id is not None else None,
            "recipient": _email(recipient),
            "from_address": _email(from_address),
            "subject_hash": digest(str(subject or "").strip()),
            "content_hash": digest(str(content or "").strip()),
            "policy_version": POLICY_VERSION,
        }

    def require_issued(self, expected: dict, *, now: datetime | None = None) -> OutboundApproval:
        approval_id = str(expected.get("approval_id") or "")
        state = self.inspect(approval_id)
        if state is None:
            raise ValueError("outbound approval not found")
        if state["state"] != "issued":
            raise ValueError("outbound approval is not reusable")
        approval = OutboundApproval.model_validate(state["approval"])
        clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if _aware(approval.expires_at, field="expires_at") <= clock:
            raise ValueError("outbound approval expired")
        bound = approval.model_dump()
        for key, value in expected.items():
            if key == "approval_id":
                continue
            if bound.get(key) != value:
                raise ValueError("outbound approval binding mismatch")
        return approval

    def mark_consuming(self, approval: OutboundApproval) -> None:
        current = self._latest(approval.approval_id)
        if current is None or current["state"] != "issued":
            raise ValueError("outbound approval is not available")
        self._record("consuming", approval, "automation-engine")

    def mark_consumed(self, approval: OutboundApproval, *, provider_operation_id: str, request_id: str | None = None) -> None:
        current = self._latest(approval.approval_id)
        if current is None or current["state"] != "consuming":
            raise ValueError("outbound approval consumption state changed")
        self._record(
            "consumed",
            approval,
            "automation-engine",
            extra={"provider_operation_id": provider_operation_id, "request_id": request_id},
        )

    def mark_manual(self, approval: OutboundApproval, *, error: str) -> None:
        current = self._latest(approval.approval_id)
        if current is None or current["state"] not in {"consuming", "issued"}:
            raise ValueError("outbound approval manual state conflict")
        self._record("manual", approval, "automation-engine", extra={"error": str(error)[:128]})
