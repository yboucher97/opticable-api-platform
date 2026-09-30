"""One read-only operator view for the controlled Phase 8 Lead."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from html import escape
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .phase7_canary import build_canary_plan, hydrate_unique_lead
from .providers.crm_leads import _utc_iso, records
from .sales_decision import build_sales_decision

CONTROLLED_LEAD_ID = "5062683000007880001"
TORONTO = ZoneInfo("America/Toronto")
_SOURCE_LABELS = {"ai_website": "AI website"}
_SERVICE_LABELS = {"ai_loss_prevention": "AI loss prevention"}


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Sales view timestamp requires an offset")
    return parsed


def _local(value: str | None) -> str | None:
    return _aware(value).astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z") if value else None


def _inquiry(description: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in str(description or "").splitlines()[:24]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().casefold()
        if key in {"ingestion source", "service", "language", "existing cameras", "project", "timeline"}:
            result.setdefault(key, value.strip()[:400])
    return result


def _history(db_path: Path, lead_id: str, version: str) -> dict:
    """Read only bounded event evidence for the exact current CRM version."""
    uri = "file:" + quote(str(db_path.resolve())) + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT l.event_id,l.received_at,l.envelope_json,p.status,p.duplicate_count "
            "FROM automation_event_ledger l JOIN automation_event_processing p USING(event_id) "
            "WHERE json_extract(l.envelope_json,'$.subject_id')=? "
            "AND json_extract(l.envelope_json,'$.event_type')='opticable.crm.lead.reviewed' "
            "ORDER BY l.received_at DESC LIMIT 20", (lead_id,)).fetchall()
        for row in rows:
            envelope = json.loads(row["envelope_json"])
            if envelope.get("source") != "crm-lead-observer":
                continue
            try:
                matched = _utc_iso((envelope.get("payload") or {}).get("version")) == version
            except (ValueError, TypeError):
                matched = False
            if not matched:
                continue
            runs = db.execute(
                "SELECT r.workflow_id,r.status,r.context_json FROM automation_event_routes t "
                "JOIN automation_runs r USING(run_id) WHERE t.root_event_id=? "
                "ORDER BY r.workflow_id LIMIT 6", (row["event_id"],)).fetchall()
            actions = []
            for run in runs:
                context = json.loads(run["context_json"] or "{}")
                steps = context.get("steps") or {}
                if run["workflow_id"] == "opticable.crm.lead-reconcile":
                    detail = (steps.get("reconcile") or {}).get("mode") or "unverified"
                elif run["workflow_id"] == "opticable.sales-draft":
                    draft = steps.get("draft") or {}
                    detail = ("draft created" if draft.get("drafted") is True
                              else "no draft: " + str(draft.get("reason") or "unverified"))
                else:
                    continue
                actions.append({"workflow": run["workflow_id"], "status": run["status"], "detail": detail})
            return {"current_version_reviewed": True, "review_event_id": row["event_id"],
                    "reviewed_at": _local(row["received_at"]), "event_status": row["status"],
                    "duplicate_notifications": row["duplicate_count"], "actions": actions}
    return {"current_version_reviewed": False, "actions": []}


def _prior_outbound(db_path: Path, lead_id: str, email: str) -> dict | None:
    """Read a consumed, Lead-bound send from the local approval journal."""
    uri = "file:" + quote(str(db_path.resolve())) + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute(
            "SELECT at,metadata_json FROM automation_audit "
            "WHERE category='outbound_approval_v1' AND action='consumed' AND success=1 "
            "AND json_extract(metadata_json,'$.source_id') LIKE ? "
            "ORDER BY id DESC LIMIT 20", (f"phase7:{lead_id}:%",)).fetchall()
    matches = []
    for at, raw in rows:
        evidence = json.loads(raw)
        if (not re.fullmatch(rf"phase7:{re.escape(lead_id)}:[0-9a-f]{{64}}",
                             str(evidence.get("source_id") or ""))
                or str(evidence.get("recipient") or "").casefold() != email.casefold()
                or not re.fullmatch(r"[0-9]{1,30}", str(evidence.get("provider_operation_id") or ""))):
            continue
        matches.append({"sent_at": _local(at),
                        "provider_message_id": str(evidence["provider_operation_id"])})
    if not matches:
        return None
    return {"latest": matches[0], "recorded_sends": len(matches),
            "basis": "consumed human approval and provider message ID in local audit"}


def build_sales_operator_view(client, db_path: Path, *, lead_id: str = CONTROLLED_LEAD_ID,
                              now: datetime | None = None) -> dict:
    """Three bounded CRM GETs; no approval, write, draft save or send path."""
    if lead_id != CONTROLLED_LEAD_ID:
        raise ValueError("Sales view is limited to the controlled Lead")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Sales view clock requires a timezone")
    lead, proof = hydrate_unique_lead(client, lead_id)
    full = records(client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}"))
    if (len(full) != 1 or str(full[0].get("id")) != lead_id
            or _utc_iso(full[0].get("Modified_Time")) != proof.source_version
            or str(full[0].get("Email") or "").strip().casefold()
               != str(lead.get("Email") or "").strip().casefold()):
        raise ValueError("CRM Lead changed during sales view hydration")
    record = full[0]
    if (any(record.get(key) != lead.get(key) for key in
            ("Email_Opt_Out", "Lead_Status", "Converted__s", "Company"))
            or _utc_iso(record.get("Next_Followup_At"))
               != _utc_iso(lead.get("Next_Followup_At"))):
        raise ValueError("CRM Lead fields changed during sales view hydration")
    plan = build_canary_plan(lead, proof, now=clock)
    decision = build_sales_decision(record, now=clock)
    if decision.version != proof.source_version:
        raise ValueError("Sales decision does not match deduplicated Lead")
    modified = _aware(record["Modified_Time"])
    if modified > clock.astimezone(timezone.utc):
        raise ValueError("CRM modification time is in the future")

    inquiry = _inquiry(record.get("Description"))
    source_code = str(record.get("Ingestion_Source") or "").strip()
    source_agrees = bool(source_code and inquiry.get("ingestion source") == source_code)
    service_code = inquiry.get("service") if source_agrees else None
    service_interest = (_SERVICE_LABELS.get(service_code or "")
                        or str(record.get("Service_Types") or "").strip() or None)
    form_language = inquiry.get("language") if source_agrees else None
    if form_language not in {"en", "fr"}:
        form_language = None
    camera_context = inquiry.get("existing cameras") if source_agrees else None
    project_summary = inquiry.get("project") if source_agrees else None
    current_due = _aware(record["Next_Followup_At"]) if record.get("Next_Followup_At") else None
    overdue = bool(current_due and current_due <= clock)

    missing = []
    if not record.get("Service_Types"):
        missing.append("Confirm service requirements" if service_interest else "Service requirements")
    if not str(record.get("Street") or "").strip():
        missing.append("Site street address")
    if service_code == "ai_loss_prevention":
        missing.append("Camera count and coverage areas")
    elif not str(record.get("Scope") or "").strip():
        missing.append("Approximate project scope")
    if not inquiry.get("timeline") and not record.get("Project_Timeline"):
        missing.append("Target timeline")
    if decision.language == "unknown" and not form_language:
        missing.append("Preferred reply language")
    elif decision.language == "unknown":
        missing.append("Confirm preferred reply language (form suggests " + form_language.upper() + ")")

    ready = bool(decision.active and record.get("Service_Types")
                 and record.get("Street") and not any("scope" in x.lower() or "camera" in x.lower()
                                                       or "timeline" in x.lower() for x in missing))
    quote = "READY" if ready else "NEEDS INFORMATION"
    priority = "High" if overdue and decision.active else {"urgent": "High", "high": "High",
                "normal": "Medium", "low": "Low"}[decision.priority]
    if not decision.active:
        next_action = "Review Lead status before further action"
    elif overdue:
        next_action = "Review overdue follow-up now"
    elif ready:
        next_action = "Prepare a quote for human review"
    elif decision.email_contactable:
        next_action = "Ask for project details before quoting"
    elif decision.contactable:
        next_action = "Call to clarify project requirements"
    else:
        next_action = "Resolve contact details before outreach"

    prior_outbound = _prior_outbound(db_path, lead_id, str(record.get("Email") or ""))
    if prior_outbound and decision.active and not overdue:
        next_action = "Check for a reply before the scheduled follow-up"
    next_reason = ("The CRM deadline has passed and a prior send is recorded; check the inbox before outreach."
                   if prior_outbound and overdue else
                   "A prior approved send is recorded; check the inbox before another request."
                   if prior_outbound and decision.active else
                   "The current CRM record lacks enough confirmed scope for a quote."
                   if not ready else
                   "The core quote inputs are present; pricing still requires human review.")
    language = decision.language if decision.language in {"en", "fr"} else form_language
    if decision.email_contactable and language == "en":
        subject = ("Following up on your Opticable inquiry" if prior_outbound
                   else "Re: Your inquiry with Opticable")
        topic = service_interest or "your project"
        place = str(record.get("City") or "your site").strip()
        opening = (f"I’m following up on my previous note about {topic} in {place}. "
                   if prior_outbound else f"Thank you for your inquiry about {topic} in {place}. ")
        body = ("Hello,\n\n" + opening +
                "To assess the right solution and whether a quote is appropriate, "
                "could you confirm the site address, the approximate scope"
                + (" (including camera count and coverage areas)" if service_code == "ai_loss_prevention" else "")
                + ", and your target timeline?\n\nThe Opticable team")
    elif decision.email_contactable and language == "fr":
        subject = ("Suivi de votre demande auprès d’Opticable" if prior_outbound
                   else "Votre demande auprès d’Opticable")
        opening = ("Je fais suite à mon dernier message. " if prior_outbound
                   else "Merci pour votre demande. ")
        body = ("Bonjour,\n\n" + opening + "Pour évaluer la solution et préparer "
                "une soumission appropriée, pourriez-vous confirmer l’adresse du site, "
                "la portée approximative du projet et votre échéancier?\n\nL’équipe Opticable")
    else:
        subject, body = None, None

    audit = _history(db_path, lead_id, proof.source_version)
    return {
        "controlled_test": True,
        "lead": {"id": lead_id, "name": str(record.get("Full_Name") or "").strip(),
                 "company": str(record.get("Company") or "").strip() or None,
                 "email": str(record.get("Email") or "").strip(),
                 "status": str(record.get("Lead_Status") or "").strip(),
                 "client_ref": plan.client_ref, "project_ref": plan.project_ref},
        "source": {"label": _SOURCE_LABELS.get(source_code, source_code or "Unknown"),
                   "crm_source": source_code or None, "description_agrees": source_agrees,
                   "source_record_id": record.get("Source_Record_ID"),
                   "inquiry_id": record.get("Inquiry_ID")},
        "dedupe": {"status": "One exact-email Lead", "matches": len(proof.matching_lead_ids),
                   "query_hash": proof.query_hash},
        "known": {"service_interest": service_interest, "service_basis": "AI website form, unconfirmed in CRM"
                  if service_code else "CRM service field" if service_interest else None,
                  "city": record.get("City"), "existing_cameras": camera_context,
                  "project_summary": project_summary},
        "qualification": {"status": "Discovery needed" if decision.active and not ready else
                          "Quote review" if ready else "Inactive / review",
                          "priority": priority,
                          "reason": "A service interest is recorded, but site, scope and timing need confirmation."
                          if service_interest and not ready else
                          "Project details require human review."},
        "missing_information": missing,
        "next_action": {"primary": next_action, "reason": next_reason},
        "quote_readiness": {"status": quote,
                            "reason": "Confirm site, scope and timeline before pricing."
                            if not ready else "Prepare a human-reviewed quote; no automatic send."},
        "follow_up": {"current": _local(record.get("Next_Followup_At")),
                      "overdue": overdue,
                      "recommended": "Review now; preserve the overdue CRM deadline" if overdue else
                                     _local(decision.followup_at),
                      "basis": "Existing provider deadline preserved" if current_due else
                               "Montreal business-day recommendation"},
        "draft": {"label": "DRAFT — NOT SENT", "subject": subject, "body": body,
                  "recipient": record.get("Email"),
                  "use_condition": "Check the inbox for a reply and wait until the CRM follow-up deadline."
                                   if prior_outbound and not overdue else "Check Sent and inbox before use.",
                  "language_basis": "AI website form; verify before use" if decision.language == "unknown" and form_language else
                                    "CRM language" if language else "Language needs review"},
        "evidence": {"read_at": _local(clock.isoformat()), "created_at": _local(record.get("Created_Time")),
                     "modified_at": _local(record.get("Modified_Time")),
                     "source_version": proof.source_version,
                     "crm_age_hours": round((clock - modified).total_seconds() / 3600, 1),
                     "decision_hash": decision.decision_hash,
                     "audit": audit, "prior_outbound": prior_outbound},
    }


def render_sales_operator_view(view: dict) -> str:
    """Compact, escaped HTML with no script and no business-action control."""
    h = lambda value: escape(str(value if value is not None else "—"), quote=True)
    items = "".join(f"<li>{h(item)}</li>" for item in view["missing_information"])
    audit = view["evidence"]["audit"]
    actions = " · ".join(h(x["workflow"].removeprefix("opticable.") + ": " + x["detail"])
                         for x in audit["actions"]) or "No current-version action evidence"
    draft = view["draft"]
    draft_content = (f"<p><strong>{h(draft['subject'])}</strong></p><pre>{h(draft['body'])}</pre>"
                     if draft["body"] else "<p>Language or contact permission requires review before drafting.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OptiBrain sales view — {h(view['lead']['id'])}</title><style>
body{{font:16px/1.45 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#182536;background:#f7f9fc}}
h1{{font-size:1.5rem;margin-bottom:.2rem}}h2{{font-size:1rem;margin:.2rem 0 .7rem}}p{{margin:.35rem 0}}
.card{{background:white;border:1px solid #d9e1eb;border-radius:10px;padding:1rem;margin:.8rem 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:.8rem}}
.badge{{font-weight:700;color:#164c79}}.note{{color:#526174}}pre{{white-space:pre-wrap;font:inherit}}
</style></head><body><h1>{h(view['lead']['name'])}</h1><p>{h(view['lead']['company'])} · Lead {h(view['lead']['id'])} · {h(view['lead']['email'])}</p>
<p class="note">Controlled internal test · Read-only view · Read {h(view['evidence']['read_at'])}</p>
<div class="grid"><section class="card"><h2>Sales decision</h2><p><span class="badge">{h(view['qualification']['priority'])} priority</span> · {h(view['qualification']['status'])}</p>
<p>{h(view['qualification']['reason'])}</p><p><strong>Next:</strong> {h(view['next_action']['primary'])}</p><p class="note">{h(view['next_action']['reason'])}</p></section>
<section class="card"><h2>Quote and follow-up</h2><p><strong>Quote:</strong> {h(view['quote_readiness']['status'])} — {h(view['quote_readiness']['reason'])}</p>
<p><strong>CRM follow-up:</strong> {h(view['follow_up']['current'])}</p><p><strong>Overdue:</strong> {'Yes' if view['follow_up']['overdue'] else 'No'}</p>
<p><strong>Recommended:</strong> {h(view['follow_up']['recommended'])}</p></section></div>
<div class="grid"><section class="card"><h2>Known</h2><p><strong>Source:</strong> {h(view['source']['label'])} {'(CRM and description agree)' if view['source']['description_agrees'] else '(source needs review)'}</p>
<p><strong>Service interest:</strong> {h(view['known']['service_interest'])} <span class="note">{h(view['known']['service_basis'])}</span></p>
<p><strong>City:</strong> {h(view['known']['city'])} · <strong>Existing cameras:</strong> {h(view['known']['existing_cameras'])}</p>
<p><strong>Project:</strong> {h(view['known']['project_summary'])}</p>
<p class="note">Inquiry ID: {h(view['source']['inquiry_id'])}</p></section>
<section class="card"><h2>Missing before quote</h2><ul>{items}</ul></section></div>
<section class="card"><h2>{h(draft['label'])}</h2>{draft_content}<p class="note">To: {h(draft['recipient'])} · Language: {h(draft['language_basis'])}. {h(draft['use_condition'])} Preview only; no Mail draft or send.</p></section>
<section class="card"><h2>Evidence</h2><p>Exact-email dedupe: {h(view['dedupe']['status'])} · CRM status: {h(view['lead']['status'])}</p>
<p>CRM created {h(view['evidence']['created_at'])}; modified {h(view['evidence']['modified_at'])} ({h(view['evidence']['crm_age_hours'])} hours before this read).</p>
<p>Prior outbound: {('Recorded sent ' + h(view['evidence']['prior_outbound']['latest']['sent_at']) + ' · message ' + h(view['evidence']['prior_outbound']['latest']['provider_message_id']) + ' · ' + h(view['evidence']['prior_outbound']['basis'])) if view['evidence']['prior_outbound'] else 'No Lead-bound send found in local audit; check Mail before outreach.'}</p>
<p>Reviewed event: {h(audit.get('review_event_id')) if audit['current_version_reviewed'] else 'No exact-version review'}</p>
<p>Workflow: {actions}</p><p class="note">Internal refs: {h(view['lead']['client_ref'])}, {h(view['lead']['project_ref'])}; these are not Zoho IDs.</p></section>
</body></html>"""
