"""Unregistered, authenticated Phase 7 canary preview and CRM issuance routes.

There is deliberately no CRM execution or Mail send route here. Production
startup does not import this module. Preview and issuance require an explicit
verified human identity and fresh read-only Lead hydration.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .automation.phase7_canary import build_canary_plan, build_review_package, hydrate_unique_lead
from .automation.phase7_crm_approval import CrmCanaryApprovalLedger
from .automation.sales_operator_view import (
    CONTROLLED_LEAD_ID, build_sales_operator_view, render_sales_operator_view,
)
from .automation.sales_queue import build_sales_queue, render_sales_queue
from .automation.phase9_intake import IntakeLedger
from .automation.outbound_approval import OutboundApproval, OutboundApprovalLedger
from .operator_access import AccessIdentityVerifier
from .zoho_gateway import ZohoGatewayError
from html import escape
from pathlib import Path
import json


class IssueCrmCanaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: str = Field(pattern=r"^[0-9]{1,30}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    patch_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_language: str | None = None
    expires_in_minutes: int = Field(default=30, ge=5, le=60)


class IssueOutboundCanaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: str = Field(pattern=r"^[0-9]{1,30}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_language: str = Field(pattern=r"^(fr|en)$")
    expires_in_minutes: int = Field(default=30, ge=5, le=60)


def install_phase7_canary_routes(app: FastAPI, *, verifier: AccessIdentityVerifier,
                                 client, store, account_id: str, from_address: str,
                                 allowed_origin: str, clock=None, consume_callback=None,
                                 outbound_consume_callback=None) -> None:
    origin = str(allowed_origin or "").rstrip("/")
    if not origin.startswith("https://") or len(origin) > 255:
        raise ValueError("Canary operator surface requires exact HTTPS origin")
    now = clock or (lambda: datetime.now(timezone.utc))
    ledger = CrmCanaryApprovalLedger(store)
    outbound_ledger = OutboundApprovalLedger(store)

    def identity(token):
        try:
            return verifier.verify(token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Operator not authorized") from exc
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Verified human identity required") from exc

    def guard(request: Request):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="application/json required")
        if request.headers.get("origin") != origin:
            raise HTTPException(status_code=403, detail="same-origin request required")
        if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
            raise HTTPException(status_code=403, detail="cross-site request rejected")

    def package(lead_id: str, language: str | None):
        try:
            lead, proof = hydrate_unique_lead(client, lead_id)
            plan = build_canary_plan(lead, proof, now=now())
            review = build_review_package(plan, lead, account_id=account_id,
                                          from_address=from_address,
                                          reviewed_language=language)
            return plan, review
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=409, detail="Canary source requires fresh human review") from exc

    def result(value: dict, status: int = 200):
        return JSONResponse(value, status_code=status,
                            headers={"Cache-Control": "no-store, max-age=0",
                                     "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
                                     "X-Content-Type-Options": "nosniff"})

    @app.get("/v1/operator/phase7/canary/{lead_id}", tags=["operator-phase7"])
    async def preview(lead_id: str, reviewed_language: str | None = None,
                      cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        person = identity(cf_access_jwt_assertion)
        plan, review = package(lead_id, reviewed_language)
        return result({"operator": {"subject": person.subject},
                       "plan": plan.model_dump(), "review": review.model_dump(),
                       "crm_mutation_enabled": False, "customer_send_enabled": False})

    @app.get("/v1/operator/phase8/sales-view/{lead_id}", tags=["operator-phase8"],
             response_class=HTMLResponse)
    async def sales_view(lead_id: str,
                         cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        identity(cf_access_jwt_assertion)
        if lead_id != CONTROLLED_LEAD_ID:
            raise HTTPException(status_code=404, detail="Controlled sales view not found")
        try:
            view = build_sales_operator_view(client, store.db_path,
                                             account_id=account_id, from_address=from_address,
                                             lead_id=lead_id, now=now())
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=409, detail="Fresh Lead identity or evidence needs review") from exc
        except ZohoGatewayError as exc:
            raise HTTPException(status_code=503, detail="Fresh provider evidence unavailable") from exc
        return HTMLResponse(render_sales_operator_view(view), headers={
            "Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        })

    @app.get("/v1/operator/phase8/sales-queue", tags=["operator-phase8"],
             response_class=HTMLResponse)
    async def sales_queue(scope: str = "live",
            cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        identity(cf_access_jwt_assertion)
        try:
            view = build_sales_queue(client, store.db_path, account_id=account_id,
                                     from_address=from_address, now=now(), scope=scope)
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=409, detail="Fresh sales evidence needs review") from exc
        except ZohoGatewayError as exc:
            raise HTTPException(status_code=503, detail="Fresh provider evidence unavailable") from exc
        return HTMLResponse(render_sales_queue(view), headers={
            "Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        })

    @app.get("/v1/operator/phase9/source-trace/{lead_id}", tags=["operator-phase9"],
             response_class=HTMLResponse)
    async def source_trace(lead_id: str,
            cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        identity(cf_access_jwt_assertion)
        if not re.fullmatch(r"[0-9]{1,30}", lead_id):
            raise HTTPException(status_code=404, detail="Trace not found")
        try:
            registry = json.loads(Path("/etc/optibrain/phase8-test-lab-registry.json").read_text())
            if lead_id not in set(registry.get("records", {}).get("Leads") or []):
                raise ValueError("Trace is outside registered Test Lab")
            trace = IntakeLedger(Path(store.db_path).parent / "phase9-intake.db").trace(lead_id)
            if trace is None:
                raise HTTPException(status_code=404, detail="Trace not found")
            result = client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}")
            rows = (result.get("data") or {}).get("data") or []
            if len(rows) != 1 or rows[0].get("OptiBrain_Test") is not True or not str(rows[0].get("Description") or "").startswith("OPTIBRAIN TEST — PHASE "):
                raise ValueError("CRM Test Lab identity changed")
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail="Fresh Test Lab trace needs review") from exc
        except ZohoGatewayError as exc:
            raise HTTPException(status_code=503, detail="Fresh provider evidence unavailable") from exc
        h = lambda value: escape(str(value or "—"), quote=True)
        lead = rows[0]
        events = "".join(
            f"<li><b>{h(e['source'])}</b> · {h(e['occurred_at_montreal'])} · "
            f"{h(e['event_id'])} · {h(e['crm_action'])} · campaign {h(e['campaign'])}</li>"
            for e in trace["events"])
        outcomes = "".join(
            f"<li><b>{h(e['kind'])}</b> · {h(e['related_module'])} {h(e['related_id'])}</li>"
            for e in trace["feedback"])
        html = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<title>OptiBrain source trace</title>"
                "<style>body{font:16px/1.5 system-ui;max-width:850px;margin:2rem auto;padding:0 1rem;color:#182536}"
                "li{margin:.5rem 0}small{color:#526174}</style>"
                f"<h1>Source to opportunity · TEST ONLY</h1><p>{h(lead.get('Full_Name'))} · Lead {h(lead_id)}</p>"
                f"<p><b>First touch:</b> {h(trace['first_touch'])} · <b>Latest touch:</b> {h(trace['latest_touch'])}</p>"
                f"<h2>Intakes</h2><ol>{events}</ol><h2>Outcomes</h2><ol>{outcomes}</ol>"
                "<small>Verified Test Lab CRM identity. Internal audit only; external conversion export disabled.</small></html>")
        return HTMLResponse(html, headers={"Cache-Control": "private, no-store, max-age=0",
                                           "Pragma": "no-cache", "X-Frame-Options": "DENY",
                                           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    @app.post("/v1/operator/phase7/crm-approvals", tags=["operator-phase7"],
              dependencies=[Depends(guard)])
    async def issue(body: IssueCrmCanaryRequest,
                    cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        person = identity(cf_access_jwt_assertion)
        plan, review = package(body.lead_id, body.reviewed_language)
        if plan.plan_hash != body.plan_hash or plan.crm_patch_hash != body.patch_hash or not plan.crm_patch:
            raise HTTPException(status_code=409, detail="Canary patch changed; review again")
        current = now().astimezone(timezone.utc)
        try:
            approval = ledger.issue(actor=person.actor, lead_id=plan.lead_id,
                                    source_version=plan.source_version,
                                    plan_hash=plan.plan_hash, patch_hash=plan.crm_patch_hash,
                                    expires_at=(current + timedelta(minutes=body.expires_in_minutes)).isoformat(),
                                    now=current)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="CRM canary approval unavailable") from exc
        return result({"approval_id": approval.approval_id, "state": "issued",
                       "expires_at": approval.expires_at,
                       "review_package_hash": review.package_hash}, status=201)

    @app.post("/v1/operator/phase7/crm-approvals/{approval_id}/consume",
              tags=["operator-phase7"], dependencies=[Depends(guard)])
    async def consume(approval_id: str,
                      cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        person = identity(cf_access_jwt_assertion)
        try:
            state = ledger.inspect(approval_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        if state is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        approval = state["approval"]
        if approval.actor != person.actor:
            raise HTTPException(status_code=403, detail="Approval belongs to another operator")
        if state["state"] != "issued":
            raise HTTPException(status_code=409, detail="Approval is not reusable")
        # The future callback must independently hydrate/revalidate the exact
        # source and approval before the durable consuming marker/provider call.
        if consume_callback is None:
            return result({"state": "issued", "reason": "crm_canary_not_registered"}, status=409)
        try:
            return result(consume_callback(approval_id))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="CRM canary requires human reconciliation") from exc

    @app.post("/v1/operator/phase7/outbound-approvals", tags=["operator-phase7"],
              dependencies=[Depends(guard)])
    async def issue_outbound(body: IssueOutboundCanaryRequest,
                             cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        person = identity(cf_access_jwt_assertion)
        plan, review = package(body.lead_id, body.reviewed_language)
        if plan.plan_hash != body.plan_hash or review.package_hash != body.package_hash:
            raise HTTPException(status_code=409, detail="Outbound package changed; review again")
        current = now().astimezone(timezone.utc)
        try:
            approval = outbound_ledger.issue(
                actor=person.actor, action_type="send_new_email", source_type="lead",
                source_id=f"phase7:{plan.lead_id}:{plan.plan_hash}",
                source_version=plan.source_version, account_id=review.account_id,
                recipient=review.recipient, from_address=review.sender,
                subject=review.subject, content=review.content,
                expires_at=(current + timedelta(minutes=body.expires_in_minutes)).isoformat(),
                now=current)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Outbound canary approval unavailable") from exc
        return result({"approval_id": approval.approval_id, "state": "issued",
                       "expires_at": approval.expires_at,
                       "review_package_hash": review.package_hash}, status=201)

    @app.post("/v1/operator/phase7/outbound-approvals/{approval_id}/consume",
              tags=["operator-phase7"], dependencies=[Depends(guard)])
    async def consume_outbound(approval_id: str,
                               cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        person = identity(cf_access_jwt_assertion)
        try:
            state = outbound_ledger.inspect(approval_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Approval not found") from exc
        if state is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        fields = set(OutboundApproval.model_fields)
        try:
            approval = OutboundApproval.model_validate({key: state["approval"][key] for key in fields})
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Stored approval invalid") from exc
        if approval.actor != person.actor:
            raise HTTPException(status_code=403, detail="Approval belongs to another operator")
        if state["state"] != "issued":
            raise HTTPException(status_code=409, detail="Approval is not reusable")
        source = re.fullmatch(r"phase7:([0-9]{1,30}):([0-9a-f]{64})", approval.source_id)
        if source is None:
            raise HTTPException(status_code=409, detail="Approval source invalid")
        chosen = None
        for language in ("fr", "en"):
            try:
                plan, review = package(source[1], language)
                expected = outbound_ledger.expected(
                    approval_id=approval.approval_id, action_type="send_new_email",
                    source_type="lead", source_id=f"phase7:{plan.lead_id}:{plan.plan_hash}",
                    source_version=plan.source_version, account_id=review.account_id,
                    message_id=None, recipient=review.recipient,
                    from_address=review.sender, subject=review.subject,
                    content=review.content)
                outbound_ledger.require_issued(expected, now=now())
                chosen = (plan, review)
                break
            except (ValueError, HTTPException):
                continue
        if chosen is None:
            raise HTTPException(status_code=409, detail="Outbound source or content changed")
        if outbound_consume_callback is None:
            return result({"state": "issued", "reason": "outbound_canary_not_registered"}, status=409)
        plan, review = chosen
        request = {
            "approval_id": approval.approval_id, "action_type": "send_new_email",
            "source_type": "lead", "source_id": approval.source_id,
            "source_version": plan.source_version,
            "mailbox_account_id": review.account_id, "message_id": None,
            "from_address": review.sender, "to_address": review.recipient,
            "subject": review.subject, "content": review.content,
            "mail_format": "plaintext",
        }
        try:
            return result(outbound_consume_callback(request))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Outbound canary requires human reconciliation") from exc
