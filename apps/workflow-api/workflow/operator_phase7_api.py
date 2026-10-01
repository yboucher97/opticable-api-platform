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
from .automation.phase9_form_receipts import FormReceiptLedger
from .automation.outbound_approval import OutboundApproval, OutboundApprovalLedger
from .operator_access import AccessIdentityVerifier
from .zoho_gateway import ZohoGatewayError
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import json

TORONTO = ZoneInfo("America/Toronto")


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
            provider_path = Path(store.db_path).parent / "phase9-form-receipts.db"
            verified_form_ids = (FormReceiptLedger(provider_path).verified_test_ids()
                                 if provider_path.exists() else set())
            if lead_id not in (set(registry.get("records", {}).get("Leads") or []) | verified_form_ids):
                raise ValueError("Trace is outside registered Test Lab")
            trace = IntakeLedger(Path(store.db_path).parent / "phase9-intake.db").trace(lead_id)
            if trace is None:
                raise HTTPException(status_code=404, detail="Trace not found")
            provider_events = FormReceiptLedger(provider_path).timeline(lead_id) if provider_path.exists() else []
            result = client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}")
            rows = (result.get("data") or {}).get("data") or []
            if (len(rows) != 1 or str(rows[0].get("id")) != lead_id
                    or rows[0].get("OptiBrain_Test") is not True
                    or not str(rows[0].get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")):
                raise ValueError("CRM Test Lab identity changed")
            verified_chain = None
            for outcome in trace["feedback"]:
                if outcome["kind"] != "OPPORTUNITY_CREATED":
                    continue
                deal_id = outcome["related_id"]
                if deal_id not in set(registry.get("records", {}).get("Deals") or []):
                    raise ValueError("Opportunity is outside Test Lab")
                deal_response = client.request("zohoapis", "GET", f"/crm/v8/Deals/{deal_id}")
                deal_rows = (deal_response.get("data") or {}).get("data") or []
                if (len(deal_rows) != 1 or str(deal_rows[0].get("id")) != deal_id
                        or deal_rows[0].get("OptiBrain_Test") is not True
                        or not str(deal_rows[0].get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")):
                    raise ValueError("Opportunity provider marker changed")
                deal = deal_rows[0]
                contact_id = str((deal.get("Contact_Name") or {}).get("id") or "")
                related_account_id = str((deal.get("Account_Name") or {}).get("id") or "")
                if (contact_id not in set(registry.get("records", {}).get("Contacts") or [])
                        or related_account_id not in set(registry.get("records", {}).get("Accounts") or [])):
                    raise ValueError("Opportunity relationship escaped Test Lab")
                contact_result = client.request("zohoapis", "GET", f"/crm/v8/Contacts/{contact_id}")
                account_result = client.request("zohoapis", "GET", f"/crm/v8/Accounts/{related_account_id}")
                contacts = (contact_result.get("data") or {}).get("data") or []
                accounts = (account_result.get("data") or {}).get("data") or []
                if (len(contacts) != 1 or len(accounts) != 1
                        or str(contacts[0].get("id")) != contact_id
                        or str(accounts[0].get("id")) != related_account_id
                        or contacts[0].get("OptiBrain_Test") is not True
                        or accounts[0].get("OptiBrain_Test") is not True
                        or not str(contacts[0].get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")
                        or str((contacts[0].get("Account_Name") or {}).get("id")) != related_account_id
                        or str(contacts[0].get("Email") or "").casefold() != str(rows[0].get("Email") or "").casefold()
                        or not str(accounts[0].get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")
                        or deal.get("Amount") not in (None, 0, 0.0)
                        or any(deal.get(key) != rows[0].get(key) for key in ("First_Source", "First_Campaign"))):
                    raise ValueError("Opportunity relationship/source readback mismatch")
                verified_chain = (contact_id, related_account_id, deal_id)
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=409, detail="Fresh Test Lab trace needs review") from exc
        except ZohoGatewayError as exc:
            raise HTTPException(status_code=503, detail="Fresh provider evidence unavailable") from exc
        h = lambda value: escape(str(value or "—"), quote=True)
        lead = rows[0]
        history = [e for e in trace["events"] if not (provider_events and e["source"] == "zoho_form"
                   and str(e.get("inquiry_id") or "").startswith("OB-I-"))]
        history += [{**e, "crm_action": e["action"],
                     "occurred_at_montreal": datetime.fromisoformat(e["occurred_at"]).astimezone(
                         TORONTO).isoformat()} for e in provider_events]
        history = sorted({e["event_id"]: e for e in history}.values(),
                         key=lambda e: (datetime.fromisoformat(e.get("occurred_at") or e["occurred_at_montreal"]),
                                        e["event_id"]))
        events = "".join(
            f"<li><b>{h(e['source'])}</b> · {h(e['occurred_at_montreal'])} · "
            f"{h(e['event_id'])} · {h(e['crm_action'])} · campaign {h(e['campaign'])}</li>"
            for e in history)
        outcomes = "".join(
            f"<li><b>{h(e['kind'])}</b> · {h(e.get('occurred_at_montreal'))} · "
            f"{h(e['related_module'])} {h(e['related_id'])}</li>"
            for e in trace["feedback"])
        chain_html = (f"<p><b>Verified CRM relationship:</b> Contact {h(verified_chain[0])} "
                      f"→ Account {h(verified_chain[1])} → Deal {h(verified_chain[2])}. "
                      "The Lead to Contact match is by exact controlled email; no Lead conversion is claimed.</p>"
                      if verified_chain else "<p>No linked opportunity verified yet.</p>")
        html = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<title>OptiBrain source trace</title>"
                "<style>body{font:16px/1.5 system-ui;max-width:850px;margin:2rem auto;padding:0 1rem;color:#182536}"
                "li{margin:.5rem 0}small{color:#526174}</style>"
                f"<h1>Source to opportunity · TEST ONLY</h1><p>{h(lead.get('Full_Name'))} · Lead {h(lead_id)}</p>"
                f"<p><b>First touch:</b> {h(history[0]['source'] if provider_events else trace['first_touch'])} · "
                f"<b>Latest touch:</b> {h(history[-1]['source'] if provider_events else trace['latest_touch'])}</p>"
                f"<h2>Intakes</h2><ol>{events}</ol><h2>Outcomes</h2><ol>{outcomes}</ol>{chain_html}"
                "<small>Verified Test Lab CRM identity. Internal audit only; external conversion export disabled.</small></html>")
        return HTMLResponse(html, headers={"Cache-Control": "private, no-store, max-age=0",
                                           "Pragma": "no-cache", "X-Frame-Options": "DENY",
                                           "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
                                           "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    @app.get("/v1/operator/phase9/intake-receipts", tags=["operator-phase9"],
             response_class=HTMLResponse)
    async def intake_receipts(
            cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion")):
        identity(cf_access_jwt_assertion)
        try:
            ledger = FormReceiptLedger(Path(store.db_path).parent / "phase9-form-receipts.db")
            receipts = ledger.list(100)
            connector = ledger.list_connector(100)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Intake receipts unavailable") from exc
        h = lambda value: escape(str(value if value is not None else "—"), quote=True)
        pending = sum(1 for row in receipts if not row["canonical_id"]
                      or (row["provider_match_status"] == "MATCHED_MISSING_EMAIL"
                          and not row["reviewed_test_link"]))
        items = []
        for row in receipts:
            evidence = json.loads(row["evidence_json"])
            at = datetime.fromisoformat(row["occurred_at"]).astimezone(
                TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z")
            state = (f"CRM Lead {h(row['canonical_id'])} matched read-only" if row["canonical_id"]
                     else "Needs identity and CRM review — no automatic customer record change")
            if row["provider_match_status"] == "MATCHED_MISSING_EMAIL":
                state += " · form-to-CRM email mapping missing at creation"
            if row["reviewed_test_link"]:
                state += " · TEST ONLY identity reviewed"
                state += (f" · <a href='/v1/operator/phase9/source-trace/{h(row['canonical_id'])}'>source trace</a>")
            items.append(f"<li><b>{h(evidence['fields'].get('company'))}</b> · {h(at)}"
                         f"<br>From {h(evidence['source_detail'])} · {h(row['submitted_email'])}"
                         f"<br>{state}<br><small>Receipt {h(row['event_id'])} · Zoho Mail {h(row['provider_message_id'])}"
                         f" · campaign {h(evidence.get('campaign') or 'Unknown')}</small></li>")
        connector_items = []
        for row in connector:
            evidence = json.loads(row["evidence_json"])
            at = datetime.fromisoformat(row["occurred_at"]).astimezone(
                TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z")
            campaign = (evidence.get("attribution") or {}).get("last_campaign") or "Unknown"
            result = ("POSSIBLE DUPLICATE — review; no automatic merge" if row["action"] == "possible_duplicate"
                      else row["action"].replace("_", " "))
            connector_items.append(f"<li><b>{h(row['source'])}</b> · {h(at)}"
                                   f"<br>{h(row['submitted_email'])} · {h(result)}"
                                   f"<br>Canonical CRM: {h(row['canonical_id'])} · Review candidate: {h(row['possible_duplicate_id'])}"
                                   f"<br><small>Receipt {h(row['event_id'])} · campaign {h(campaign)}</small></li>")
        html = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain intake receipts</title>"
                "<style>body{font:16px/1.5 system-ui;max-width:900px;margin:2rem auto;padding:0 1rem;color:#182536}"
                "li{margin:1.2rem 0;padding:.8rem;border:1px solid #ccd;border-radius:.4rem}small{color:#526174}</style>"
                f"<h1>Intake receipts</h1><p><b>{pending} main-form submissions need CRM review</b> · "
                f"{len(receipts)} form and {len(connector)} connector receipts shown</p>"
                "<p>Verified Zoho Forms notifications. A receipt proves form delivery to Mail; it does not claim CRM creation. "
                "Original source and campaign remain Unknown when the notification omits them.</p>"
                f"<h2>Main-site Zoho Form</h2><ol>{''.join(items)}</ol>"
                f"<h2>AI / connector intakes</h2><ol>{''.join(connector_items)}</ol></html>")
        return HTMLResponse(html, headers={"Cache-Control": "private, no-store, max-age=0",
                                           "Pragma": "no-cache", "X-Frame-Options": "DENY",
                                           "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
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
