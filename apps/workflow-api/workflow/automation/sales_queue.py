"""Bounded, read-only sales triage over fresh CRM lists and the controlled Mail view."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
import re
from zoneinfo import ZoneInfo

from .providers.crm_leads import records
from .sales_operator_view import CONTROLLED_LEAD_ID, build_sales_operator_view

TORONTO = ZoneInfo("America/Toronto")
ACTIVE = {"Not Contacted", "Attempted to Contact", "Contact in Future", "Pre-Qualified"}
INACTIVE = {"Junk Lead", "Lost Lead", "Not Qualified", "Converted"}
FIELDS = ("id,Full_Name,Company,Email,Phone,Mobile,Lead_Status,Converted__s,"
          "Created_Time,Modified_Time,Next_Followup_At,Ingestion_Source,Lead_Source,"
          "Service_Types,City,State,Street,Scope,Project_Timeline,Description,Email_Opt_Out")


def aware(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Sales queue timestamp requires an offset")
    return value


def local(value):
    return aware(value).astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z") if value else None


def _list(client, module, fields, limit):
    response = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                              query={"fields": fields, "per_page": limit, "page": 1,
                                     "sort_by": "Modified_Time" if module == "Leads" else "id",
                                     "sort_order": "desc"})
    rows = records(response, empty=True)
    info = (response.get("data") or {}).get("info") or {}
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("CRM list has invalid records")
    return rows, not bool(info.get("more_records"))


def _relationship(lead, contacts, accounts, *, complete):
    name = str(lead.get("Full_Name") or "").strip().casefold()
    company = str(lead.get("Company") or "").strip().casefold()
    email = str(lead.get("Email") or "").strip().casefold()
    matched_contacts = [str(x["id"]) for x in contacts if
                        (email and str(x.get("Email") or "").strip().casefold() == email)
                        or (name and str(x.get("Full_Name") or "").strip().casefold() == name)]
    matched_accounts = [str(x["id"]) for x in accounts if
                        company and str(x.get("Account_Name") or "").strip().casefold() == company]
    if len(matched_contacts) > 1 or len(matched_accounts) > 1:
        state = "AMBIGUOUS"
    elif matched_contacts or matched_accounts:
        state = "SUGGESTED"
    else:
        state = "NONE SEEN" if complete else "NOT VERIFIED"
    return {"state": state, "contact_ids": matched_contacts[:3],
            "account_ids": matched_accounts[:3],
            "basis": "Exact CRM name/email or company match; no provider link asserted"
                     if matched_contacts or matched_accounts else
                     "Bounded Contacts/Accounts list; absence is not a verified relationship"}


def neglected(*, status, deadline, modified, last_outbound, reply_state, now):
    """Neglect requires a known open status and verified thread, not age alone."""
    if status not in ACTIVE or reply_state != "NO_REPLY_YET":
        return False
    if deadline is None or deadline >= now or modified > now - timedelta(days=2):
        return False
    if last_outbound is None:
        return False  # No verified send history: cannot assert no recent outreach.
    sent = aware(last_outbound)
    return sent < now - timedelta(days=2) and sent < deadline


def future_controlled_draft(view):
    """Review-only draft for the known waiting Lead; never a send recommendation."""
    if (view["lead"]["id"] != CONTROLLED_LEAD_ID
            or view["follow_up"]["status"] != "WAIT"
            or view["evidence"]["mail"]["reply_state"] != "NO_REPLY_YET"
            or not view["evidence"]["mail"].get("last_outbound")):
        return None
    deadline = view["follow_up"]["current"]
    service = view["known"]["service_interest"] or "your project"
    city = view["known"]["city"] or "your site"
    body = (
        "TEST ONLY — OPTIBRAIN PHASE 8\n"
        f"Hold for human review after {deadline}; check the inbox again before use.\n\n"
        "Proposed customer message:\n\nHello,\n\n"
        f"I'm following up on my previous note about {service} in {city}. "
        "To understand the site and assess whether a quote is appropriate, "
        "could you share the site address, approximate camera count and coverage areas, "
        "and your target timeline?\n\nThe Opticable team"
    )
    return {"label": "FUTURE FOLLOW-UP DRAFT — NOT SENT",
            "subject": "TEST ONLY — OPTIBRAIN PHASE 8 — Future follow-up for your Opticable inquiry",
            "body": body, "use_condition": "Review after " + deadline + " and recheck Mail before any send."}


def analyze_queue(leads, contacts, accounts, controlled, *, now, leads_complete,
                  relationships_complete):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Queue clock requires timezone")
    ids = [str(x.get("id") or "") for x in leads]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[0-9]{1,30}", x) for x in ids):
        raise ValueError("CRM list identity is ambiguous")
    emails = Counter(str(x.get("Email") or "").strip().casefold() for x in leads if x.get("Email"))
    rows = []
    for lead in leads:
        lead_id = str(lead["id"])
        status = str(lead.get("Lead_Status") or "").strip()
        modified = aware(lead.get("Modified_Time"))
        if modified > now + timedelta(minutes=2):
            raise ValueError("Future CRM modification time")
        due = aware(lead["Next_Followup_At"]) if lead.get("Next_Followup_At") else None
        email = str(lead.get("Email") or "").strip()
        duplicate_count = emails[email.casefold()] if email else 0
        duplicate = ("DUPLICATE IN CRM" if duplicate_count > 1 and leads_complete else
                     "MATCH IN SAMPLE" if duplicate_count > 1 else
                     "ONE EXACT EMAIL" if email and leads_complete else
                     "NOT VERIFIED")
        relation = _relationship(lead, contacts, accounts, complete=relationships_complete)
        missing = []
        if not status: missing.append("Lead status")
        if not (email or lead.get("Phone") or lead.get("Mobile")): missing.append("Contact method")
        if not lead.get("Service_Types"): missing.append("Service requirements")
        if not lead.get("Street"): missing.append("Site address")
        if not lead.get("Scope"): missing.append("Project scope")
        if not lead.get("Project_Timeline"): missing.append("Target timeline")
        source = str(lead.get("Ingestion_Source") or lead.get("Lead_Source") or "").strip() or "Unknown"
        known_active = status in ACTIVE and lead.get("Converted__s") is False
        closed = status in INACTIVE or lead.get("Converted__s") is True
        reply = "NOT CHECKED"
        followup = "NO VERIFIED DEADLINE" if due is None else "INBOX REVIEW REQUIRED"
        action, reason, priority, qualification = (
            "Verify Lead status and identity before outreach",
            "CRM status and project context are absent; age alone does not prove neglect.",
            "MEDIUM", "Unreviewed / insufficient evidence")
        draft = None
        last_activity = "CRM modified " + local(lead["Modified_Time"]) + " (activity unverified)"
        if closed:
            action, reason, priority, qualification = (
                "No sales outreach", "CRM marks the Lead inactive or converted.", "LOW", "Inactive")
        elif status and not known_active:
            action, reason, priority, qualification = (
                "Review CRM status before outreach", "Status is outside the verified open workflow.",
                "LOW", "Status needs review")
        elif known_active:
            action, reason, priority, qualification = (
                "Review Lead and inbox before outreach",
                "No thread-linked Mail evidence was checked for this Lead.",
                "MEDIUM", "Discovery needed")
        if duplicate_count > 1:
            action = "Resolve duplicate identity before sales action"
            reason = f"{duplicate_count} Leads share this exact email in the bounded CRM read."
            priority = "MEDIUM" if not closed else "LOW"
        ready = bool(known_active and leads_complete and lead.get("Service_Types") and lead.get("Street")
                     and lead.get("Scope") and lead.get("Project_Timeline")
                     and duplicate_count <= 1)
        quote = "READY FOR QUOTE" if ready else "NOT APPROPRIATE YET" if not known_active else "NEEDS INFORMATION"
        quote_reason = ("Open status and project fit are unverified." if not known_active else
                        "Service, site, scope and timing are recorded; human pricing review remains required."
                        if ready else "Service, site, scope and timing must support a human quote review.")
        if ready:
            action, reason, priority, qualification = (
                "Review scope and prepare a human quote", "Recorded service, site, scope and timing support quote review.",
                "HIGH", "Quote review")
        if lead_id == CONTROLLED_LEAD_ID and controlled:
            if controlled["evidence"]["source_version"] != modified.astimezone(timezone.utc).isoformat():
                raise ValueError("Controlled Lead changed during queue read")
            followup = controlled["follow_up"]["status"]
            reply = controlled["evidence"]["mail"]["reply_state"]
            action = controlled["next_action"]["primary"]
            reason = controlled["next_action"]["reason"]
            priority = "LOW" if followup == "WAIT" else "HIGH" if followup in {
                "OVERDUE", "REPLIED — REVIEW RESPONSE"} else "MEDIUM"
            qualification = controlled["qualification"]["status"]
            missing = controlled["missing_information"]
            quote = "READY FOR QUOTE" if controlled["quote_readiness"]["status"] == "READY" else "NEEDS INFORMATION"
            quote_reason = controlled["quote_readiness"]["reason"]
            source = controlled["source"]["label"]
            duplicate = controlled["dedupe"]["status"].upper()
            outbound = controlled["evidence"]["mail"].get("last_outbound")
            if outbound:
                last_activity = "Verified outbound " + outbound["sent_at_local"]
            draft = (controlled["draft"] if controlled["draft"]["body"] else
                     future_controlled_draft(controlled))
        is_neglected = False
        if lead_id == CONTROLLED_LEAD_ID and controlled:
            mail = controlled["evidence"]["mail"]
            outbound = mail.get("last_outbound")
            is_neglected = neglected(
                status=status, deadline=due, modified=modified,
                last_outbound=outbound.get("sent_at") if outbound else None,
                reply_state=mail["reply_state"], now=now)
        rows.append({"id": lead_id, "name": str(lead.get("Full_Name") or "").strip(),
                     "company": str(lead.get("Company") or "").strip() or None,
                     "email": email or None, "status": status or "Unreviewed", "source": source,
                     "priority": priority, "qualification": qualification,
                     "duplicate": duplicate, "relationship": relation,
                     "missing": missing, "reply": reply, "followup": followup,
                     "deadline": local(lead.get("Next_Followup_At")),
                     "quote": quote, "quote_reason": quote_reason,
                     "action": action, "reason": reason, "last_activity": last_activity,
                     "draft": draft, "neglected": is_neglected,
                     "modified_at": modified.isoformat()})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    rows.sort(key=lambda x: (order[x["priority"]], x["followup"] not in {
        "REPLIED — REVIEW RESPONSE", "OVERDUE", "DUE"},
        x["duplicate"] != "DUPLICATE IN CRM", x["relationship"]["state"] != "SUGGESTED",
        -aware(x["modified_at"]).timestamp()))
    summary = {
        "needs_attention_now": sum(x["priority"] != "LOW" and x["followup"] != "WAIT" for x in rows),
        "waiting_for_reply": sum(x["followup"] == "WAIT" and x["reply"] == "NO_REPLY_YET" for x in rows),
        "replies_needing_response": sum(x["followup"] == "REPLIED — REVIEW RESPONSE" for x in rows),
        "followup_due": sum(x["followup"] == "DUE" for x in rows),
        "overdue": sum(x["followup"] == "OVERDUE" for x in rows),
        "neglected": sum(x["neglected"] for x in rows),
        "potentially_quote_ready": sum(x["quote"] == "READY FOR QUOTE" for x in rows),
        "missing_critical_information": sum(bool(x["missing"]) for x in rows),
        "new_or_unreviewed": sum(x["status"] == "Unreviewed" for x in rows),
    }
    return {"label": "Bounded live CRM validation sample", "read_at": local(now.isoformat()),
            "sample_count": len(rows), "all_leads_in_crm": leads_complete,
            "summary": summary, "rows": rows, "writes_enabled": False}


def build_sales_queue(client, db_path, *, account_id, from_address, now=None):
    clock = now or datetime.now(timezone.utc)
    leads, complete = _list(client, "Leads", FIELDS, 15)
    contacts, contacts_complete = _list(client, "Contacts", "id,Email,Full_Name,Account_Name", 100)
    accounts, accounts_complete = _list(client, "Accounts", "id,Account_Name", 100)
    controlled = None
    if any(str(x["id"]) == CONTROLLED_LEAD_ID for x in leads):
        controlled = build_sales_operator_view(client, db_path, account_id=account_id,
                                               from_address=from_address, now=clock)
    return analyze_queue(leads, contacts, accounts, controlled, now=clock,
                         leads_complete=complete, relationships_complete=contacts_complete and accounts_complete)


def render_sales_queue(view):
    h = lambda x: escape(str(x if x is not None else "—"), quote=True)
    labels = [("needs_attention_now", "Needs review now"), ("waiting_for_reply", "Waiting for reply"),
              ("replies_needing_response", "Replies needing response"), ("followup_due", "Follow-up due"),
              ("overdue", "Overdue"), ("potentially_quote_ready", "Potentially quote-ready"),
              ("missing_critical_information", "Missing critical information"),
              ("new_or_unreviewed", "New / unreviewed")]
    cards = "".join(f"<div class='stat'><b>{h(view['summary'][key])}</b><span>{h(label)}</span></div>"
                    for key, label in labels)
    rows = []
    for item in view["rows"]:
        relation = item["relationship"]
        links = ", ".join("Contact " + h(x) for x in relation["contact_ids"]) or ""
        links += (", " if links and relation["account_ids"] else "") + (
            ", ".join("Account " + h(x) for x in relation["account_ids"]))
        missing = ", ".join(h(x) for x in item["missing"]) or "None identified"
        draft = item["draft"]
        draft_html = (f"<details><summary>{h(draft.get('label') or 'DRAFT — NOT SENT')}</summary>"
                      f"<b>{h(draft['subject'])}</b><pre>{h(draft['body'])}</pre>"
                      f"<p class='note'>{h(draft.get('use_condition'))}</p></details>") if draft else ""
        rows.append(
            f"<article><div class='top'><h2>{h(item['name'])} <small>{h(item['company'])}</small></h2>"
            f"<strong class='{h(item['priority'].lower())}'>{h(item['priority'])}</strong></div>"
            f"<p>Lead {h(item['id'])} · {h(item['status'])} · {h(item['source'])} · {h(item['email'])}</p>"
            f"<p><b>Work:</b> {h(item['action'])} <span class='note'>{h(item['reason'])}</span></p>"
            f"<p><b>Qualification:</b> {h(item['qualification'])} · <b>Quote:</b> {h(item['quote'])}"
            f" <span class='note'>{h(item['quote_reason'])}</span></p>"
            f"<p><b>Reply:</b> {h(item['reply'])} · <b>Follow-up:</b> {h(item['followup'])}"
            f" · <b>CRM deadline:</b> {h(item['deadline'])}</p>"
            f"<p><b>Missing:</b> {missing}</p>"
            f"<p><b>Identity:</b> {h(item['duplicate'])} · {h(relation['state'])} {links}</p>"
            f"<p class='note'>{h(item['last_activity'])}</p>{draft_html}</article>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OptiBrain sales queue</title><style>
body{{font:16px/1.45 system-ui,sans-serif;max-width:1100px;margin:1.5rem auto;padding:0 1rem;color:#182536;background:#f7f9fc}}
h1{{font-size:1.6rem;margin-bottom:.2rem}}h2{{font-size:1.1rem;margin:0}}small{{font-weight:400;color:#526174}}
article,.stat{{background:white;border:1px solid #d9e1eb;border-radius:10px;padding:1rem;margin:.6rem 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.4rem}}
.stat b{{display:block;font-size:1.5rem}}.stat span,.note{{color:#526174}}.top{{display:flex;justify-content:space-between;gap:1rem}}
.high{{color:#a32525}}.medium{{color:#805000}}.low{{color:#2b6670}}p{{margin:.3rem 0}}pre{{white-space:pre-wrap;font:inherit}}
</style></head><body><h1>What should I work on now?</h1>
<p class="note">{h(view['label'])} · {h(view['sample_count'])} Leads · read {h(view['read_at'])} · Read only. Mail checked only for the controlled Lead; other inbox states require review.</p>
<div class="grid">{cards}</div>{''.join(rows)}</body></html>"""
