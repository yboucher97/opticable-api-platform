"""Provider-specific verification of bounded deliveries, before normalization."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .events import EventLedger, MAX_EVENT_BYTES
from .event_schema import digest
from .models import AutomationEvent


class WebhookError(ValueError):
    def __init__(self, category: str, status: int = 401) -> None:
        super().__init__(category)
        self.category = category
        self.status = status


class WebhookEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["github", "zoho_crm", "google_calendar", "google_drive", "cloudflare", "signed_relay"]
    source_account: str = Field(min_length=1, max_length=255)
    secret_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    allowed_event_types: list[str] = Field(min_length=1, max_length=100)
    channel_id: str | None = Field(default=None, max_length=128)
    resource_id: str | None = Field(default=None, max_length=255)
    sync_stream: str | None = Field(default=None, max_length=255)
    expires_at: str | None = None
    max_body_bytes: int = Field(default=262_144, ge=1024, le=MAX_EVENT_BYTES)
    replay_window_seconds: int = Field(default=300, ge=30, le=86400)
    enabled: bool = False


def load_endpoints(path: Path | None = None) -> dict[str, WebhookEndpoint]:
    selected = path or Path(os.getenv("OPTIBRAIN_WEBHOOK_CONFIG", "config/automation/webhooks.yaml"))
    if not selected.exists():
        return {}
    if selected.stat().st_size > 65536:
        raise WebhookError("configuration_unavailable", 503)
    raw = yaml.safe_load(selected.read_text()) or {}
    if not isinstance(raw, dict) or len(raw) > 100:
        raise WebhookError("configuration_unavailable", 503)
    result = {}
    for name, value in raw.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", str(name)):
            raise WebhookError("configuration_unavailable", 503)
        result[name] = WebhookEndpoint.model_validate(value)
    return result


def _json(raw: bytes) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid number")))
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise WebhookError("malformed_json", 400) from None


def _equal(actual: Any, expected: str) -> None:
    if not isinstance(actual, str) or not hmac.compare_digest(actual.encode(), expected.encode()):
        raise WebhookError("verification_failed")


def _window(timestamp: datetime, now: datetime, seconds: int) -> None:
    if abs((now - timestamp).total_seconds()) > seconds:
        raise WebhookError("timestamp_outside_window")


def verify_delivery(endpoint: WebhookEndpoint, headers: dict[str, str], raw: bytes,
                    *, now: datetime | None = None) -> tuple[AutomationEvent, str | None]:
    if not endpoint.enabled:
        raise WebhookError("endpoint_disabled", 503)
    secret = os.getenv(endpoint.secret_env, "")
    if len(secret.encode()) < 32 or not secret.strip():
        raise WebhookError("verification_unavailable", 503)
    if len(raw) > endpoint.max_body_bytes:
        raise WebhookError("body_too_large", 413)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("verification clock must include timezone")
    if endpoint.expires_at:
        expiry = datetime.fromisoformat(endpoint.expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= now:
            raise WebhookError("channel_expired", 401)
    provider = endpoint.provider
    if provider not in {"google_calendar", "google_drive"} and headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise WebhookError("unsupported_content_type", 415)
    data: dict[str, Any]
    evidence: dict[str, Any] = {}
    timestamp: str | None = None
    native: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    version = 1
    if provider == "github":
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        _equal(headers.get("x-hub-signature-256"), signature)
        # No documented signed timestamp. Durable body and delivery dedupe are
        # used; no invented freshness header is required from GitHub.
        data = _json(raw)
        try:
            native = str(UUID(headers.get("x-github-delivery", "")))
        except ValueError:
            raise WebhookError("invalid_delivery_identity", 400) from None
        kind = headers.get("x-github-event", "")
        if not re.fullmatch(r"[a-z_]{1,64}", kind):
            raise WebhookError("invalid_event_type", 400)
        event_type = "github." + kind
        repo = data.get("repository") or {}
        if not isinstance(repo, dict):
            raise WebhookError("invalid_provider_record", 422)
        if endpoint.resource_id and str(repo.get("id", "")) != endpoint.resource_id:
            raise WebhookError("resource_mismatch", 401)
        subject_type, subject_id = "repository", str(repo.get("id", "")) or None
        if isinstance(data.get("head_commit"), dict):
            timestamp = data["head_commit"].get("timestamp")
        evidence = {"delivery_id": native, "raw_sha256": hashlib.sha256(raw).hexdigest()}
    elif provider == "zoho_crm":
        data = _json(raw)
        _equal(data.get("token"), secret)
        if not endpoint.channel_id:
            raise WebhookError("channel_unconfigured", 503)
        _equal(str(data.get("channel_id", "")), endpoint.channel_id)
        server_time = data.get("server_time")
        if not isinstance(server_time, int) or isinstance(server_time, bool):
            raise WebhookError("invalid_timestamp", 400)
        try:
            when = datetime.fromtimestamp(server_time / 1000, timezone.utc)
        except (ValueError, OverflowError, OSError):
            raise WebhookError("invalid_timestamp", 400) from None
        _window(when, now, endpoint.replay_window_seconds)
        timestamp = when.isoformat()
        module, operation = data.get("module"), data.get("operation")
        ids = data.get("ids")
        if (not isinstance(module, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", module)
                or operation not in {"insert", "update", "delete"} or not isinstance(ids, list)
                or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) or not i.isdigit() for i in ids)):
            raise WebhookError("invalid_provider_record", 422)
        event_type = f"zoho.crm.{module}.{operation}"
        subject_type = module
        subject_id = ids[0] if len(ids) == 1 else None
        evidence = {"channel_id": endpoint.channel_id, "server_time": server_time, "module": module, "operation": operation}
        # Token and arbitrary URL query parameters are authentication material.
        data = {key: data[key] for key in ("module", "operation", "ids", "server_time", "affected_fields") if key in data}
    elif provider in {"google_calendar", "google_drive"}:
        _equal(headers.get("x-goog-channel-token"), secret)
        if not endpoint.channel_id or not endpoint.resource_id or not endpoint.expires_at:
            raise WebhookError("channel_unconfigured", 503)
        _equal(headers.get("x-goog-channel-id"), endpoint.channel_id)
        _equal(headers.get("x-goog-resource-id"), endpoint.resource_id)
        number = headers.get("x-goog-message-number", "")
        state = headers.get("x-goog-resource-state", "")
        if not re.fullmatch(r"[0-9]{1,20}", number) or int(number) < 1 or state not in {"sync", "exists", "not_exists", "change", "update", "add", "remove", "trash", "untrash"}:
            raise WebhookError("invalid_provider_record", 422)
        if raw:
            raise WebhookError("unexpected_notification_body", 400)
        native = endpoint.channel_id + ":" + number
        event_type = "google." + ("calendar" if provider == "google_calendar" else "drive") + ".notification"
        data = {"resource_id": endpoint.resource_id, "state": state}
        evidence = {"channel_id": endpoint.channel_id, "resource_id": endpoint.resource_id, "message_number": number}
        subject_type, subject_id = "notification_channel", endpoint.channel_id
    elif provider == "cloudflare":
        _equal(headers.get("cf-webhook-auth"), secret)
        data = _json(raw)
        event_type = "cloudflare.notification"
        # Generic notifications have no universal immutable ID or signed time.
        evidence = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
    else:
        # Explicit relay contract, not a claim about any provider's native scheme.
        stamp, native = headers.get("x-optibrain-timestamp", ""), headers.get("x-optibrain-delivery", "")
        if not re.fullmatch(r"[0-9]{10}", stamp) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", native):
            raise WebhookError("invalid_delivery_identity", 400)
        signature = hmac.new(secret.encode(), stamp.encode() + b"." + native.encode() + b"." + raw, hashlib.sha256).hexdigest()
        _equal(headers.get("x-optibrain-signature"), signature)
        when = datetime.fromtimestamp(int(stamp), timezone.utc)
        _window(when, now, endpoint.replay_window_seconds)
        data = _json(raw)
        event_type = data.get("event_type", "")
        timestamp = data.get("occurred_at")
        version = data.get("event_version", 1)
        evidence = {"delivery_id": native, "raw_sha256": hashlib.sha256(raw).hexdigest()}
    source = {"zoho_crm": "zoho.crm", "google_calendar": "google.calendar", "google_drive": "google.drive"}.get(provider, provider)
    try:
        event = AutomationEvent(event_type=event_type, event_version=version, source=source, source_account=endpoint.source_account,
            provider_event_id=native, dedupe_identity=None if native else digest({"type": event_type, "data": data}),
            subject_type=subject_type, subject_id=subject_id, provider_timestamp=timestamp,
            payload=data, provider_evidence=evidence)
    except (ValueError, TypeError):
        raise WebhookError("invalid_provider_record", 422) from None
    quarantine = None if event_type in endpoint.allowed_event_types else "unsupported_event_type"
    return event, quarantine


def accept_delivery(ledger: EventLedger, endpoint: WebhookEndpoint, headers: dict[str, str], raw: bytes) -> dict[str, Any]:
    from .native_notifications import effective_endpoint, capture_origin
    endpoint = effective_endpoint(ledger.store, endpoint)
    event, quarantine = verify_delivery(endpoint, headers, raw)
    with ledger.store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        accepted, event_id, correlation_id = ledger._capture(conn, event)
        if accepted and quarantine:
            ledger._quarantine(conn, event_id, event.source, quarantine)
        if accepted and not quarantine:
            capture_origin(conn, endpoint, event, event_id)
        if accepted and not quarantine and endpoint.sync_stream and event.source in {"google.calendar", "google.drive"}:
            # A durable dirty generation prevents a push received during a delta
            # page read from being lost when that read finishes. Backoff remains
            # authoritative; push traffic cannot bypass a provider's Retry-After.
            conn.execute("UPDATE automation_sync_checkpoints SET notifications=notifications+1,"
                "next_attempt_at=CASE WHEN status='idle' THEN 0 ELSE next_attempt_at END "
                "WHERE provider=? AND source_account=? AND stream=? AND mode='incremental'",
                (event.source, event.source_account, endpoint.sync_stream))
    return {"accepted": accepted, "duplicate": not accepted, "event_id": event_id,
            "correlation_id": correlation_id, "quarantined": quarantine is not None}
