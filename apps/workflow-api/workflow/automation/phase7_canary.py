"""Pure, fail-closed preparation for one explicitly approved Phase 7 canary.

The plan is advisory. It never creates provider IDs, folders, approvals, writes,
or messages. A live executor must independently rehydrate the Lead and prove the
same version, identity evidence, exact proposed mutation, and human approval.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from .event_schema import digest
from .providers.crm_leads import _utc_iso, phase6_lead_patch
from .providers.crm_leads import FIELDS, records
from .providers.sales_drafts import TEMPLATES
from .outbound_approval import _email, _internal, validate_text
from .sales_decision import SalesDecision, build_sales_decision


POLICY = "phase7-single-canary-v1"
_CRM_ID = re.compile(r"[0-9]{1,30}\Z")
_SCORE = {"low": 20, "normal": 50, "high": 75, "urgent": 90}
_FOLDERS = ("00-intake", "10-discovery", "20-site", "30-design", "40-quote", "50-delivery")


class IdentityEvidence(BaseModel):
    """A read-only CRM search result; the caller must authenticate its origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    lead_id: str
    source_version: str
    matching_lead_ids: tuple[str, ...]
    query_hash: str


def hydrate_unique_lead(client, lead_id: str) -> tuple[dict[str, Any], IdentityEvidence]:
    """Read one Lead and an exact-email search; never infer uniqueness from fuzzy hits.

    Zoho Search can return fuzzy matches and may lag writes. More pages, empty
    responses, or other exact-email IDs require human review. This function
    performs GETs only and never confers write authority.
    """
    if not isinstance(lead_id, str) or not _CRM_ID.fullmatch(lead_id):
        raise ValueError("Invalid existing Lead ID")
    read = client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}",
                          query={"fields": FIELDS + ",Company"})
    rows = records(read)
    if len(rows) != 1 or str(rows[0].get("id") or "") != lead_id:
        raise ValueError("Lead hydration identity mismatch")
    lead = rows[0]
    version = _utc_iso(lead.get("Modified_Time"))
    email = str(lead.get("Email") or "").strip().casefold()
    if not email or "@" not in email or lead.get("Email_Opt_Out") is not False:
        raise ValueError("Canary Lead has no confirmed contactable email")
    search = client.request("zohoapis", "GET", "/crm/v8/Leads/search",
                            query={"email": email, "fields": "id,Email", "per_page": 200, "page": 1})
    hits = records(search)
    outer = search.get("data") or {}
    info = outer.get("info")
    if not isinstance(info, dict) or info.get("more_records") is not False:
        raise ValueError("Lead search pagination is incomplete")
    matches = tuple(sorted(str(hit.get("id") or "") for hit in hits
                           if str(hit.get("Email") or "").strip().casefold() == email))
    if matches != (lead_id,):
        raise ValueError("Exact-email Lead identity is ambiguous or not indexed")
    proof = IdentityEvidence(lead_id=lead_id, source_version=version,
                             matching_lead_ids=matches,
                             query_hash=digest(["zoho-crm-v8-email", email, matches, version]))
    return lead, proof


class CanaryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy: str
    lead_id: str
    source_version: str
    source_hash: str
    identity_hash: str
    dedupe_query_hash: str
    dedupe_status: str
    client_ref: str
    contact_ref: str
    company_ref: str | None
    site_ref: str
    project_ref: str
    crm_contact_id: str | None
    crm_account_id: str | None
    crm_deal_id: str | None
    folder_paths: tuple[str, ...]
    qualification_score: int
    next_action: str
    language: str
    followup_at: str | None
    crm_patch: dict[str, Any]
    crm_patch_hash: str
    outbound_eligible: bool
    decision_hash: str
    plan_hash: str

    def audit_evidence(self) -> dict[str, Any]:
        """Return IDs/hashes only; no email, phone, subject, body or patch values."""
        return self.model_dump(exclude={"crm_patch", "folder_paths"})


class CanaryReviewPackage(BaseModel):
    """Human-visible exact proposal; never persist this raw object in audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    policy: str
    lead_id: str
    source_version: str
    plan_hash: str
    crm_before: dict[str, Any]
    crm_after: dict[str, Any]
    crm_patch_hash: str
    account_id: str
    reviewed_language: str
    sender: str
    recipient: str
    subject: str
    content: str
    subject_hash: str
    content_hash: str
    package_hash: str

    def audit_evidence(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "lead_id": self.lead_id,
            "source_version": self.source_version,
            "plan_hash": self.plan_hash,
            "crm_patch_hash": self.crm_patch_hash,
            "account_id": self.account_id,
            "reviewed_language": self.reviewed_language,
            "sender_hash": digest(self.sender),
            "recipient_hash": digest(self.recipient),
            "subject_hash": self.subject_hash,
            "content_hash": self.content_hash,
            "package_hash": self.package_hash,
        }


def _provider_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _CRM_ID.fullmatch(value):
        raise ValueError("Invalid existing CRM relationship ID")
    return value


def build_canary_plan(
    record: dict[str, Any],
    evidence: IdentityEvidence,
    *,
    now: datetime,
    ai_hint: dict[str, Any] | None = None,
) -> CanaryPlan:
    """Bind a bounded plan to one exact reviewed, deduplicated Lead snapshot."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Canary clock must be timezone-aware")
    lead_id = str(record.get("id") or "")
    if not _CRM_ID.fullmatch(lead_id):
        raise ValueError("Canary requires an existing numeric Zoho Lead ID")
    version = _utc_iso(record.get("Modified_Time"))
    if evidence.lead_id != lead_id or evidence.source_version != version:
        raise ValueError("Identity evidence does not match exact Lead version")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.query_hash):
        raise ValueError("Missing read-only identity query hash")
    matches = evidence.matching_lead_ids
    if not matches or len(matches) != len(set(matches)) or any(not _CRM_ID.fullmatch(x) for x in matches):
        raise ValueError("Identity search result is incomplete or malformed")
    if matches != (lead_id,):
        raise ValueError("Lead identity is ambiguous; human dedupe review required")

    bounded_hint = {key: value for key, value in (ai_hint if isinstance(ai_hint, dict) else {}).items()
                    if key != "language"}
    decision: SalesDecision = build_sales_decision(record, ai_hint=bounded_hint, now=now)
    if not decision.active or decision.converted:
        raise ValueError("Canary requires an active, unconverted Lead")
    patch = phase6_lead_patch(record, decision)
    # Provisional references survive later Lead versions. Version/dedupe proof
    # remain separately bound to the plan hash and must be re-reviewed.
    identity_hash = digest([POLICY, lead_id])
    # These are provisional internal references. Never present them as Zoho IDs.
    suffix = identity_hash[:12].upper()
    client_ref = f"OB-C-{suffix}"
    contact_ref = f"OB-P-{suffix}"
    company_ref = f"OB-O-{suffix}" if str(record.get("Company") or "").strip() else None
    site_ref = f"OB-S-{suffix}"
    project_ref = f"OB-J-{suffix}"
    root = f"leads/{lead_id}/{project_ref}"
    folders = tuple(f"{root}/{name}" for name in _FOLDERS)
    value = {
        "policy": POLICY,
        "lead_id": lead_id,
        "source_version": version,
        "source_hash": digest(record),
        "identity_hash": identity_hash,
        "dedupe_query_hash": evidence.query_hash,
        "dedupe_status": "unique_lead_email_match",
        "client_ref": client_ref,
        "contact_ref": contact_ref,
        "company_ref": company_ref,
        "site_ref": site_ref,
        "project_ref": project_ref,
        "crm_contact_id": _provider_id(record.get("Contact_Id")),
        "crm_account_id": _provider_id(record.get("Account_Id")),
        "crm_deal_id": _provider_id(record.get("Deal_Id")),
        "folder_paths": folders,
        "qualification_score": _SCORE[decision.priority],
        "next_action": decision.next_action,
        "language": decision.language,
        "followup_at": decision.followup_at,
        "crm_patch": patch,
        "crm_patch_hash": digest(patch),
        "outbound_eligible": bool(decision.email_contactable and decision.language in {"fr", "en"}
                                  and decision.next_action == "draft_reply"),
        "decision_hash": decision.decision_hash,
    }
    value["plan_hash"] = digest(value)
    return CanaryPlan.model_validate(value)


def build_review_package(
    plan: CanaryPlan,
    record: dict[str, Any],
    *,
    account_id: str,
    from_address: str,
    reviewed_language: str | None = None,
) -> CanaryReviewPackage:
    """Prepare exact CRM/email review values without issuing approval or sending."""
    if plan.policy != POLICY or str(record.get("id") or "") != plan.lead_id:
        raise ValueError("Canary plan identity changed")
    if _utc_iso(record.get("Modified_Time")) != plan.source_version or digest(record) != plan.source_hash:
        raise ValueError("Canary Lead version changed")
    # A human may explicitly choose a bounded language when CRM has no trusted
    # language field. AI hints cannot supply this parameter through the planner.
    language = reviewed_language if reviewed_language is not None else plan.language
    if reviewed_language is not None and plan.language in TEMPLATES and reviewed_language != plan.language:
        raise ValueError("Human language selection conflicts with reviewed Lead language")
    if (plan.next_action != "draft_reply" or language not in TEMPLATES
            or (reviewed_language is None and not plan.outbound_eligible)):
        raise ValueError("Canary outbound review is not eligible")
    if not isinstance(account_id, str) or not _CRM_ID.fullmatch(account_id):
        raise ValueError("Configured mailbox account ID required")
    sender = _email(from_address)
    recipient = _email(record.get("Email"))
    if sender.rsplit("@", 1)[1] != "opticable.ca" or _internal(recipient):
        raise ValueError("Owned sender and external customer recipient required")
    if record.get("Email_Opt_Out") is not False:
        raise ValueError("Explicit non-opt-out state required")
    subject, content = validate_text(*TEMPLATES[language])
    before = {key: record.get(key) for key in plan.crm_patch}
    after = {**before, **plan.crm_patch}
    value = {
        "policy": POLICY, "lead_id": plan.lead_id,
        "source_version": plan.source_version, "plan_hash": plan.plan_hash,
        "crm_before": before, "crm_after": after,
        "crm_patch_hash": plan.crm_patch_hash,
        "account_id": account_id, "reviewed_language": language,
        "sender": sender, "recipient": recipient,
        "subject": subject, "content": content,
        "subject_hash": digest(subject), "content_hash": digest(content),
    }
    value["package_hash"] = digest(value)
    return CanaryReviewPackage.model_validate(value)
