from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


_WHITESPACE_RE = re.compile(r"\s+")
_PHONE_RE = re.compile(r"[^0-9+]")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE_RE.sub(" ", str(value)).strip()
    return cleaned or None


def normalize_email(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.lower() if cleaned else None


def normalize_phone(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    normalized = _PHONE_RE.sub("", cleaned)
    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]
    if normalized.count("+") > 1 or ("+" in normalized and not normalized.startswith("+")):
        normalized = normalized.replace("+", "")
    return normalized or None


def split_name(full_name: str | None) -> tuple[str | None, str | None]:
    cleaned = _clean(full_name)
    if not cleaned:
        return None, None
    parts = cleaned.split(" ", 1)
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], parts[1]


class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    medium: str | None = None
    campaign: str | None = None
    campaign_id: str | None = None
    term: str | None = None
    content: str | None = None
    landing_url: str | None = None
    referrer: str | None = None
    site: str | None = None
    gclid: str | None = None
    gbraid: str | None = None
    wbraid: str | None = None
    fbclid: str | None = None
    fbp: str | None = None
    fbc: str | None = None
    visitor_id: str | None = None


class LeadIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = Field(min_length=1, max_length=128)
    source_record_id: str | None = Field(default=None, max_length=255)
    inquiry_id: str | None = Field(default=None, max_length=255)
    occurred_at: str | None = None

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None

    service_type: str | None = None
    message: str | None = None
    language: str | None = None

    street: str | None = None
    city: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    country: str | None = None

    attribution: Attribution = Field(default_factory=Attribution)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_identity(self) -> "LeadIntakeRequest":
        if not any(
            _clean(value)
            for value in (
                self.first_name,
                self.last_name,
                self.full_name,
                self.company,
                self.email,
                self.phone,
                self.mobile,
            )
        ):
            raise ValueError("Lead intake requires at least a name, company, email, or phone number.")
        return self


def normalize_lead(payload: dict[str, Any]) -> dict[str, Any]:
    request = LeadIntakeRequest.model_validate(payload)

    first_name = _clean(request.first_name)
    last_name = _clean(request.last_name)
    if not first_name and not last_name and request.full_name:
        first_name, last_name = split_name(request.full_name)

    email = normalize_email(request.email)
    phone = normalize_phone(request.phone)
    mobile = normalize_phone(request.mobile)

    # Zoho Leads requires Last_Name. Prefer an actual name, then company, then
    # an email/phone-derived stable label rather than inventing personal data.
    if not last_name:
        last_name = (
            _clean(request.company)
            or (email.split("@", 1)[0] if email and "@" in email else email)
            or phone
            or mobile
            or "Unknown lead"
        )

    occurred_at = _clean(request.occurred_at) or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    attr = request.attribution

    normalized = {
        "source": _clean(request.source),
        "source_record_id": _clean(request.source_record_id),
        "inquiry_id": _clean(request.inquiry_id),
        "occurred_at": occurred_at,
        "first_name": first_name,
        "last_name": last_name,
        "company": _clean(request.company),
        "email": email,
        "phone": phone,
        "mobile": mobile,
        "service_type": _clean(request.service_type),
        "message": _clean(request.message),
        "language": _clean(request.language),
        "address": {
            "street": _clean(request.street),
            "city": _clean(request.city),
            "state_province": _clean(request.state_province),
            "postal_code": _clean(request.postal_code),
            "country": _clean(request.country),
        },
        "attribution": {
            "source": _clean(attr.source),
            "medium": _clean(attr.medium),
            "campaign": _clean(attr.campaign),
            "campaign_id": _clean(attr.campaign_id),
            "term": _clean(attr.term),
            "content": _clean(attr.content),
            "landing_url": _clean(attr.landing_url),
            "referrer": _clean(attr.referrer),
            "site": _clean(attr.site),
            "gclid": _clean(attr.gclid),
            "gbraid": _clean(attr.gbraid),
            "wbraid": _clean(attr.wbraid),
            "fbclid": _clean(attr.fbclid),
            "fbp": _clean(attr.fbp),
            "fbc": _clean(attr.fbc),
            "visitor_id": _clean(attr.visitor_id),
        },
        "metadata": request.metadata,
    }

    stable_identity = "|".join(
        str(value or "")
        for value in (
            normalized["inquiry_id"],
            normalized["source_record_id"],
            normalized["email"],
            normalized["phone"],
            normalized["mobile"],
            normalized["company"],
        )
    )
    normalized["identity_hash"] = hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()
    return normalized


def lead_event_idempotency_key(payload: dict[str, Any]) -> str | None:
    request = LeadIntakeRequest.model_validate(payload)
    if request.inquiry_id:
        return f"lead:{request.source}:inquiry:{request.inquiry_id}"
    if request.source_record_id:
        return f"lead:{request.source}:record:{request.source_record_id}"
    return None


class EmailIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = "zoho_mail"
    mailbox_account_id: str = Field(min_length=1, max_length=64)
    mailbox_address: str = Field(min_length=3, max_length=320)
    message_id: str = Field(min_length=1, max_length=255)
    folder_id: str | None = Field(default=None, max_length=255)
    thread_id: str | None = Field(default=None, max_length=255)
    internet_message_id: str | None = Field(default=None, max_length=1000)
    received_at: str | None = None
    sender_name: str | None = None
    sender_email: str = Field(min_length=3, max_length=320)
    subject: str | None = Field(default=None, max_length=1000)
    body: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MeetingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    start_datetime: str
    end_datetime: str
    description: str | None = None
    venue: str | None = Field(default=None, max_length=255)
    contact_id: str | None = Field(default=None, max_length=64)
    deal_id: str | None = Field(default=None, max_length=64)
    source: str = Field(default="opticable", min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_window(self) -> "MeetingRequest":
        start = datetime.fromisoformat(self.start_datetime.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.end_datetime.replace("Z", "+00:00"))
        if start >= end:
            raise ValueError("end_datetime must be after start_datetime")
        return self


def email_event_idempotency_key(payload: dict[str, Any]) -> str:
    request = EmailIntakeRequest.model_validate(payload)
    return f"email:{request.mailbox_account_id}:{request.message_id}"
