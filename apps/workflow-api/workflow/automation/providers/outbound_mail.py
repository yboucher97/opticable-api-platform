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
from ..outbound_approval import OutboundApprovalLedger, POLICY_VERSION, _email, validate_text


_INTERNAL_DOMAINS = {"opticable.ca", "opti-plex.ca"}
_SEND_FIELDS = {"approval_id", "action_type", "source_type", "source_id", "source_version",
                "mailbox_account_id", "message_id", "from_address", "to_address",
                "subject", "content", "mail_format"}


def _provider_message_id(response):
    if not isinstance(response, dict) or response.get("ok") is not True or response.get("status") not in {200, 201}:
        return None
    outer = response.get("data")
    if not isinstance(outer, dict):
        return None
    status = outer.get("status")
    if not isinstance(status, dict) or status.get("code") not in {200, 201}:
        return None
    data = outer.get("data")
    if not isinstance(data, dict):
        return None
    # Only the expected Mail message identity slot is recognized. Generic
    # IDs and partial envelopes are not proof that this send was accepted.
    identity = data.get("messageId")
    if isinstance(identity, str) and re.fullmatch(r"[0-9]{1,30}", identity):
        return identity
    return None


def register_outbound_mail_action(engine, client, store):
    ledger = OutboundApprovalLedger(store)

    def send(context, step):
        if os.environ.get("OPTIBRAIN_OUTBOUND_SENDS") != POLICY_VERSION:
            return {"sent": False, "reason": "observe"}
        request = step.inputs.get("send")
        if not isinstance(request, dict) or set(request) - _SEND_FIELDS:
            raise ValueError("lifecycle.mail_send_approved_v2 requires with.send object")

        approval_id = request.get("approval_id")
        action_type = request.get("action_type")
        source_type = request.get("source_type")
        source_id = request.get("source_id")
        source_version = request.get("source_version")
        account_id = request.get("mailbox_account_id")
        message_id = request.get("message_id")
        from_address = _email(request.get("from_address"))
        recipient = _email(request.get("to_address"))
        subject, content = validate_text(request.get("subject"), request.get("content"))
        mail_format = request.get("mail_format", "plaintext")

        if action_type not in {"send_new_email", "reply_email"}:
            raise ValueError("Invalid outbound action type")
        if source_type not in {"lead", "message", "draft"}:
            raise ValueError("Invalid outbound source type")
        if not isinstance(account_id, str) or not re.fullmatch(r"[0-9]{1,30}", account_id):
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
            if not isinstance(message_id, str) or not re.fullmatch(r"[0-9]{1,30}", message_id):
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
                ledger.require_consuming(approval)
                if os.environ.get("OPTIBRAIN_OUTBOUND_SENDS") != POLICY_VERSION:
                    ledger.mark_manual(approval, error="policy_disabled")
                    return {"sent": False, "reason": "observe", "approval_state": "manual"}
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
                ledger.mark_consumed(
                    approval, provider_operation_id=operation, request_id=response.get("request_id"),
                )
            except Exception:
                try:
                    ledger.mark_manual(approval, error="provider_unconfirmed")
                except Exception:
                    # A failed journal finalization must not hide the ambiguous
                    # classification. The durable consuming/consumed marker
                    # still permanently prevents another automatic send.
                    pass
                raise ZohoWriteUnconfirmedError(
                    "Outbound mail outcome requires human reconciliation; approval cannot be reused"
                ) from None
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
