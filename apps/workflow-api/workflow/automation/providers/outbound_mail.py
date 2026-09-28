"""Phase 6 outbound mail consumption.

This action cannot issue approvals. It consumes one exact, unexpired approval,
records consuming state before the network call, and never retries an ambiguous
send. Production remains disabled unless OPTIBRAIN_OUTBOUND_SENDS explicitly
selects the Phase 6 policy.
"""
from __future__ import annotations

import os
import re

from ...zoho_gateway import ZohoWriteUnconfirmedError
from ..outbound_approval import OutboundApprovalLedger, POLICY_VERSION


_INTERNAL_DOMAINS = {"opticable.ca", "opti-plex.ca"}
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")


def _email(value):
    cleaned = str(value or "").strip().lower()
    if len(cleaned) > 254 or not _EMAIL.fullmatch(cleaned):
        raise ValueError("Invalid outbound email address")
    return cleaned


def _provider_message_id(response):
    if not isinstance(response, dict) or response.get("ok") is not True or response.get("status") not in {200, 201}:
        return None
    outer = response.get("data")
    if not isinstance(outer, dict):
        return None
    status = outer.get("status")
    if isinstance(status, dict) and status.get("code") not in {200, 201}:
        return None
    data = outer.get("data")
    candidates = []
    if isinstance(data, dict):
        candidates.extend([data.get("messageId"), data.get("message_id"), data.get("id")])
    candidates.extend([outer.get("messageId"), outer.get("message_id"), outer.get("id")])
    for value in candidates:
        identity = str(value or "").strip()
        if re.fullmatch(r"[0-9]{1,30}", identity):
            return identity
    return None


def register_outbound_mail_action(engine, client, store):
    ledger = OutboundApprovalLedger(store)

    def send(context, step):
        if os.environ.get("OPTIBRAIN_OUTBOUND_SENDS") != POLICY_VERSION:
            return {"sent": False, "reason": "observe"}
        request = step.inputs.get("send")
        if not isinstance(request, dict):
            raise ValueError("lifecycle.mail_send_approved_v2 requires with.send object")

        approval_id = str(request.get("approval_id") or "").strip()
        action_type = str(request.get("action_type") or "").strip()
        source_type = str(request.get("source_type") or "").strip()
        source_id = str(request.get("source_id") or "").strip()
        source_version = str(request.get("source_version") or "").strip()
        account_id = str(request.get("mailbox_account_id") or "").strip()
        message_id = str(request.get("message_id") or "").strip() or None
        from_address = _email(request.get("from_address"))
        recipient = _email(request.get("to_address"))
        subject = str(request.get("subject") or "").strip()
        content = str(request.get("content") or "").strip()
        mail_format = str(request.get("mail_format") or "plaintext").strip().lower()

        if action_type not in {"send_new_email", "reply_email"}:
            raise ValueError("Invalid outbound action type")
        if source_type not in {"lead", "message", "draft"}:
            raise ValueError("Invalid outbound source type")
        if not re.fullmatch(r"[0-9]{1,30}", account_id):
            raise ValueError("Invalid outbound mailbox account")
        if from_address.rsplit("@", 1)[1] not in _INTERNAL_DOMAINS:
            raise ValueError("Outbound sender must be Opticable-owned")
        if recipient.rsplit("@", 1)[1] in _INTERNAL_DOMAINS:
            raise ValueError("Customer outbound action cannot target an internal domain")
        if not subject or len(subject) > 500 or not content or len(content) > 12000:
            raise ValueError("Outbound subject/content are missing or out of bounds")
        if mail_format != "plaintext":
            raise ValueError("Phase 6 outbound mail is plaintext only")
        if action_type == "reply_email":
            if not message_id or not re.fullmatch(r"[0-9]{1,30}", message_id):
                raise ValueError("reply_email requires numeric message_id")
        elif message_id is not None:
            raise ValueError("send_new_email must not include message_id")

        expected = ledger.expected(
            approval_id=approval_id,
            action_type=action_type,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
            account_id=account_id,
            message_id=message_id,
            recipient=recipient,
            from_address=from_address,
            subject=subject,
            content=content,
        )

        with ledger.lock():
            approval = ledger.require_issued(expected)
            # Re-read policy immediately before making the approval single-use.
            if os.environ.get("OPTIBRAIN_OUTBOUND_SENDS") != POLICY_VERSION:
                return {"sent": False, "reason": "observe"}
            ledger.mark_consuming(approval)
            # A process loss after this durable marker is intentionally
            # human-required. It must never be transformed into a second send.
            try:
                body = {
                    "fromAddress": from_address,
                    "toAddress": recipient,
                    "subject": subject,
                    "content": content,
                    "mailFormat": "plaintext",
                }
                if action_type == "reply_email":
                    body["action"] = "reply"
                    path = f"/api/accounts/{account_id}/messages/{message_id}"
                else:
                    path = f"/api/accounts/{account_id}/messages"
                response = client.request(
                    "mail",
                    "POST",
                    path,
                    body=body,
                    reason="Phase 6: explicitly approved single-use outbound email",
                    confirm=True,
                )
                operation = _provider_message_id(response)
                if operation is None:
                    raise ZohoWriteUnconfirmedError("Outbound mail acknowledgement is unconfirmed")
            except Exception as exc:
                ledger.mark_manual(approval, error=type(exc).__name__)
                raise ZohoWriteUnconfirmedError(
                    "Outbound mail outcome requires human reconciliation; approval cannot be reused"
                ) from None
            ledger.mark_consumed(
                approval,
                provider_operation_id=operation,
                request_id=response.get("request_id"),
            )
            event = context.get("event") or {}
            return {
                "sent": True,
                "approval_id": approval.approval_id,
                "action_type": action_type,
                "source_id": source_id,
                "provider_operation_id": operation,
                "correlation_id": event.get("correlation_id") or event.get("event_id"),
            }

    engine.register_action("lifecycle.mail_send_approved_v2", send)  # Never retry an outbound send.
