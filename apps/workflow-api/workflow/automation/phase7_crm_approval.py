"""Unregistered, durable one-use human approval for a single CRM canary patch.

This ledger supplies evidence only; it is not a provider writer or an automation
action. A future live executor must rehydrate the source and verify exact values
before claiming, then use the CRM transport boundary. A claimed approval is
never automatically reusable, including after process loss or response loss.
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
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator

from .outbound_approval import _aware, _clock, _human


CATEGORY = "phase7_crm_canary_approval_v1"
POLICY = "phase7-single-canary-v1"
MAX_LIFETIME = timedelta(hours=1)
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_CRM_ID = re.compile(r"[0-9]{1,30}\Z")


class CrmCanaryApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    approval_id: str
    actor: str
    approved_at: str
    expires_at: str
    lead_id: str
    source_version: str
    plan_hash: str
    patch_hash: str
    policy: str = POLICY

    @model_validator(mode="after")
    def validate_exact(self):
        if not _ID.fullmatch(self.approval_id) or not _CRM_ID.fullmatch(self.lead_id):
            raise ValueError("Invalid CRM canary approval identity")
        if self.actor != _human(self.actor) or self.policy != POLICY:
            raise ValueError("Invalid CRM canary approval authority")
        start = _aware(self.approved_at, field="approved_at")
        end = _aware(self.expires_at, field="expires_at")
        if not timedelta(0) < end - start <= MAX_LIFETIME:
            raise ValueError("CRM canary approval lifetime exceeds one hour")
        if _aware(self.source_version, field="source_version").isoformat() != self.source_version:
            raise ValueError("Noncanonical Lead source version")
        if not _HEX.fullmatch(self.plan_hash) or not _HEX.fullmatch(self.patch_hash):
            raise ValueError("Invalid exact canary hashes")
        return self


class CrmCanaryApprovalLedger:
    def __init__(self, store):
        self.store = store
        self.lock_path = Path(store.db_path).resolve().with_suffix(".phase7-crm-canary.lock")

    @contextmanager
    def _lock(self):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            meta = os.fstat(fd)
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                    or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1):
                raise ValueError("Unsafe CRM canary approval lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def inspect(self, approval_id: str) -> dict | None:
        if not isinstance(approval_id, str) or not _ID.fullmatch(approval_id):
            raise ValueError("Invalid CRM canary approval ID")
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT action,metadata_json FROM automation_audit WHERE category=? AND target=? "
                "ORDER BY id DESC LIMIT 1", (CATEGORY, approval_id),
            ).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"])
        fields = set(CrmCanaryApproval.model_fields)
        extras = set(metadata) - fields
        allowed = {"consumed": {"provider_operation_id", "verified_patch_hash"},
                   "manual": {"reason"}}.get(row["action"], set())
        if not extras <= allowed:
            raise ValueError("Unexpected CRM approval audit metadata")
        approval = CrmCanaryApproval.model_validate({key: metadata[key] for key in fields if key in metadata})
        return {"state": row["action"], "approval": approval, "evidence": metadata}

    def _record(self, state: str, approval: CrmCanaryApproval, extra: dict | None = None):
        self.store.audit(category=CATEGORY, action=state,
                         actor=approval.actor if state == "issued" else "automation-engine",
                         success=state in {"issued", "consumed"}, target=approval.approval_id,
                         metadata={**approval.model_dump(), **(extra or {})})

    def issue(self, *, actor: str, lead_id: str, source_version: str,
              plan_hash: str, patch_hash: str, expires_at: str,
              now: datetime | None = None, approval_id: str | None = None) -> CrmCanaryApproval:
        """Human control-plane entry only; never register as an automation action."""
        current = _clock(now)
        approval = CrmCanaryApproval(
            approval_id=approval_id or uuid4().hex, actor=_human(actor),
            approved_at=current.isoformat(), expires_at=_aware(expires_at, field="expires_at").isoformat(),
            lead_id=lead_id, source_version=source_version,
            plan_hash=plan_hash, patch_hash=patch_hash,
        )
        if _aware(approval.expires_at, field="expires_at") <= current:
            raise ValueError("CRM canary approval already expired")
        with self._lock():
            if self.inspect(approval.approval_id) is not None:
                raise ValueError("CRM canary approval ID already exists")
            self._record("issued", approval)
        return approval

    def claim(self, approval_id: str, *, lead_id: str, source_version: str,
              plan_hash: str, patch_hash: str, now: datetime | None = None) -> CrmCanaryApproval:
        """Durably mark consuming before any future provider call."""
        with self._lock():
            state = self.inspect(approval_id)
            if state is None or state["state"] != "issued":
                raise ValueError("CRM canary approval is unavailable or non-reusable")
            approval = state["approval"]
            current = _clock(now)
            if not _aware(approval.approved_at, field="approved_at") <= current < _aware(approval.expires_at, field="expires_at"):
                raise ValueError("CRM canary approval expired")
            if (approval.lead_id, approval.source_version, approval.plan_hash, approval.patch_hash) != (
                    lead_id, source_version, plan_hash, patch_hash):
                raise ValueError("CRM canary exact binding changed")
            self._record("consuming", approval)
            return approval

    def mark_dispatch(self, approval: CrmCanaryApproval, *, now: datetime | None = None) -> None:
        """One durable dispatch token; a crash leaves no second transport grant."""
        with self._lock():
            state = self.inspect(approval.approval_id)
            if state is None or state["state"] != "consuming" or state["approval"] != approval:
                raise ValueError("CRM canary transport grant already used or unavailable")
            current = _clock(now)
            if not _aware(approval.approved_at, field="approved_at") <= current < _aware(approval.expires_at, field="expires_at"):
                raise ValueError("CRM canary approval expired before transport")
            self._record("dispatching", approval)

    def finish(self, approval: CrmCanaryApproval, *, operation_id: str | None = None,
               verified_patch_hash: str | None = None, reason: str | None = None) -> None:
        with self._lock():
            state = self.inspect(approval.approval_id)
            if (state is None or state["state"] not in {"consuming", "dispatching"}
                    or state["approval"] != approval):
                raise ValueError("CRM canary approval is not in a resolvable state")
            if (operation_id is not None and reason is None and _CRM_ID.fullmatch(operation_id)
                    and verified_patch_hash == approval.patch_hash and state["state"] == "dispatching"):
                self._record("consumed", approval, {"provider_operation_id": operation_id,
                                                   "verified_patch_hash": verified_patch_hash})
            elif (operation_id is None and verified_patch_hash is None
                  and reason in {"provider_unconfirmed", "preflight_changed", "policy_disabled"}):
                self._record("manual", approval, {"reason": reason})
            else:
                raise ValueError("CRM canary outcome must be verified or manual")
