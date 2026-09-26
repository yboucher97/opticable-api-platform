from __future__ import annotations

from typing import Any

from ...universal_inbox_live_safe import observe_message
from ..engine import AutomationEngine
from ..store import AutomationStore


def register_universal_inbox_actions(engine: AutomationEngine, store: AutomationStore) -> None:
    def observe(context: dict[str, Any], step: Any) -> dict[str, Any]:
        message = step.inputs.get("message")
        if not isinstance(message, dict):
            raise ValueError("universal_inbox.observe requires with.message object.")
        normalized = {
            "messageId": message.get("message_id") or message.get("messageId"),
            "threadId": message.get("thread_id") or message.get("threadId"),
            "fromAddress": message.get("sender_email") or message.get("fromAddress"),
            "toAddress": (message.get("metadata") or {}).get("to_address") or message.get("toAddress"),
            "ccAddress": (message.get("metadata") or {}).get("cc_address") or message.get("ccAddress"),
            "subject": message.get("subject"),
            "summary": (message.get("metadata") or {}).get("summary") or message.get("summary"),
            "content": message.get("body") or message.get("content"),
        }
        result = observe_message(store, normalized)
        result["mail_mutations"] = 0
        result["crm_mutations"] = 0
        result["books_mutations"] = 0
        result["outbound_sends"] = 0
        return result

    engine.register_action("universal_inbox.observe", observe)
