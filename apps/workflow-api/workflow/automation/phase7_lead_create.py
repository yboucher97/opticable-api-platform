"""Unregistered, single-use Phase 7 Lead creation control.

The human-visible payload is supplied only at the operator boundary. Audit rows
retain hashes and identities, never the customer's address or raw field values.
An uncertain request is permanently fenced for manual reconciliation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator

from .outbound_approval import _aware, _clock, _email, _human, _internal
from .event_schema import digest


POLICY = "phase7-single-lead-create-v1"
CATEGORY = "phase7_lead_create_approval_v1"
FIELDS = frozenset({"First_Name", "Last_Name", "Company", "Email", "Lead_Status", "Email_Opt_Out"})
MAX_LIFETIME = timedelta(hours=1)
MAX_DEDUPE_AGE = timedelta(minutes=5)
_ID = re.compile(r"[0-9a-f]{32}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CRM_ID = re.compile(r"[0-9]{1,30}\Z")


def canonical_payload(fields: dict) -> dict:
    """Reject extra fields and return the only permitted one-record CRM body."""
    if not isinstance(fields, dict) or set(fields) != FIELDS:
        raise ValueError("Lead create requires the exact six reviewed fields")
    for key in ("First_Name", "Last_Name", "Company"):
        value = fields[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 120:
            raise ValueError("Lead create name/company is invalid")
    address = _email(fields["Email"])
    if address != fields["Email"] or _internal(address):
        raise ValueError("Lead create requires canonical external email")
    if fields["Lead_Status"] != "Not Contacted" or fields["Email_Opt_Out"] is not False:
        raise ValueError("Lead create status or consent differs from review")
    # Zoho runs configured Cadences by default on insert even with an empty
    # workflow trigger list. Suppress both for this human-controlled canary.
    return {"data": [dict(sorted(fields.items()))], "trigger": [],
            "skip_feature_execution": [{"name": "cadences"}]}


def request_hash(fields: dict) -> str:
    return digest(["POST", "/crm/v8/Leads", canonical_payload(fields)])


def exact_email_search(client, module: str, email: str) -> tuple[str, ...]:
    if module not in {"Leads", "Contacts"}:
        raise ValueError("Unreviewed dedupe module")
    response = client.request("zohoapis", "GET", f"/crm/v8/{module}/search",
                              query={"email": email, "fields": "id,Email", "page": 1, "per_page": 200})
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise ValueError("CRM dedupe search failed")
    status = response.get("status")
    if status == 204:
        if response.get("data") not in (None, "", {}, {"data": []}):
            raise ValueError("CRM dedupe empty response was malformed")
        return ()
    outer = response.get("data")
    if (status != 200 or not isinstance(outer, dict)
            or not isinstance(outer.get("data"), list)
            or not isinstance(outer.get("info"), dict)
            or outer["info"].get("more_records") is not False):
        raise ValueError("CRM dedupe search is incomplete")
    matches = []
    for row in outer["data"]:
        if not isinstance(row, dict):
            raise ValueError("CRM dedupe row malformed")
        value = row.get("Email")
        if value is not None and str(value).strip().casefold() == email:
            identity = str(row.get("id") or "")
            if not _CRM_ID.fullmatch(identity):
                raise ValueError("CRM dedupe identity malformed")
            matches.append(identity)
    if len(matches) != len(set(matches)):
        raise ValueError("CRM dedupe result repeated")
    return tuple(sorted(matches))


def complete_module_scan(client, module: str, email: str) -> tuple[tuple[str, ...], int]:
    """Cross-check Search against the current records API to catch index lag.

    This canary scans at most 2,000 rows per module. An account beyond that
    limit requires a separately reviewed read-only query mechanism.
    """
    if module not in {"Leads", "Contacts"}:
        raise ValueError("Unreviewed dedupe module")
    matches = []
    seen = set()
    count = 0
    for page in range(1, 11):
        response = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                                  query={"fields": "id,Email", "page": page, "per_page": 200})
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise ValueError("CRM dedupe inventory failed")
        if response.get("status") == 204 and page == 1 and response.get("data") in (None, "", {}):
            return (), 0
        outer = response.get("data")
        if (response.get("status") != 200 or not isinstance(outer, dict)
                or not isinstance(outer.get("data"), list)
                or not isinstance(outer.get("info"), dict)
                or not isinstance(outer["info"].get("more_records"), bool)):
            raise ValueError("CRM dedupe inventory is incomplete")
        rows = outer["data"]
        if not rows or len(rows) > 200:
            raise ValueError("CRM dedupe inventory page is malformed")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("CRM dedupe inventory row malformed")
            identity = str(row.get("id") or "")
            if not _CRM_ID.fullmatch(identity) or identity in seen:
                raise ValueError("CRM dedupe inventory identity malformed or repeated")
            seen.add(identity)
            if str(row.get("Email") or "").strip().casefold() == email:
                matches.append(identity)
        count += len(rows)
        if not outer["info"]["more_records"]:
            return tuple(sorted(matches)), count
    raise ValueError("CRM dedupe inventory exceeds bounded canary scan")


def dedupe_preflight(client, fields: dict, *, now: datetime | None = None) -> dict:
    canonical_payload(fields)
    current = _clock(now)
    email = fields["Email"]
    leads = exact_email_search(client, "Leads", email)
    contacts = exact_email_search(client, "Contacts", email)
    current_leads, lead_rows = complete_module_scan(client, "Leads", email)
    current_contacts, contact_rows = complete_module_scan(client, "Contacts", email)
    if leads or contacts or current_leads or current_contacts:
        raise ValueError("Exact email already exists in CRM; create refused")
    return {"at": current.isoformat(), "email_hash": digest(email),
            "query_hash": digest(["Zoho CRM v8", "Leads", leads, current_leads, lead_rows,
                                   "Contacts", contacts, current_contacts, contact_rows, email]),
            "lead_count": 0, "contact_count": 0,
            "scanned_leads": lead_rows, "scanned_contacts": contact_rows}


class LeadCreateApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    approval_id: str
    actor: str
    approved_at: str
    expires_at: str
    payload_hash: str
    email_hash: str
    dedupe_hash: str
    dedupe_at: str
    policy: str = POLICY

    @model_validator(mode="after")
    def validate_exact(self):
        if not _ID.fullmatch(self.approval_id) or self.actor != _human(self.actor) or self.policy != POLICY:
            raise ValueError("Invalid Lead create approval authority")
        start = _aware(self.approved_at, field="approved_at")
        expiry = _aware(self.expires_at, field="expires_at")
        dedupe = _aware(self.dedupe_at, field="dedupe_at")
        if not timedelta(0) < expiry-start <= MAX_LIFETIME:
            raise ValueError("Lead create approval lifetime exceeds one hour")
        if not timedelta(0) <= start-dedupe <= MAX_DEDUPE_AGE:
            raise ValueError("Lead create dedupe evidence is stale")
        if (not _HEX.fullmatch(self.payload_hash) or not _HEX.fullmatch(self.email_hash)
                or not _HEX.fullmatch(self.dedupe_hash)):
            raise ValueError("Lead create review hash malformed")
        return self


class LeadCreateLedger:
    def __init__(self, store):
        self.store = store
        self.lock_path = Path(store.db_path).resolve().with_suffix(".phase7-lead-create.lock")

    @contextmanager
    def lock(self):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            meta = os.fstat(fd)
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                    or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1):
                raise ValueError("Unsafe Lead create lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def inspect(self, approval_id: str) -> dict | None:
        if not isinstance(approval_id, str) or not _ID.fullmatch(approval_id):
            raise ValueError("Invalid Lead create approval ID")
        with self.store._connect() as conn:
            row = conn.execute("SELECT action,metadata_json FROM automation_audit WHERE category=? AND target=? "
                               "ORDER BY id DESC LIMIT 1", (CATEGORY, approval_id)).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"])
        names = set(LeadCreateApproval.model_fields)
        extras = set(metadata)-names
        allowed = {"consumed": {"provider_id", "verified_hash"},
                   "manual": {"reason"}}.get(row["action"], set())
        if not extras <= allowed:
            raise ValueError("Unexpected Lead create audit metadata")
        approval = LeadCreateApproval.model_validate({k: metadata[k] for k in names if k in metadata})
        return {"state": row["action"], "approval": approval, "evidence": metadata}

    def _record(self, state: str, approval: LeadCreateApproval, extra: dict | None = None):
        self.store.audit(category=CATEGORY, action=state,
                         actor=approval.actor if state == "issued" else "automation-engine",
                         success=state in {"issued", "consumed"}, target=approval.approval_id,
                         metadata={**approval.model_dump(), **(extra or {})})

    def issue(self, *, actor: str, fields: dict, dedupe: dict, expires_at: str,
              now: datetime | None = None, approval_id: str | None = None) -> LeadCreateApproval:
        current = _clock(now)
        canonical_payload(fields)
        if (dedupe.get("email_hash") != digest(fields["Email"])
                or dedupe.get("lead_count") != 0 or dedupe.get("contact_count") != 0
                or not _HEX.fullmatch(str(dedupe.get("query_hash") or ""))):
            raise ValueError("Lead create dedupe evidence changed")
        approval = LeadCreateApproval(
            approval_id=approval_id or uuid4().hex, actor=_human(actor),
            approved_at=current.isoformat(), expires_at=_aware(expires_at, field="expires_at").isoformat(),
            payload_hash=request_hash(fields), email_hash=dedupe["email_hash"],
            dedupe_hash=dedupe["query_hash"],
            dedupe_at=dedupe["at"])
        if _aware(approval.expires_at, field="expires_at") <= current:
            raise ValueError("Lead create approval expired")
        with self.lock():
            if self.inspect(approval.approval_id) is not None:
                raise ValueError("Lead create approval ID already exists")
            with self.store._connect() as conn:
                rows = conn.execute("SELECT metadata_json FROM automation_audit WHERE category=? AND action='issued'",
                                    (CATEGORY,)).fetchall()
            if any(json.loads(row["metadata_json"]).get("email_hash") == approval.email_hash for row in rows):
                raise ValueError("Lead create email was already approved; reconcile before another approval")
            self._record("issued", approval)
        return approval

    def claim(self, approval_id: str, fields: dict, *, now: datetime | None = None) -> LeadCreateApproval:
        with self.lock():
            state = self.inspect(approval_id)
            if state is None or state["state"] != "issued":
                raise ValueError("Lead create approval is unavailable or non-reusable")
            approval = state["approval"]
            current = _clock(now)
            if (not _aware(approval.approved_at, field="approved_at") <= current
                    < _aware(approval.expires_at, field="expires_at")
                    or request_hash(fields) != approval.payload_hash):
                raise ValueError("Lead create approval expired or payload changed")
            self._record("consuming", approval)
            return approval

    def dispatch(self, approval: LeadCreateApproval):
        with self.lock():
            state = self.inspect(approval.approval_id)
            if state is None or state["state"] != "consuming" or state["approval"] != approval:
                raise ValueError("Lead create dispatch already used")
            self._record("dispatching", approval)

    def finish(self, approval: LeadCreateApproval, *, provider_id: str | None = None,
               verified_hash: str | None = None, reason: str | None = None):
        with self.lock():
            state = self.inspect(approval.approval_id)
            if state is None or state["state"] not in {"consuming", "dispatching"} or state["approval"] != approval:
                raise ValueError("Lead create approval is not resolvable")
            if (state["state"] == "dispatching" and provider_id is not None
                    and _CRM_ID.fullmatch(provider_id) and verified_hash == approval.payload_hash and reason is None):
                self._record("consumed", approval, {"provider_id": provider_id, "verified_hash": verified_hash})
            elif provider_id is None and verified_hash is None and reason in {"provider_unconfirmed", "policy_disabled"}:
                self._record("manual", approval, {"reason": reason})
            else:
                raise ValueError("Lead create outcome must be verified or manual")


def execute_approved_create(client, store, approval_id: str, fields: dict, *, now: datetime | None = None) -> dict:
    """One exact create attempt. No caller may retry an ambiguous result."""
    canonical_payload(fields)
    ledger = LeadCreateLedger(store)
    if os.environ.get("OPTIBRAIN_LEAD_CREATE_CANARY") != POLICY or os.environ.get("OPTIBRAIN_LEAD_CREATE_APPROVAL_ID") != approval_id:
        raise ValueError("Lead create canary is disabled or approval is not pinned")
    state = ledger.inspect(approval_id)
    if state is None or state["state"] != "issued" or state["approval"].payload_hash != request_hash(fields):
        raise ValueError("Lead create approval unavailable or changed")
    proof = dedupe_preflight(client, fields, now=now)
    if proof["query_hash"] != state["approval"].dedupe_hash:
        raise ValueError("Lead create dedupe result changed")
    approval = ledger.claim(approval_id, fields, now=now)
    body = canonical_payload(fields)
    try:
        from .crm_write_boundary import reviewed_create_call
        with reviewed_create_call(client, body, approval, ledger, now=now):
            response = client.request("zohoapis", "POST", "/crm/v8/Leads", body=body,
                                      reason="Phase 7 single approved Lead create", confirm=True)
        rows = (response.get("data") or {}).get("data") if isinstance(response, dict) else None
        if (response.get("ok") is not True or response.get("status") not in {200, 201}
                or not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "success"):
            raise ValueError("Lead create acknowledgement unconfirmed")
        identity = str((rows[0].get("details") or {}).get("id") or "")
        if not _CRM_ID.fullmatch(identity):
            raise ValueError("Lead create returned no provider ID")
        readback = client.request("zohoapis", "GET", f"/crm/v8/Leads/{identity}",
                                  query={"fields": ",".join(sorted(FIELDS))})
        actual = (readback.get("data") or {}).get("data") if isinstance(readback, dict) else None
        if (not isinstance(actual, list) or len(actual) != 1
                or str(actual[0].get("id") or "") != identity
                or any(actual[0].get(k) != v for k, v in fields.items())):
            raise ValueError("Lead create exact readback mismatch")
        lead_search = exact_email_search(client, "Leads", fields["Email"])
        contact_search = exact_email_search(client, "Contacts", fields["Email"])
        lead_scan, _ = complete_module_scan(client, "Leads", fields["Email"])
        contact_scan, _ = complete_module_scan(client, "Contacts", fields["Email"])
        if lead_search != (identity,) or lead_scan != (identity,) or contact_search or contact_scan:
            raise ValueError("Lead create duplicate or indexing state requires human reconciliation")
        ledger.finish(approval, provider_id=identity, verified_hash=approval.payload_hash)
        return {"state": "consumed", "approval_id": approval_id, "provider_id": identity,
                "request_hash": approval.payload_hash}
    except Exception:
        current = ledger.inspect(approval_id)
        if current is not None and current["state"] in {"consuming", "dispatching"}:
            try:
                ledger.finish(approval, reason="provider_unconfirmed")
            except Exception:
                pass
        raise ValueError("Lead create outcome requires human reconciliation") from None


def inspect_ambiguous_create(client, store, approval_id: str, fields: dict) -> dict:
    """Read-only provider reconciliation; never reopens a spent approval."""
    canonical_payload(fields)
    ledger = LeadCreateLedger(store)
    state = ledger.inspect(approval_id)
    if (state is None or state["state"] not in {"consuming", "dispatching", "manual"}
            or state["approval"].payload_hash != request_hash(fields)):
        raise ValueError("No matching uncertain Lead create exists")
    lead_search = exact_email_search(client, "Leads", fields["Email"])
    contact_search = exact_email_search(client, "Contacts", fields["Email"])
    lead_scan, _ = complete_module_scan(client, "Leads", fields["Email"])
    contact_scan, _ = complete_module_scan(client, "Contacts", fields["Email"])
    identities = tuple(sorted(set(lead_search) | set(lead_scan)))
    conclusion = "not_observed"
    identity = None
    if contact_search or contact_scan or len(identities) > 1:
        conclusion = "ambiguous_identity"
    elif len(identities) == 1:
        identity = identities[0]
        response = client.request("zohoapis", "GET", f"/crm/v8/Leads/{identity}",
                                  query={"fields": ",".join(sorted(FIELDS))})
        rows = (response.get("data") or {}).get("data") if isinstance(response, dict) else None
        if (isinstance(rows, list) and len(rows) == 1
                and str(rows[0].get("id") or "") == identity
                and all(rows[0].get(key) == value for key, value in fields.items())):
            conclusion = "exact_record_observed_human_review_required"
        else:
            conclusion = "record_values_differ_human_review_required"
    evidence = {"approval_id": approval_id, "state": state["state"],
                "provider_id": identity, "conclusion": conclusion,
                "request_hash": state["approval"].payload_hash,
                "lead_match_count": len(identities),
                "contact_match_count": len(set(contact_search) | set(contact_scan))}
    store.audit(category="phase7_lead_create_reconciliation_v1", action="read_only",
                actor="automation-engine", success=False, target=approval_id,
                metadata=evidence)
    return evidence
