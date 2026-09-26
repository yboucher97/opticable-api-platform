from __future__ import annotations

from typing import Any

from .automation.models import AutomationEvent
from .automation.store import AutomationStore
from .universal_inbox_dry_run import classify_message


SAFE_EVENT_TYPE = "universal_inbox.classified"
SAFE_SOURCE = "zoho_mail"


def _message_identity(message: dict[str, Any]) -> str:
    thread_id = str(message.get("threadId") or "").strip()
    message_id = str(message.get("messageId") or "").strip()
    if thread_id:
        return f"thread:{thread_id}"
    if message_id:
        return f"message:{message_id}"
    raise ValueError("Message must include messageId or threadId for safe deduplication.")


def observe_message(store: AutomationStore, message: dict[str, Any]) -> dict[str, Any]:
    """Persist a classification observation only; never mutate mail, CRM, or Books."""
    decision = classify_message(message).to_dict()
    identity = _message_identity(message)

    if decision.get("mutate_mail") or decision.get("mutate_crm") or decision.get("books_write"):
        raise RuntimeError("Unsafe classifier decision rejected by live-safe observer.")

    payload = {
        "mode": "observe_only",
        "identity": identity,
        "message": {
            "messageId": message.get("messageId"),
            "threadId": message.get("threadId"),
            "fromAddress": message.get("fromAddress"),
            "toAddress": message.get("toAddress"),
            "subject": message.get("subject"),
        },
        "decision": decision,
        "safety": {
            "mail_mutations": False,
            "outbound_send": False,
            "crm_mutations": False,
            "books_mutations": False,
        },
    }

    event = AutomationEvent(
        event_type=SAFE_EVENT_TYPE,
        source=SAFE_SOURCE,
        idempotency_key=f"universal-inbox:{identity}",
        correlation_id=identity,
        payload=payload,
    )
    accepted, event_id, correlation_id = store.ingest_event(event)
    store.audit(
        category="universal_inbox",
        action="observe_classification" if accepted else "observe_duplicate",
        actor="live-safe-observer",
        success=True,
        correlation_id=correlation_id,
        target=identity,
        metadata={
            "category": decision.get("category"),
            "confidence": decision.get("confidence"),
            "accepted": accepted,
            "mode": "observe_only",
        },
    )
    return {
        "accepted": accepted,
        "duplicate": not accepted,
        "event_id": event_id,
        "correlation_id": correlation_id,
        "decision": decision,
        "mode": "observe_only",
    }


def observe_batch(store: AutomationStore, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [observe_message(store, message) for message in messages]
