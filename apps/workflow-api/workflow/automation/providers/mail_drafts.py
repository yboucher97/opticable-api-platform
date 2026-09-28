"""Shared Zoho Mail draft transport. This operation can never send."""
from __future__ import annotations

import re


def save_mail_draft(client, account_id, payload):
    allowed = {"mode", "fromAddress", "toAddress", "subject", "content", "mailFormat", "inReplyTo"}
    if (not re.fullmatch(r"[0-9]{1,30}", str(account_id))
            or payload.get("mode") != "draft" or set(payload) - allowed):
        raise ValueError("Invalid draft-only request")
    return client.request(
        "mail", "POST", f"/api/accounts/{account_id}/messages",
        body=payload, reason="Customer lifecycle: save reply as Zoho Mail draft", confirm=True,
    )
