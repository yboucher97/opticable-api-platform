"""Unregistered operator surface for one exact Phase 7 Lead creation.

Installing these routes does not authorize a provider write. A separate callback
and exact pinned policy are needed for consumption, and issuance is human-only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .automation.phase7_lead_create import (
    LeadCreateLedger, canonical_payload, dedupe_preflight, request_hash,
)
from .operator_access import AccessIdentityVerifier


class CreateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict


class IssueCreateRequest(CreateReviewRequest):
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_in_minutes: int = Field(default=30, ge=5, le=60)


def install_phase7_create_routes(app: FastAPI, *, verifier: AccessIdentityVerifier,
                                 client, store, allowed_origin: str, clock=None,
                                 consume_callback=None) -> None:
    origin = str(allowed_origin or "").rstrip("/")
    if not origin.startswith("https://") or len(origin) > 255:
        raise ValueError("Lead create operator surface requires exact HTTPS origin")
    now = clock or (lambda: datetime.now(timezone.utc))
    ledger = LeadCreateLedger(store)

    def guard(request: Request):
        if request.headers.get("content-type", "").split(";",1)[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="application/json required")
        if request.headers.get("origin") != origin:
            raise HTTPException(status_code=403, detail="same-origin request required")
        if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
            raise HTTPException(status_code=403, detail="cross-site request rejected")

    def person(token):
        try:
            return verifier.verify(token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Operator not authorized") from exc
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Verified human required") from exc

    def result(value, status=200):
        return JSONResponse(value, status_code=status,
                            headers={"Cache-Control":"no-store, max-age=0", "Pragma":"no-cache",
                                     "Referrer-Policy":"no-referrer", "X-Content-Type-Options":"nosniff"})

    @app.post("/v1/operator/phase7/lead-create/review", dependencies=[Depends(guard)], tags=["operator-phase7"])
    async def review(body: CreateReviewRequest,
                     cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        human = person(cf_access_jwt_assertion)
        try:
            payload = canonical_payload(body.fields)
            proof = dedupe_preflight(client, body.fields, now=now())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Lead create requires identity review") from exc
        return result({"operator": human.subject, "payload": payload,
                       "request_hash": request_hash(body.fields), "dedupe": proof,
                       "provider_write_enabled": False})

    @app.post("/v1/operator/phase7/lead-create/approvals", dependencies=[Depends(guard)],
              tags=["operator-phase7"])
    async def issue(body: IssueCreateRequest,
                    cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        human = person(cf_access_jwt_assertion)
        try:
            if request_hash(body.fields) != body.request_hash:
                raise ValueError("Lead create review hash changed")
            proof = dedupe_preflight(client, body.fields, now=now())
            current = now().astimezone(timezone.utc)
            approval = ledger.issue(actor=human.actor, fields=body.fields, dedupe=proof,
                                    expires_at=(current+timedelta(minutes=body.expires_in_minutes)).isoformat(),
                                    now=current)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Lead create approval unavailable") from exc
        return result({"approval_id":approval.approval_id,"state":"issued",
                       "request_hash":approval.payload_hash,"expires_at":approval.expires_at},201)

    @app.post("/v1/operator/phase7/lead-create/approvals/{approval_id}/consume",
              dependencies=[Depends(guard)], tags=["operator-phase7"])
    async def consume(approval_id: str, body: CreateReviewRequest,
                      cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        human = person(cf_access_jwt_assertion)
        try:
            state = ledger.inspect(approval_id)
            if state is None:
                raise HTTPException(status_code=404, detail="Approval not found")
            approval = state["approval"]
            if approval.actor != human.actor:
                raise HTTPException(status_code=403, detail="Approval belongs to another operator")
            if state["state"] != "issued" or request_hash(body.fields) != approval.payload_hash:
                raise HTTPException(status_code=409, detail="Approval unavailable or payload changed")
            if consume_callback is None:
                return result({"state":"issued","reason":"lead_create_not_registered"},409)
            return result(consume_callback(approval_id, body.fields))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Lead create requires human reconciliation") from exc
