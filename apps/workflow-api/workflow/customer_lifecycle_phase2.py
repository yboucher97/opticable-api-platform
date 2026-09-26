from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class QuoteReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_id: str = Field(min_length=1, max_length=64)
    contact_id: str | None = Field(default=None, max_length=64)
    account_id: str | None = Field(default=None, max_length=64)
    service_summary: str = Field(min_length=1, max_length=4000)
    requested_by: str = Field(default="opticable", min_length=1, max_length=128)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    notes: str | None = Field(default=None, max_length=12000)


class ContractSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: Literal["general_terms", "installation"]
    recipient_name: str = Field(min_length=1, max_length=255)
    recipient_email: EmailStr
    request_name: str = Field(min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    deal_id: str | None = Field(default=None, max_length=64)
    service_id: str | None = Field(default=None, max_length=64)
    field_text_data: dict[str, str] = Field(default_factory=dict)
    field_date_data: dict[str, str] = Field(default_factory=dict)
    approved_to_send: bool = False

    @model_validator(mode="after")
    def require_explicit_approval(self) -> "ContractSendRequest":
        if not self.approved_to_send:
            raise ValueError("approved_to_send must be true before a contract can be sent for signature.")
        return self


class BooksObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(default="802337532", min_length=1, max_length=64)
    include_invoices: bool = True
    include_estimates: bool = True
    include_payments: bool = True
    customer_id: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1, le=10000)
    per_page: int = Field(default=100, ge=1, le=200)


class DigestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Literal["daily", "weekly"] = "daily"
    organization_id: str = Field(default="802337532", min_length=1, max_length=64)
    mailbox_account_id: str = Field(default="1083319000000008002", min_length=1, max_length=64)
    from_address: EmailStr = "yboucher@opticable.ca"
    recipient: EmailStr = "yboucher@opticable.ca"
    create_mail_draft: bool = True
    extra_context: dict[str, Any] = Field(default_factory=dict)
