"""Authenticated event administration and independently authenticated webhooks."""
from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from .events import EventConflict, EventLedger
from .delta_sync import DeltaSync
from .event_schema import digest
from .store import AutomationStore
from .webhooks import WebhookError, accept_delivery, load_endpoints


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    reason: str = Field(min_length=8, max_length=500)


class ReplayBatchRequest(ReplayRequest):
    event_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    after: str | None = Field(default=None, max_length=128)
    through: str | None = Field(default=None, max_length=128)
    start: str | None = None
    end: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class BackfillPromotion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern=r"^google\.calendar$")
    source_account: str = Field(min_length=1, max_length=255)
    stream: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=8, max_length=500)


def install_event_routes(app: FastAPI, get_store: Callable[[], AutomationStore],
                         authenticate: Callable[[str | None], None], enabled: Callable[[], bool],
                         sync_health: Callable[[], dict] | None = None) -> None:
    def ledger(key: str | None) -> EventLedger:
        authenticate(key)
        return EventLedger(get_store())

    @app.get("/v1/automation/event-health", tags=["automation"])
    async def event_health(x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        result = await run_in_threadpool(ledger(x_api_key).health)
        if sync_health:
            result["sync_worker"] = sync_health()
        return result

    @app.get("/v1/automation/usage", tags=["automation"])
    async def usage(days: int = Query(30, ge=1, le=365), x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        return {"usage": await run_in_threadpool(ledger(x_api_key).usage, days)}

    @app.get("/v1/automation/sync/checkpoints", tags=["automation"])
    async def checkpoints(x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        return {"checkpoints": (await run_in_threadpool(ledger(x_api_key).health))["sync_checkpoints"]}

    @app.post("/v1/automation/sync/promote-backfill", tags=["automation"])
    async def promote_backfill(body: BackfillPromotion, x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        selected = ledger(x_api_key)
        try:
            return await run_in_threadpool(DeltaSync(selected.store).promote_backfill, body.provider, body.source_account,
                                          body.stream, expected_revision=body.expected_revision, actor="api", reason=body.reason)
        except ValueError:
            raise HTTPException(409, "Completed backfill is not eligible for promotion") from None

    @app.get("/v1/automation/events", tags=["automation"])
    async def events(limit: int = Query(50, ge=1, le=100), after: str | None = Query(None, max_length=128),
                     start: str | None = None, end: str | None = None, status: str | None = None,
                     x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        selected = ledger(x_api_key)
        try:
            rows = await run_in_threadpool(selected.list_events, limit=limit, after=after, start=start, end=end, status=status)
        except ValueError:
            raise HTTPException(422, "Invalid event selection") from None
        return {"events": rows, "next_after": rows[-1]["event_id"] if len(rows) == limit else None}

    @app.post("/v1/automation/events/replay-batch", tags=["automation"])
    async def replay_batch(body: ReplayBatchRequest, x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        selected = ledger(x_api_key)
        if body.event_ids is not None:
            if any(value is not None for value in (body.after, body.through, body.start, body.end)):
                raise HTTPException(422, "Select event identities or a bounded range")
            ids = list(dict.fromkeys(body.event_ids))
        else:
            if not ((body.after is not None and body.through is not None) or (body.start and body.end)):
                raise HTTPException(422, "A bounded range or time window is required")
            try:
                rows = await run_in_threadpool(selected.list_events, limit=body.limit, after=body.after, start=body.start, end=body.end)
            except ValueError:
                raise HTTPException(422, "Invalid event selection") from None
            ids = [row["event_id"] for row in rows if not row["replay_of"] and (body.through is None or row["event_id"] <= body.through)]
        outcomes = []
        for event_id in ids:
            try:
                result = await run_in_threadpool(selected.replay, event_id,
                    request_key="batch:" + digest([body.request_key, event_id]), actor="api", reason=body.reason)
                outcomes.append({"original_event_id": event_id, **result})
            except (LookupError, ValueError):
                outcomes.append({"original_event_id": event_id, "status": "ineligible"})
        return {"outcomes": outcomes, "count": len(outcomes)}

    @app.get("/v1/automation/events/{event_id}", tags=["automation"])
    async def inspect_event(event_id: str, x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        result = await run_in_threadpool(ledger(x_api_key).inspect, event_id)
        if result is None:
            raise HTTPException(404, "Event not found")
        return result

    @app.post("/v1/automation/events/{event_id}/replay", tags=["automation"])
    async def replay_event(event_id: str, body: ReplayRequest,
                           x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict:
        selected = ledger(x_api_key)
        try:
            return await run_in_threadpool(selected.replay, event_id, request_key=body.request_key, actor="api", reason=body.reason)
        except LookupError:
            raise HTTPException(404, "Event not found") from None
        except ValueError:
            raise HTTPException(409, "Event is not eligible for this replay request") from None

    @app.post("/v1/automation/webhooks/{endpoint_name}", status_code=202, tags=["automation"])
    async def webhook(endpoint_name: str, request: Request) -> dict:
        if not enabled():
            raise HTTPException(503, "Automation is disabled")
        try:
            endpoints = load_endpoints()
            endpoint = endpoints.get(endpoint_name)
            if endpoint is None:
                raise HTTPException(404, "Webhook endpoint not configured")
        except (ValueError, OSError):
            raise HTTPException(503, "Webhook configuration unavailable") from None
        selected = EventLedger(get_store())
        source = {"zoho_crm": "zoho.crm", "google_calendar": "google.calendar", "google_drive": "google.drive"}.get(endpoint.provider, endpoint.provider)
        try:
            for name in ("content-length", "content-type", "x-hub-signature-256", "x-github-delivery", "x-github-event",
                         "x-goog-channel-token", "x-goog-channel-id", "x-goog-resource-id", "x-goog-message-number",
                         "x-goog-resource-state", "cf-webhook-auth", "x-optibrain-signature", "x-optibrain-timestamp", "x-optibrain-delivery"):
                if len(request.headers.getlist(name)) > 1:
                    raise WebhookError("ambiguous_headers", 400)
            length = request.headers.get("content-length")
            if length is not None:
                if not length.isdecimal():
                    raise WebhookError("invalid_content_length", 400)
                if int(length) > endpoint.max_body_bytes:
                    raise WebhookError("body_too_large", 413)
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > endpoint.max_body_bytes:
                    raise WebhookError("body_too_large", 413)
                raw.extend(chunk)
            return await run_in_threadpool(accept_delivery, selected, endpoint, dict(request.headers), bytes(raw))
        except WebhookError as exc:
            await run_in_threadpool(selected.record_usage, source,
                "webhook_verification_failures" if exc.status == 401 else "webhook_rejections")
            raise HTTPException(exc.status, exc.category) from None
        except EventConflict:
            await run_in_threadpool(selected.record_usage, source, "dedupe_conflicts")
            raise HTTPException(409, "Delivery identity conflicts with durable evidence") from None
