"""Read-only Zoho Mail readiness verification for Phase 6 Gate F."""
from __future__ import annotations

import re

from .outbound_approval import _email


def verify_mailbox_readiness(client, *, account_id: str, from_address: str) -> dict:
    account = str(account_id or "")
    if not re.fullmatch(r"[0-9]{1,30}", account):
        raise ValueError("invalid mailbox account id")
    sender = _email(from_address)
    response = client.request("mail", "GET", f"/api/accounts/{account}")
    if not isinstance(response, dict) or response.get("ok") is not True or response.get("status") != 200:
        raise ValueError("mailbox account read failed")
    outer = response.get("data")
    if not isinstance(outer, dict):
        raise ValueError("mailbox account response malformed")
    status = outer.get("status")
    if isinstance(status, dict) and status.get("code") != 200:
        raise ValueError("mailbox account provider status failed")
    data = outer.get("data")
    if not isinstance(data, dict) or str(data.get("accountId") or "") != account:
        raise ValueError("mailbox account identity mismatch")
    if data.get("enabled") is not True or data.get("status") is not True:
        raise ValueError("mailbox account is not enabled")
    if data.get("mailboxStatus") != "enabled":
        raise ValueError("mailbox is not enabled")
    if data.get("outgoingBlocked") is not False or data.get("smtpStatus") is not True:
        raise ValueError("mailbox outbound transport is blocked")

    addresses = data.get("emailAddress")
    if not isinstance(addresses, list):
        raise ValueError("mailbox address inventory missing")
    confirmed = set()
    for item in addresses:
        if not isinstance(item, dict) or item.get("isConfirmed") is not True:
            continue
        try:
            confirmed.add(_email(item.get("mailId")))
        except ValueError:
            continue

    send_details = data.get("sendMailDetails")
    if not isinstance(send_details, list):
        raise ValueError("mailbox send alias inventory missing")
    active_from = set()
    for item in send_details:
        if not isinstance(item, dict) or item.get("status") is not True:
            continue
        try:
            active_from.add(_email(item.get("fromAddress")))
        except ValueError:
            continue

    if sender not in confirmed and sender not in active_from:
        raise ValueError("configured sender is not a verified mailbox address")
    if sender not in active_from:
        raise ValueError("configured sender is not an active send-from identity")

    return {
        "result": "PASS",
        "account_id": account,
        "from_address": sender,
        "mailbox_enabled": True,
        "outgoing_blocked": False,
        "smtp_ready": True,
        "confirmed_address": sender in confirmed,
        "active_send_alias": True,
        "provider_writes": 0,
    }
