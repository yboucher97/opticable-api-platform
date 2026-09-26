from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ...universal_inbox_live_safe import observe_message
from ...zoho_gateway import ZohoGatewayClient
from ..engine import AutomationEngine
from ..models import AutomationEvent, WorkflowStep
from ..store import AutomationStore

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_INTERNAL_DOMAINS = {"opticable.ca", "opti-plex.ca"}
_SENT_FOLDER_ID = "1083319000000008022"


def _provider_data(response: dict[str, Any]) -> Any:
    return response.get("data")


def _mail_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = _provider_data(response)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _message_content(response: dict[str, Any]) -> str:
    data = _provider_data(response)
    if not isinstance(data, dict):
        return ""
    nested = data.get("content")
    if isinstance(nested, dict):
        value = nested.get("content")
        return str(value or "")
    if isinstance(nested, str):
        return nested
    value = data.get("messageContent") or data.get("body")
    return str(value or "")


def _plain_body(value: str) -> str:
    text = str(value or "")
    if "<" in text and ">" in text:
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = _HTML_TAG_RE.sub(" ", text)
        text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sender_domain(address: str) -> str:
    value = str(address or "").strip().lower()
    if "<" in value and ">" in value:
        value = value.rsplit("<", 1)[-1].split(">", 1)[0].strip()
    if "@" not in value:
        return ""
    return value.rsplit("@", 1)[-1]


def _iso_from_epoch_millis(value: Any) -> str | None:
    try:
        millis = int(str(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_observer_message(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return {
        "messageId": message.get("message_id") or message.get("messageId"),
        "threadId": message.get("thread_id") or message.get("threadId"),
        "fromAddress": message.get("sender_email") or message.get("fromAddress"),
        "toAddress": metadata.get("to_address") or message.get("toAddress"),
        "ccAddress": metadata.get("cc_address") or message.get("ccAddress"),
        "subject": message.get("subject"),
        "summary": metadata.get("summary") or message.get("summary"),
        "content": message.get("body") or message.get("content"),
    }


def register_lifecycle_mailbox_actions(
    engine: AutomationEngine,
    client: ZohoGatewayClient,
    store: AutomationStore,
) -> None:
    def poll_mailbox(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        account_id = str(step.inputs.get("account_id") or "1083319000000008002").strip()
        mailbox_address = str(step.inputs.get("mailbox_address") or "yboucher@opticable.ca").strip().lower()
        window_days = max(1, min(7, int(step.inputs.get("window_days") or 2)))
        limit = max(1, min(100, int(step.inputs.get("limit") or 100)))
        internal_domains = {
            str(item).strip().lower()
            for item in (step.inputs.get("internal_domains") or sorted(_INTERNAL_DOMAINS))
            if str(item).strip()
        }
        if not account_id or "@" not in mailbox_address:
            raise ValueError("Mailbox polling requires account_id and mailbox_address.")

        toronto = ZoneInfo("America/Toronto")
        today = datetime.now(toronto).date()
        start = today - timedelta(days=window_days)
        search_key = f"fromDate:{start.strftime('%d-%b-%Y')}::toDate:{today.strftime('%d-%b-%Y')}"
        response = client.request(
            "mail",
            "GET",
            f"/api/accounts/{account_id}/messages/search",
            query={"searchKey": search_key, "start": 0, "limit": limit},
        )
        rows = _mail_rows(response)
        parent = AutomationEvent.model_validate(context["event"])

        scanned = 0
        skipped_internal = 0
        skipped_sent = 0
        skipped_empty = 0
        accepted = 0
        duplicates = 0
        failed = 0
        child_event_ids: list[str] = []

        for item in rows:
            scanned += 1
            message_id = str(item.get("messageId") or "").strip()
            folder_id = str(item.get("folderId") or "").strip()
            sender_email = str(item.get("fromAddress") or "").strip().lower()
            if not message_id or not folder_id or not sender_email:
                skipped_empty += 1
                continue
            if folder_id == _SENT_FOLDER_ID:
                skipped_sent += 1
                continue
            if _sender_domain(sender_email) in internal_domains:
                skipped_internal += 1
                continue

            try:
                content_response = client.request(
                    "mail",
                    "GET",
                    f"/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/content",
                )
                body = _plain_body(_message_content(content_response))
                if not body:
                    body = str(item.get("summary") or "").strip()
                if not body:
                    skipped_empty += 1
                    continue

                payload = {
                    "source": "zoho_mail",
                    "mailbox_account_id": account_id,
                    "mailbox_address": mailbox_address,
                    "message_id": message_id,
                    "folder_id": folder_id,
                    "thread_id": str(item.get("threadId") or "").strip() or None,
                    "received_at": _iso_from_epoch_millis(item.get("receivedTime")),
                    "sender_name": str(item.get("sender") or "").strip() or None,
                    "sender_email": sender_email,
                    "subject": str(item.get("subject") or "").strip() or None,
                    "body": body,
                    "metadata": {
                        "summary": str(item.get("summary") or "")[:4000],
                        "to_address": str(item.get("toAddress") or "")[:2000],
                        "cc_address": str(item.get("ccAddress") or "")[:2000],
                        "has_attachment": str(item.get("hasAttachment") or "0"),
                        "priority": str(item.get("priority") or ""),
                        "search_key": search_key,
                    },
                }
                child = AutomationEvent(
                    event_type="customer.lifecycle.email.received",
                    source="zoho-mail-poller",
                    correlation_id=parent.correlation_id or parent.event_id,
                    causation_id=parent.event_id,
                    idempotency_key=f"email:{account_id}:{message_id}",
                    depth=parent.depth + 1,
                    payload=payload,
                )
                result = engine.ingest(child)
                child_event_ids.append(result.event_id)
                if result.duplicate:
                    duplicates += 1
                else:
                    accepted += 1
            except Exception as exc:
                failed += 1
                store.audit(
                    category="customer_lifecycle",
                    action="mailbox_message_ingest_failed",
                    actor="automation-engine",
                    success=False,
                    correlation_id=parent.correlation_id or parent.event_id,
                    target=message_id,
                    metadata={"error": type(exc).__name__, "folder_id": folder_id},
                )

        return {
            "account_id": account_id,
            "search_key": search_key,
            "scanned": scanned,
            "accepted": accepted,
            "duplicates": duplicates,
            "skipped_internal": skipped_internal,
            "skipped_sent": skipped_sent,
            "skipped_empty": skipped_empty,
            "failed": failed,
            "child_event_ids": child_event_ids,
            "mailbox_mutations": 0,
        }

    def observe_universal_inbox(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        message = step.inputs.get("message")
        if not isinstance(message, dict):
            raise ValueError("universal_inbox.observe requires with.message object.")
        result = observe_message(store, _normalized_observer_message(message))
        result.update({"mail_mutations": 0, "crm_mutations": 0, "books_mutations": 0, "outbound_sends": 0})
        return result

    def send_approved_reply(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        reply = step.inputs.get("reply")
        if not isinstance(reply, dict):
            raise ValueError("lifecycle.mail_reply_approved requires with.reply object.")
        if reply.get("approved_to_send") is not True:
            raise ValueError("Email reply send requires approved_to_send=true.")

        account_id = str(reply.get("mailbox_account_id") or "").strip()
        message_id = str(reply.get("message_id") or "").strip()
        from_address = str(reply.get("from_address") or "").strip().lower()
        to_address = str(reply.get("to_address") or "").strip().lower()
        subject = str(reply.get("subject") or "").strip()
        content = str(reply.get("content") or "").strip()
        if not account_id or not message_id or "@" not in from_address or "@" not in to_address or not content:
            raise ValueError("Approved reply requires mailbox_account_id, message_id, from/to addresses, and content.")
        if _sender_domain(from_address) not in _INTERNAL_DOMAINS:
            raise ValueError("Reply from_address must use an Opticable-owned domain.")

        body = {
            "fromAddress": from_address,
            "toAddress": to_address,
            "subject": subject,
            "content": content,
            "action": "reply",
            "mailFormat": str(reply.get("mail_format") or "plaintext"),
        }
        response = client.request(
            "mail",
            "POST",
            f"/api/accounts/{account_id}/messages/{message_id}",
            body=body,
            reason="Customer lifecycle: explicitly approved reply to existing customer email",
            confirm=True,
        )
        event = context.get("event") or {}
        store.audit(
            category="customer_lifecycle",
            action="approved_email_reply_sent",
            actor="automation-engine",
            success=True,
            correlation_id=event.get("correlation_id") or event.get("event_id"),
            target=message_id,
            metadata={"to": to_address, "from": from_address},
        )
        return {
            "sent": True,
            "message_id": message_id,
            "to_address": to_address,
            "provider_status": response.get("status"),
        }

    engine.register_action("lifecycle.mailbox_poll", poll_mailbox)
    engine.register_action("universal_inbox.observe", observe_universal_inbox)
    engine.register_action("lifecycle.mail_reply_approved", send_approved_reply)
