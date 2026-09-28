"""Unregistered Gate F operator routes for outbound approval control.

This module is intentionally not imported by workflow.api. Tests may mount it on
a disposable FastAPI app. Gate G must separately review any production routing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .automation.event_schema import digest
from .automation.outbound_approval import OutboundApproval, OutboundApprovalLedger
from .operator_access import AccessIdentityVerifier, AccessPrincipal


class IssueApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_event_id: str = Field(min_length=8, max_length=128)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_in_minutes: int = Field(default=30, ge=5, le=60)


def _no_store(value: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(
        value,
        status_code=status,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def install_operator_outbound_routes(
    app: FastAPI,
    *,
    verifier: AccessIdentityVerifier,
    resolver,
    ledger: OutboundApprovalLedger,
    store,
    allowed_origin: str,
    consume_callback: Callable[[dict], dict] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Mount Gate F routes on an explicitly supplied app.

    `consume_callback` is deliberately optional. Without it, consumption is
    unavailable even for a valid approval. Production startup does not call this
    installer during Gate F engineering.
    """

    origin = str(allowed_origin or "").rstrip("/")
    if not origin.startswith("https://") or len(origin) > 255:
        raise ValueError("operator surface requires an explicit HTTPS same-origin value")
    now = clock or (lambda: datetime.now(timezone.utc))

    def principal(token: str | None) -> AccessPrincipal:
        try:
            return verifier.verify(token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Operator is not authorized") from exc
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Valid Cloudflare Access human identity required") from exc

    def mutation_guard(request: Request) -> None:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="application/json required")
        supplied_origin = request.headers.get("origin")
        if supplied_origin != origin:
            raise HTTPException(status_code=403, detail="same-origin operator request required")
        sec_fetch = request.headers.get("sec-fetch-site")
        if sec_fetch not in {None, "same-origin", "none"}:
            raise HTTPException(status_code=403, detail="cross-site operator request rejected")

    def candidate_dict(review_event_id: str) -> dict:
        try:
            return resolver.resolve(review_event_id).model_dump()
        except (LookupError, ValueError) as exc:
            # Do not echo provider/source details in errors.
            raise HTTPException(status_code=409, detail="Authoritative outbound candidate is not currently eligible") from exc

    @app.get("/v1/operator/outbound/candidates/{review_event_id}", tags=["operator-outbound"])
    async def preview_candidate(
        review_event_id: str,
        cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ):
        identity = principal(cf_access_jwt_assertion)
        candidate = candidate_dict(review_event_id)
        return _no_store({
            "candidate": candidate,
            "operator": {"subject": identity.subject, "email": identity.email},
            "send_enabled": False,
        })

    @app.post("/v1/operator/outbound/approvals", tags=["operator-outbound"])
    async def issue_approval(
        body: IssueApprovalRequest,
        request: Request,
        cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ):
        mutation_guard(request)
        identity = principal(cf_access_jwt_assertion)
        candidate = candidate_dict(body.review_event_id)
        if candidate["candidate_hash"] != body.candidate_hash:
            raise HTTPException(status_code=409, detail="Candidate changed; review the fresh candidate before approval")
        current = now().astimezone(timezone.utc)
        expires = current + timedelta(minutes=body.expires_in_minutes)
        try:
            approval = ledger.issue(
                actor=identity.actor,
                action_type=candidate["action_type"],
                source_type=candidate["source_type"],
                source_id=candidate["source_id"],
                source_version=candidate["source_version"],
                account_id=candidate["account_id"],
                message_id=candidate["message_id"],
                recipient=candidate["recipient"],
                from_address=candidate["from_address"],
                subject=candidate["subject"],
                content=candidate["content"],
                expires_at=expires.isoformat(),
                now=current,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Approval could not be issued") from exc
        store.audit(
            category="outbound_operator",
            action="approval_issued",
            actor=identity.actor,
            success=True,
            target=approval.approval_id,
            metadata={
                "principal_sub": identity.subject,
                "principal_email_hash": digest(identity.email),
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        return _no_store({
            "approval_id": approval.approval_id,
            "state": "issued",
            "actor": approval.actor,
            "approved_at": approval.approved_at,
            "expires_at": approval.expires_at,
        }, status=201)

    @app.get("/v1/operator/outbound/approvals/{approval_id}", tags=["operator-outbound"])
    async def inspect_approval(
        approval_id: str,
        cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ):
        identity = principal(cf_access_jwt_assertion)
        try:
            state = ledger.inspect(approval_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        if state is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        approval = OutboundApproval.model_validate(state["approval"])
        if approval.actor != identity.actor:
            raise HTTPException(status_code=403, detail="Approval belongs to another operator")
        return _no_store({
            "approval": approval.model_dump(),
            "state": state["state"],
            "at": state["at"],
        })

    @app.post("/v1/operator/outbound/approvals/{approval_id}/consume", tags=["operator-outbound"])
    async def consume_approval(
        approval_id: str,
        request: Request,
        cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ):
        mutation_guard(request)
        identity = principal(cf_access_jwt_assertion)
        try:
            state = ledger.inspect(approval_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        if state is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        approval = OutboundApproval.model_validate(state["approval"])
        if approval.actor != identity.actor:
            raise HTTPException(status_code=403, detail="Approval belongs to another operator")
        if state["state"] != "issued":
            raise HTTPException(status_code=409, detail="Approval is not available for consumption")
        try:
            candidate = resolver.resolve_approval_source(
                source_type=approval.source_type,
                source_id=approval.source_id,
            )
            expected = ledger.expected(
                approval_id=approval.approval_id,
                action_type=candidate.action_type,
                source_type=candidate.source_type,
                source_id=candidate.source_id,
                source_version=candidate.source_version,
                account_id=candidate.account_id,
                message_id=candidate.message_id,
                recipient=candidate.recipient,
                from_address=candidate.from_address,
                subject=candidate.subject,
                content=candidate.content,
            )
            ledger.require_issued(expected, now=now())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Authoritative source changed; send blocked") from exc
        if consume_callback is None:
            return _no_store({
                "sent": False,
                "reason": "outbound_send_not_registered",
                "approval_id": approval.approval_id,
            }, status=409)
        request_value = {
            "approval_id": approval.approval_id,
            "action_type": candidate.action_type,
            "source_type": candidate.source_type,
            "source_id": candidate.source_id,
            "source_version": candidate.source_version,
            "mailbox_account_id": candidate.account_id,
            "message_id": candidate.message_id,
            "from_address": candidate.from_address,
            "to_address": candidate.recipient,
            "subject": candidate.subject,
            "content": candidate.content,
            "mail_format": "plaintext",
        }
        result = consume_callback(request_value)
        return _no_store(result)
