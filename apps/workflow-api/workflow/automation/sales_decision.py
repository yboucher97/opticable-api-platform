"""Pure Phase 6 sales decision policy.

This module performs no provider access and authorizes no provider mutation.
It converts a reviewed Lead snapshot plus optional advisory AI hints into a
bounded, deterministic internal sales decision.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from .event_schema import canonical, digest

POLICY_VERSION = "phase6-sales-v1"
TORONTO = ZoneInfo("America/Toronto")

ACTIVE_STATUSES = {
    "Not Contacted",
    "Attempted to Contact",
    "Contact in Future",
    "Pre-Qualified",
}

# This is deliberately a small internal taxonomy. A service value can be
# written only when a trusted non-AI intake layer supplies both an exact value
# and reviewed evidence category. AI hints never populate Service_Types.
TRUSTED_SERVICE_TYPES = {
    "Structured Cabling",
    "Commercial Wi-Fi",
    "Network Infrastructure",
    "IP Cameras",
    "Access Control",
    "Intercom",
    "Alarm",
    "IP Telephony",
    "AI Loss Prevention",
    "Fiber",
    "Point-to-Point",
    "Jobsite Wi-Fi",
    "Jobsite Cameras",
}
TRUSTED_SERVICE_EVIDENCE = {
    "explicit_customer_selection",
    "validated_intake",
}

Priority = Literal["low", "normal", "high", "urgent"]
NextAction = Literal[
    "review",
    "call",
    "draft_reply",
    "site_visit",
    "quote_review",
    "wait",
]
Language = Literal["fr", "en", "unknown"]
ServiceTypeSource = Literal["existing", "trusted_hint"]

_PRIORITY_ORDER = {
    "low": 0,
    "normal": 1,
    "high": 2,
    "urgent": 3,
}
_ALLOWED_ACTIONS = {
    "review",
    "call",
    "draft_reply",
    "site_visit",
    "quote_review",
    "wait",
}
_ALLOWED_LANGUAGES = {"fr", "en", "unknown"}


class SalesDecision(BaseModel):
    """Payload-safe sales decision derived from one exact Lead version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lead_id: str
    version: str
    active: bool
    converted: bool
    contactable: bool
    email_contactable: bool
    email_opt_out: bool
    service_type: str | None
    service_type_source: ServiceTypeSource | None
    language: Language
    priority: Priority
    next_action: NextAction
    missing_information: list[str]
    followup_at: str | None
    policy_version: str = POLICY_VERSION
    decision_hash: str


def _aware(value: Any, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _optional_aware(value: Any, *, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    return _aware(value, field=field)


def _next_business_date(start, days: int):
    current = start
    remaining = max(0, int(days))
    if remaining == 0:
        while current.weekday() >= 5:
            current += timedelta(days=1)
        return current
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def business_due(now: datetime, business_days: int) -> datetime:
    """Return a deterministic Toronto-business-day deadline in UTC.

    Deadlines land at 17:00 America/Toronto. A same-day deadline requested
    after 17:00, or on a weekend, rolls to the next business day.
    """

    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    local = now.astimezone(TORONTO)
    date = local.date()

    if business_days <= 0:
        if date.weekday() >= 5 or local.timetz().replace(tzinfo=None) >= time(17, 0):
            date += timedelta(days=1)
            while date.weekday() >= 5:
                date += timedelta(days=1)
    else:
        date = _next_business_date(date, business_days)

    return datetime.combine(date, time(17, 0), tzinfo=TORONTO).astimezone(timezone.utc)


def _safe_language(record: dict[str, Any], hint: dict[str, Any]) -> Language:
    raw = str(
        record.get("Preferred_Language")
        or record.get("Language")
        or hint.get("language")
        or "unknown"
    ).strip().lower()
    return raw if raw in _ALLOWED_LANGUAGES else "unknown"  # type: ignore[return-value]


def _safe_hint_priority(hint: dict[str, Any]) -> Priority | None:
    value = str(hint.get("priority") or "").strip().lower()
    return value if value in _PRIORITY_ORDER else None  # type: ignore[return-value]


def _safe_hint_action(hint: dict[str, Any]) -> NextAction | None:
    value = str(hint.get("recommended_next_action") or "").strip().lower()
    return value if value in _ALLOWED_ACTIONS else None  # type: ignore[return-value]


def _safe_service_type(
    record: dict[str, Any],
    trusted_service_hint: dict[str, Any],
) -> tuple[str | None, ServiceTypeSource | None]:
    existing = str(record.get("Service_Types") or "").strip()
    if existing:
        return existing, "existing"

    value = str(trusted_service_hint.get("value") or "").strip()
    evidence = str(trusted_service_hint.get("evidence") or "").strip()
    if value in TRUSTED_SERVICE_TYPES and evidence in TRUSTED_SERVICE_EVIDENCE:
        return value, "trusted_hint"
    return None, None


def _base_priority(status: str, *, stale: bool, age_seconds: float) -> Priority:
    if status == "Pre-Qualified":
        return "high"
    if stale and age_seconds >= 172800:
        return "high"
    if stale:
        return "normal"
    if status == "Contact in Future":
        return "low"
    return "normal"


def _safe_action(
    status: str,
    *,
    email_contactable: bool,
    phone_contactable: bool,
    explicit_future: bool,
    hint: NextAction | None,
) -> NextAction:
    if explicit_future:
        return "wait"

    allowed = {"review", "wait"}
    if email_contactable:
        allowed.add("draft_reply")
    if phone_contactable:
        allowed.add("call")
    if status == "Pre-Qualified":
        allowed.update({"quote_review", "site_visit"})

    if hint in allowed:
        return hint
    if status == "Pre-Qualified":
        return "quote_review"
    if email_contactable:
        return "draft_reply"
    if phone_contactable:
        return "call"
    return "review"


def _decision_hash(value: dict[str, Any]) -> str:
    return digest([POLICY_VERSION, canonical(value)])


def validate_sales_decision(value: dict[str, Any] | SalesDecision) -> SalesDecision:
    """Validate the complete immutable decision envelope and its hash."""

    decision = value if isinstance(value, SalesDecision) else SalesDecision.model_validate(value)
    if decision.policy_version != POLICY_VERSION:
        raise ValueError("Unsupported sales decision policy")
    safe = decision.model_dump(exclude={"decision_hash"})
    if decision.decision_hash != _decision_hash(safe):
        raise ValueError("Sales decision hash mismatch")
    return decision


def build_sales_decision(
    record: dict[str, Any],
    *,
    ai_hint: dict[str, Any] | None = None,
    trusted_service_hint: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> SalesDecision:
    """Build one deterministic decision from one reviewed Lead snapshot.

    `ai_hint` is advisory only. Unknown values are discarded and an AI action
    can be selected only when deterministic contactability/state gates permit it.
    `trusted_service_hint` is a separate non-AI evidence channel; an AI response
    cannot fill Service_Types merely by naming a service or reporting confidence.
    """

    identity = str(record.get("id") or "")
    if not re.fullmatch(r"[0-9]{1,30}", identity):
        raise ValueError("Invalid lead id")

    version_dt = _aware(record.get("Modified_Time"), field="Modified_Time")
    created_dt = _aware(
        record.get("Created_Time") or record.get("Modified_Time"),
        field="Created_Time",
    )
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("now must include a timezone")

    hint = ai_hint if isinstance(ai_hint, dict) else {}
    service_hint = trusted_service_hint if isinstance(trusted_service_hint, dict) else {}
    status = str(record.get("Lead_Status") or "").strip()
    converted = record.get("Converted__s") is True
    active = not converted and status in ACTIVE_STATUSES

    email = str(record.get("Email") or "").strip()
    phone = str(record.get("Phone") or record.get("Mobile") or "").strip()
    email_opt_out = record.get("Email_Opt_Out") is True
    email_contactable = bool(active and email and "@" in email and not email_opt_out)
    phone_contactable = bool(active and phone)
    contactable = email_contactable or phone_contactable

    age_seconds = max(0.0, (clock - created_dt.astimezone(timezone.utc)).total_seconds())
    stale = active and age_seconds >= 86400

    existing_followup = _optional_aware(
        record.get("Next_Followup_At"),
        field="Next_Followup_At",
    )
    future_followup = bool(active and existing_followup and existing_followup > clock)
    explicit_future = bool(status == "Contact in Future" and future_followup)

    language = _safe_language(record, hint)
    priority: Priority = _base_priority(status, stale=stale, age_seconds=age_seconds) if active else "low"
    hint_priority = _safe_hint_priority(hint)
    if active and hint_priority and _PRIORITY_ORDER[hint_priority] > _PRIORITY_ORDER[priority]:
        priority = hint_priority

    if not active:
        action: NextAction = "wait"
        followup = None
    else:
        action = _safe_action(
            status,
            email_contactable=email_contactable,
            phone_contactable=phone_contactable,
            explicit_future=explicit_future,
            hint=_safe_hint_action(hint),
        )
        if future_followup:
            # An existing explicit future timestamp is provider-owned state.
            # Preserve it instead of shifting the SLA on every notification.
            followup = existing_followup
        else:
            cadence = {
                "urgent": 0,
                "high": 1,
                "normal": 2,
                "low": 2,
            }[priority]
            followup = business_due(clock, cadence)

    service_type, service_type_source = _safe_service_type(record, service_hint)
    missing = []
    if not service_type:
        missing.append("service_type")
    if not contactable and active:
        missing.append("contact_method")
    if not str(record.get("City") or record.get("State") or "").strip():
        missing.append("location")

    safe = {
        "lead_id": identity,
        "version": version_dt.astimezone(timezone.utc).isoformat(),
        "active": active,
        "converted": converted,
        "contactable": contactable,
        "email_contactable": email_contactable,
        "email_opt_out": email_opt_out,
        "service_type": service_type,
        "service_type_source": service_type_source,
        "language": language,
        "priority": priority,
        "next_action": action,
        "missing_information": missing,
        "followup_at": followup.astimezone(timezone.utc).isoformat() if followup else None,
        "policy_version": POLICY_VERSION,
    }
    safe["decision_hash"] = _decision_hash(safe)
    return SalesDecision.model_validate(safe)
