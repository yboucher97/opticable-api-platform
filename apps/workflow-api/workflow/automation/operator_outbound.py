"""Authoritative read-only source hydration for Phase 6 outbound approvals.

A browser or workflow never supplies recipient, sender, subject or body authority.
Those values are reconstructed from one immutable reviewed Lead event plus fresh
provider reads. Draft-ID-only approval remains unsupported until a readback
contract is separately proven.
"""
from __future__ import annotations

from email.utils import parseaddr
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .event_schema import digest
from .events import EventLedger
from .outbound_approval import _email, _internal, validate_text
from .providers.crm_leads import FIELDS, _utc_iso, records
from .providers.sales_drafts import TEMPLATES
from .sales_decision import ACTIVE_STATUSES, validate_sales_decision


class OutboundCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_event_id: str
    lead_id: str
    action_type: Literal["send_new_email", "reply_email"]
    source_type: Literal["lead", "message"]
    source_id: str
    source_version: str
    account_id: str
    message_id: str | None = None
    recipient: str
    from_address: str
    subject: str
    content: str
    candidate_hash: str


class AuthoritativeOutboundResolver:
    """Reconstruct exact outbound content without trusting caller payload fields."""

    def __init__(self, client, store, *, account_id: str, from_address: str) -> None:
        account = str(account_id or "")
        if not re.fullmatch(r"[0-9]{1,30}", account):
            raise ValueError("invalid configured outbound mailbox account")
        sender = _email(from_address)
        if _internal(sender) is not True:
            raise ValueError("configured outbound sender must be Opticable-owned")
        self.client = client
        self.store = store
        self.account_id = account
        self.from_address = sender
        self.events = EventLedger(store)

    @staticmethod
    def _provider_data(response: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(response, dict) or response.get("ok") is not True or response.get("status") != 200:
            raise ValueError("authoritative provider read failed")
        outer = response.get("data")
        if not isinstance(outer, dict):
            raise ValueError("authoritative provider response malformed")
        status = outer.get("status")
        if isinstance(status, dict) and status.get("code") != 200:
            raise ValueError("authoritative provider response not successful")
        data = outer.get("data")
        if not isinstance(data, dict):
            raise ValueError("authoritative provider data missing")
        return data

    @staticmethod
    def _header_message_id(response: dict[str, Any]) -> str:
        data = AuthoritativeOutboundResolver._provider_data(response)
        header = data.get("headerContent")
        if not isinstance(header, dict):
            raise ValueError("mail header response must be JSON format")
        values = header.get("Message-Id") or header.get("Message-ID") or header.get("Message-id")
        if not isinstance(values, list) or len(values) != 1:
            raise ValueError("mail Internet Message-ID unavailable")
        value = str(values[0] or "").strip()
        if not re.fullmatch(r"<[^<>\s]{1,250}@[^<>\s]{1,250}>", value):
            raise ValueError("mail Internet Message-ID invalid")
        return value

    @staticmethod
    def _candidate_hash(value: dict[str, Any]) -> str:
        safe = {
            "review_event_id": value["review_event_id"],
            "lead_id": value["lead_id"],
            "action_type": value["action_type"],
            "source_type": value["source_type"],
            "source_id": value["source_id"],
            "source_version": value["source_version"],
            "account_id": value["account_id"],
            "message_id": value.get("message_id"),
            "recipient": value["recipient"],
            "from_address": value["from_address"],
            "subject_hash": digest(value["subject"]),
            "content_hash": digest(value["content"]),
        }
        return digest(safe)

    def _review(self, review_event_id: str) -> tuple[dict[str, Any], dict[str, Any], Any]:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", str(review_event_id or "")):
            raise ValueError("invalid reviewed Lead event id")
        captured = self.events.inspect(review_event_id)
        if captured is None:
            raise ValueError("reviewed Lead event not found")
        envelope = captured["envelope"]
        if envelope.get("source") != "crm-lead-observer" or envelope.get("event_type") != "opticable.crm.lead.reviewed":
            raise ValueError("outbound approval requires an internal reviewed Lead event")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("reviewed Lead payload missing")
        decision = validate_sales_decision(payload.get("sales_decision"))
        if str(payload.get("lead_id") or "") != decision.lead_id:
            raise ValueError("reviewed Lead identity mismatch")
        return captured, payload, decision

    def _lead(self, lead_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]{1,30}", lead_id):
            raise ValueError("invalid Lead identity")
        response = self.client.request(
            "zohoapis",
            "GET",
            "/crm/v8/Leads/" + lead_id,
            query={"fields": FIELDS},
        )
        rows = records(response)
        if len(rows) != 1 or str(rows[0].get("id") or "") != lead_id:
            raise ValueError("authoritative Lead identity mismatch")
        return rows[0]

    def _message_binding(self, payload: dict[str, Any], *, lead_id: str, recipient: str, version: str):
        event_id = str(payload.get("message_event_id") or "")
        expected_hash = str(payload.get("message_content_hash") or "")
        if not event_id and not expected_hash:
            return None
        if not event_id or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError("reviewed message binding is incomplete")
        captured = self.events.inspect(event_id)
        if captured is None or captured.get("content_hash") != expected_hash:
            raise ValueError("reviewed message evidence changed")
        envelope = captured["envelope"]
        if envelope.get("source") != "zoho-mail-poller" or envelope.get("event_type") != "customer.lifecycle.email.received":
            raise ValueError("reviewed message source is not authoritative mailbox intake")
        email = envelope.get("payload")
        if not isinstance(email, dict):
            raise ValueError("reviewed message payload missing")
        account_id = str(email.get("mailbox_account_id") or "")
        mailbox = _email(email.get("mailbox_address"))
        sender = _email(email.get("sender_email"))
        message_id = str(email.get("message_id") or "")
        folder_id = str(email.get("folder_id") or "")
        if account_id != self.account_id or mailbox != self.from_address or sender != recipient:
            raise ValueError("reviewed message mailbox/recipient binding mismatch")
        if not re.fullmatch(r"[0-9]{1,30}", message_id) or not re.fullmatch(r"[0-9]{1,30}", folder_id):
            raise ValueError("reviewed message provider identity invalid")

        details = self._provider_data(self.client.request(
            "mail", "GET",
            f"/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/details",
        ))
        if str(details.get("messageId") or "") != message_id or str(details.get("folderId") or "") != folder_id:
            raise ValueError("live mailbox message identity drift")
        live_sender = _email(parseaddr(str(details.get("fromAddress") or ""))[1])
        if live_sender != recipient:
            raise ValueError("live mailbox sender drift")

        internet_id = self._header_message_id(self.client.request(
            "mail", "GET",
            f"/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/header",
            query={"raw": "false"},
        ))
        source_id = f"message:{lead_id}:{payload.get('review_event_id') or ''}:{event_id}"
        # The caller-facing review id is filled by resolve(); this temporary
        # identity is replaced there before hashing.
        return {
            "event_id": event_id,
            "message_id": message_id,
            "internet_message_id": internet_id,
            "content_hash": captured["content_hash"],
            "source_version": digest([version, captured["content_hash"], internet_id]),
        }

    def resolve(self, review_event_id: str) -> OutboundCandidate:
        _, payload, decision = self._review(review_event_id)
        lead = self._lead(decision.lead_id)
        version = _utc_iso(lead.get("Modified_Time"))
        if version != decision.version:
            raise ValueError("Lead changed after reviewed decision")
        status = str(lead.get("Lead_Status") or "").strip()
        if lead.get("Converted__s") is not False or status not in ACTIVE_STATUSES:
            raise ValueError("Lead is converted or inactive")
        if lead.get("Email_Opt_Out") is not False:
            raise ValueError("Lead email consent is opted out or unknown")
        recipient = _email(lead.get("Email"))
        if _internal(recipient):
            raise ValueError("customer outbound recipient cannot be internal")
        if (not decision.active or decision.converted or decision.email_opt_out
                or not decision.email_contactable or decision.next_action != "draft_reply"):
            raise ValueError("reviewed sales decision does not authorize a draft reply candidate")
        if decision.language not in TEMPLATES:
            raise ValueError("reviewed language must be fr or en")
        subject, content = validate_text(*TEMPLATES[decision.language])

        message = self._message_binding(payload, lead_id=decision.lead_id, recipient=recipient, version=version)
        if message is None:
            value = {
                "review_event_id": review_event_id,
                "lead_id": decision.lead_id,
                "action_type": "send_new_email",
                "source_type": "lead",
                "source_id": f"lead:{decision.lead_id}:{review_event_id}",
                "source_version": version,
                "account_id": self.account_id,
                "message_id": None,
                "recipient": recipient,
                "from_address": self.from_address,
                "subject": subject,
                "content": content,
            }
        else:
            value = {
                "review_event_id": review_event_id,
                "lead_id": decision.lead_id,
                "action_type": "reply_email",
                "source_type": "message",
                "source_id": f"message:{decision.lead_id}:{review_event_id}:{message['event_id']}",
                "source_version": message["source_version"],
                "account_id": self.account_id,
                "message_id": message["message_id"],
                "recipient": recipient,
                "from_address": self.from_address,
                "subject": subject,
                "content": content,
            }
        value["candidate_hash"] = self._candidate_hash(value)
        return OutboundCandidate.model_validate(value)

    def resolve_approval_source(self, *, source_type: str, source_id: str) -> OutboundCandidate:
        value = str(source_id or "")
        if source_type == "lead":
            match = re.fullmatch(r"lead:([0-9]{1,30}):([A-Za-z0-9._:-]{8,128})", value)
        elif source_type == "message":
            match = re.fullmatch(r"message:([0-9]{1,30}):([A-Za-z0-9._:-]{8,128}):([A-Za-z0-9._:-]{8,128})", value)
        else:
            raise ValueError("draft source readback is not verified for Gate F")
        if not match:
            raise ValueError("invalid authoritative outbound source identity")
        lead_id, review_event_id = match.group(1), match.group(2)
        candidate = self.resolve(review_event_id)
        if candidate.lead_id != lead_id or candidate.source_type != source_type or candidate.source_id != value:
            raise ValueError("authoritative outbound source changed")
        return candidate
