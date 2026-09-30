"""Bounded, read-only Mail evidence for the one controlled Lead follow-up."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
import re
from zoneinfo import ZoneInfo


SENT_FOLDER_ID = "1083319000000008022"
CONTROLLED_MESSAGE_ID = "1790714949014155100"
TORONTO = ZoneInfo("America/Toronto")
_MESSAGE_ID = re.compile(r"<[^<>\s]{1,250}@[^<>\s]{1,250}>")


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Mail evidence timestamp requires an offset")
    return parsed


def local(value: datetime | str) -> str:
    stamp = aware(value) if isinstance(value, str) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Mail display timestamp requires an offset")
    return stamp.astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z")


def _epoch_millis(value) -> datetime:
    try:
        millis = int(str(value))
        if not 0 < millis < 32503680000000:
            raise ValueError
        return datetime.fromtimestamp(millis / 1000, timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Mail receipt timestamp is unavailable") from exc


def _data(response, expected_type):
    if not isinstance(response, dict) or response.get("ok") is not True or response.get("status") != 200:
        raise ValueError("Authoritative Mail read failed")
    outer = response.get("data")
    if not isinstance(outer, dict) or not isinstance(outer.get("status"), dict) or outer["status"].get("code") != 200:
        raise ValueError("Mail response status is ambiguous")
    value = outer.get("data")
    if not isinstance(value, expected_type):
        raise ValueError("Mail response shape is ambiguous")
    return value


def _addresses(value: str) -> tuple[str, ...]:
    return tuple(address.casefold() for _, address in getaddresses([unescape(str(value or ""))]) if address)


def _headers(response) -> dict[str, str]:
    header = _data(response, dict).get("headerContent")
    if not isinstance(header, dict):
        raise ValueError("Mail headers are unavailable")
    result = {}
    for key, values in header.items():
        if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str):
            result[key.casefold()] = values[0].strip()
    return result


def _message_id(value: str) -> str:
    cleaned = str(value or "").strip()
    if not _MESSAGE_ID.fullmatch(cleaned):
        raise ValueError("Mail Internet Message-ID is unavailable")
    return cleaned


def _plain_body(response) -> str:
    payload = _data(response, dict)
    nested = payload.get("content")
    value = nested.get("content") if isinstance(nested, dict) else nested
    if not isinstance(value, str):
        raise ValueError("Mail content is unavailable")
    value = re.sub(r"(?i)<br\s*/?>|</p>", "\n", value)
    value = unescape(re.sub(r"<[^>]*>", " ", value)).replace("\r", "")
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith(">") or re.match(r"(?i)on .{5,120} wrote:$|[- ]*original message[- ]*", stripped):
            break
        lines.append(stripped)
    return "\n".join(lines).strip()[:4000]


def _new_information(body: str) -> list[str]:
    """Only lift explicit labelled facts; they remain unconfirmed until reviewed."""
    names = {"service": "Service", "site address": "Site address",
             "camera count": "Camera count", "timeline": "Timeline"}
    found = []
    for line in body.splitlines()[:30]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().casefold()
        value = value.strip()[:120]
        if key in names and value and len(value) >= 2:
            found.append(f"{names[key]}: {value} (from reply; verify)")
    return found[:4]


def read_controlled_mail(client, *, account_id: str, from_address: str,
                         recipient: str, prior_outbound: dict | None,
                         now: datetime) -> dict:
    """GET the known Sent message, then search exact sender and bind replies by headers."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Mail read clock requires an offset")
    if not re.fullmatch(r"[0-9]{1,30}", str(account_id or "")):
        raise ValueError("Mail account identity invalid")
    if not prior_outbound or prior_outbound.get("recorded_sends") != 1:
        return {"reply_state": "AMBIGUOUS", "reason": "A unique approved outbound send is unavailable",
                "last_outbound": None, "last_inbound": None, "new_information": [], "search_complete": False}
    item = prior_outbound["latest"]
    if (item.get("provider_message_id") != CONTROLLED_MESSAGE_ID
            or item.get("account_id") != account_id
            or item.get("from_address", "").casefold() != from_address.casefold()):
        return {"reply_state": "AMBIGUOUS", "reason": "Approved outbound identity differs from the controlled Mail account",
                "last_outbound": None, "last_inbound": None, "new_information": [], "search_complete": False}
    base = f"/api/accounts/{account_id}/folders/{SENT_FOLDER_ID}/messages/{CONTROLLED_MESSAGE_ID}"
    sent = _data(client.request("mail", "GET", base + "/details"), dict)
    if (str(sent.get("messageId")) != CONTROLLED_MESSAGE_ID
            or str(sent.get("folderId")) != SENT_FOLDER_ID
            or _addresses(sent.get("fromAddress")) != (from_address.casefold(),)
            or _addresses(sent.get("toAddress")) != (recipient.casefold(),)):
        raise ValueError("Known Sent message identity changed")
    header = _headers(client.request("mail", "GET", base + "/header", query={"raw": "false"}))
    internet_id = _message_id(header.get("message-id"))
    try:
        sent_header_time = parsedate_to_datetime(header.get("date", ""))
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("Sent header Date is invalid") from exc
    if sent_header_time is None or sent_header_time.tzinfo is None or sent_header_time.utcoffset() is None:
        raise ValueError("Sent header Date has no timezone")
    sent_receipt = _epoch_millis(sent.get("receivedTime") or sent.get("receivedtime"))
    audit_time = aware(item["sent_at_iso"])
    if (abs((sent_header_time - sent_receipt).total_seconds()) > 120
            or abs((audit_time - sent_receipt).total_seconds()) > 120
            or sent_receipt > now + timedelta(minutes=2)):
        raise ValueError("Sent time evidence disagrees")
    outbound = {"message_id": CONTROLLED_MESSAGE_ID, "internet_message_id": internet_id,
                "sent_at": sent_receipt.isoformat(), "sent_at_local": local(sent_receipt),
                "recipient": recipient, "subject": str(sent.get("subject") or "")[:200],
                "provider_sent_date_disagrees": False}
    if sent.get("sentDateInGMT"):
        outbound["provider_sent_date_disagrees"] = abs((_epoch_millis(sent["sentDateInGMT"]) - sent_receipt).total_seconds()) > 120

    start_day = sent_receipt.astimezone(TORONTO).strftime("%d-%b-%Y")
    end_day = (now.astimezone(TORONTO) + timedelta(days=1)).strftime("%d-%b-%Y")
    search_key = f"sender:{recipient}::fromDate:{start_day}::toDate:{end_day}::inclspamtrash:true"
    candidates = []
    for page in range(5):
        rows = _data(client.request("mail", "GET", f"/api/accounts/{account_id}/messages/search",
                                    query={"searchKey": search_key, "start": page * 200,
                                           "limit": 200, "receivedTime": int(now.timestamp() * 1000)}), list)
        candidates.extend(rows)
        if len(rows) < 200:
            break
    else:
        return {"reply_state": "AMBIGUOUS", "reason": "Mail search exceeded its bounded page limit",
                "last_outbound": outbound, "last_inbound": None, "new_information": [], "search_complete": False}

    inbound = []
    ambiguous = False
    seen_ids = set()
    for row in candidates:
        if not isinstance(row, dict) or _addresses(row.get("fromAddress")) != (recipient.casefold(),):
            ambiguous = True
            continue
        message_id = str(row.get("messageId") or "")
        folder_id = str(row.get("folderId") or "")
        if (not re.fullmatch(r"[0-9]{1,30}", message_id)
                or not re.fullmatch(r"[0-9]{1,30}", folder_id)
                or message_id in seen_ids):
            ambiguous = True
            continue
        seen_ids.add(message_id)
        try:
            received = _epoch_millis(row.get("receivedTime") or row.get("receivedtime"))
        except ValueError:
            ambiguous = True
            continue
        if received <= sent_receipt:
            continue
        if folder_id == SENT_FOLDER_ID or received > now + timedelta(minutes=2):
            ambiguous = True
            continue
        path = f"/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}"
        details = _data(client.request("mail", "GET", path + "/details"), dict)
        if (str(details.get("messageId")) != message_id or str(details.get("folderId")) != folder_id
                or _addresses(details.get("fromAddress")) != (recipient.casefold(),)
                or from_address.casefold() not in _addresses(details.get("toAddress"))):
            ambiguous = True
            continue
        try:
            details_received = _epoch_millis(details.get("receivedTime") or details.get("receivedtime"))
        except ValueError:
            ambiguous = True
            continue
        if abs((details_received - received).total_seconds()) > 120:
            ambiguous = True
            continue
        headers = _headers(client.request("mail", "GET", path + "/header", query={"raw": "false"}))
        reply_ids = _MESSAGE_ID.findall(headers.get("in-reply-to", "") + " " + headers.get("references", ""))
        if internet_id not in reply_ids:
            ambiguous = True
            continue
        body = _plain_body(client.request("mail", "GET", path + "/content"))
        inbound.append({"message_id": message_id, "received_at": received.isoformat(),
                        "received_at_local": local(received), "summary": re.sub(r"\s+", " ", body)[:220],
                        "new_information": _new_information(body)})
    if ambiguous:
        return {"reply_state": "AMBIGUOUS", "reason": "Incoming Mail identity or thread linkage needs human review",
                "last_outbound": outbound, "last_inbound": None,
                "new_information": [], "search_complete": True}
    latest = max(inbound, key=lambda item: aware(item["received_at"])) if inbound else None
    return {"reply_state": "REPLIED" if latest else "NO_REPLY_YET",
            "reason": "Reply headers reference the known outbound message" if latest else "No exact-sender inbound found after the known outbound",
            "last_outbound": outbound, "last_inbound": latest,
            "new_information": latest["new_information"] if latest else [], "search_complete": True}


def followup_status(mail: dict, *, deadline: datetime | None, now: datetime,
                    crm_modified: datetime, active: bool) -> str:
    """A missed deadline alone never proves a neglected Lead."""
    if mail["reply_state"] == "AMBIGUOUS" or deadline is None or not active:
        return "AMBIGUOUS"
    if mail["reply_state"] == "REPLIED":
        return "REPLIED — REVIEW RESPONSE"
    sent = aware(mail["last_outbound"]["sent_at"])
    if now < deadline or now - sent < timedelta(hours=24):
        return "WAIT"
    if now - deadline < timedelta(hours=24) or now - crm_modified < timedelta(hours=24):
        return "DUE"
    return "OVERDUE"
