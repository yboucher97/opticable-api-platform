"""Provider-backed Test Lab evaluation for the existing read-only sales queue.

Scenario names and provider IDs are never decision inputs. Synthetic CRM fields,
Task obligations, and thread-bound Mail evidence use the same rules for every row.
"""
from collections import Counter
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
ACTIVE = {"Not Contacted", "Attempted to Contact", "Contact in Future", "Pre-Qualified"}
SOURCE = {"test_ai_website": "AI website (simulated)",
          "test_main_website": "Main website (simulated)",
          "test_zoho_form": "Zoho Form (simulated)",
          "test_email_manual": "Email/manual (simulated)"}


def aware(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Test Lab business time needs an explicit offset")
    return parsed


def local(value):
    return aware(value).astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z") if value else None


def _task_for(lead_id, tasks):
    linked = []
    for task in tasks:
        relation = task.get("What_Id") or {}
        if isinstance(relation, dict) and str(relation.get("id")) == lead_id:
            linked.append(task)
    if len(linked) > 1:
        raise ValueError("Multiple Test Lab Tasks for one Lead require review")
    return linked[0] if linked else None


def _draft(lead, row, mail, followup):
    """A preview, never an executable send instruction."""
    if (row["duplicate"].startswith("DUPLICATE") or followup in {"WAIT", "AMBIGUOUS"}
            or row.get("state") == "LOW PRIORITY"):
        return None
    service = str(lead.get("Service_Types") or "your project").strip()
    scope = str(lead.get("Scope") or "").strip()
    place = str(lead.get("City") or "Montreal").strip()
    missing = row["missing"]
    if mail and mail["reply_state"] == "REPLIED":
        facts = mail.get("reply_facts") or {}
        site = str(facts.get("site address") or "").rstrip(". ")
        scope = str(facts.get("scope") or "").rstrip(". ")
        timeline = str(facts.get("timeline") or "").rstrip(". ")
        details = (f" I noted the site at {site}." if site else "")
        details += (f" The scope you described is {scope[0].lower() + scope[1:]}." if scope else "")
        details += (f" Your stated timeline is {timeline[0].lower() + timeline[1:]}." if timeline else "")
        unanswered = [item for item in missing if not item.startswith("Verify ")]
        body = ("DRAFT — NOT SENT\nReview the verified reply before use.\n\n"
                "Hello,\n\nThank you for the update about your " + service + " project."
                + (details if details else " I will review the details you shared.") + " "
                + ("Could you also confirm " + ", ".join(unanswered[:3]).lower() + "?" if unanswered else
                   "I will review whether a site visit is needed and follow up on quote next steps.")
                + "\n\nThe Opticable team")
        subject = "Re: your Opticable test inquiry"
    elif row["quote"] == "READY FOR QUOTE":
        body = ("DRAFT — NOT SENT\nSynthetic recipient; operator review required.\n\n"
                f"Hello,\n\nThank you for the {service} inquiry for {place}. "
                f"We have the proposed scope ({scope}) and target timeline. "
                "I will review the technical details and prepare a human-reviewed quote.\n\nThe Opticable team")
        subject = "Next steps for your Opticable project"
    elif followup in {"DUE", "OVERDUE"} and mail and mail["reply_state"] == "NO_REPLY_YET":
        body = ("DRAFT — NOT SENT\nRecheck the inbox before use.\n\n"
                f"Hello,\n\nI’m following up on my previous note about {service} in {place}. "
                + ("Could you confirm " + ", ".join(missing[:3]).lower() + "?" if missing else
                   "Would you like to review the next steps?")
                + "\n\nThe Opticable team")
        subject = "Following up on your Opticable test inquiry"
    else:
        questions = ", ".join(missing[:3]).lower() or "the project requirements"
        body = ("DRAFT — NOT SENT\nSynthetic recipient; operator review required.\n\n"
                f"Hello,\n\nTo assess the {service} inquiry, could you confirm {questions}? "
                "This will help us determine the right next step before a quote.\n\nThe Opticable team")
        subject = "A few details about your Opticable project"
    return {"label": "DRAFT — NOT SENT", "subject": subject, "body": body,
            "use_condition": "Synthetic Test Lab preview. Human review and fresh inbox check required."}


def enhance_lab_queue(view, leads, contacts, accounts, deals, tasks, mail_by_id, *, now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Queue clock requires timezone")
    lead_map = {str(x["id"]): x for x in leads}
    for row in view["rows"]:
        lead = lead_map[row["id"]]
        if lead.get("OptiBrain_Test") is not True or not str(lead.get("Description") or "").startswith("OPTIBRAIN TEST — PHASE "):
            raise ValueError("Test Lab Lead marker missing")
        row["test_only"] = True
        source = str(lead.get("Ingestion_Source") or "")
        row["source"] = SOURCE.get(source, {"ai_website": "AI website", "opticable_website": "Main-origin connector", "manual_crm": "Manual CRM"}.get(source, "Unknown" if not source else "Unrecognized source"))
        row["source_basis"] = ("CRM Ingestion_Source from provider-backed intake" if source in {"ai_website", "opticable_website", "manual_crm"}
                               else "No source metadata in CRM" if not source else
                               "CRM Ingestion_Source on synthetic record; channel is simulated")
        task = _task_for(row["id"], tasks)
        deadline = aware(lead["Next_Followup_At"]) if lead.get("Next_Followup_At") else None
        if task and deadline and task.get("Due_Date") != deadline.astimezone(TORONTO).date().isoformat():
            raise ValueError("Task and CRM follow-up date disagree")
        row["task"] = {"id": str(task["id"]), "due_date": task.get("Due_Date"),
                       "status": task.get("Status")} if task else None
        mail = mail_by_id.get(row["id"])
        reply = mail["reply_state"] if mail else "NO OUTBOUND RECORDED"
        row["reply"] = reply
        row["new_from_reply"] = list(mail.get("new_information") or []) if reply == "REPLIED" else []
        if reply == "REPLIED":
            facts = mail.get("reply_facts") or {}
            for field, key in (("Service requirements", "service"), ("Site address", "site address"),
                               ("Project scope", "scope"), ("Target timeline", "timeline")):
                if field in row["missing"] and facts.get(key):
                    row["missing"][row["missing"].index(field)] = "Verify " + field.lower() + " from reply"
            if facts.get("scope") and not lead.get("Scope"):
                row["quote_reason"] = ("The linked reply supplies project scope; verify it and record it in CRM "
                                       "before preparing a human quote.")
        row["last_activity"] = ("Verified inbound " + mail["last_inbound"]["received_at_local"]
                                if mail and mail.get("last_inbound") else
                                "Verified outbound " + mail["last_outbound"]["sent_at_local"]
                                if mail and mail.get("last_outbound") else
                                "No verified contact activity; CRM created " + local(lead.get("Created_Time")))
        if mail and mail["reply_state"] == "REPLIED":
            followup = "REPLIED — REVIEW RESPONSE"
        elif mail and mail["reply_state"] == "AMBIGUOUS":
            followup = "AMBIGUOUS"
        elif deadline and task and task.get("Status") in {"Not Started", "Deferred", "In Progress"}:
            if mail and mail.get("last_outbound") and now - aware(mail["last_outbound"]["sent_at"]) < timedelta(hours=24):
                followup = "WAIT"  # Recent send prevents duplicate contact even if deadline changed.
            elif deadline > now:
                followup = "WAIT"
            elif now - deadline < timedelta(hours=24):
                followup = "DUE"
            else:
                followup = "OVERDUE"
        elif deadline and deadline > now and mail and mail["reply_state"] == "NO_REPLY_YET":
            followup = "WAIT"
        elif deadline and deadline <= now and mail and mail["reply_state"] == "NO_REPLY_YET":
            followup = "DUE" if now - deadline < timedelta(hours=24) else "OVERDUE"
        else:
            followup = "NO VERIFIED DEADLINE"
        row["followup"] = followup
        row["neglected"] = bool(followup == "OVERDUE" and row["status"] in ACTIVE
                                and reply != "REPLIED" and (not mail or not mail.get("last_outbound")
                                or now - aware(mail["last_outbound"]["sent_at"]) >= timedelta(hours=48)))
        row["state"] = ("POSSIBLE DUPLICATE" if row["duplicate"].startswith("DUPLICATE") else
                        "REPLIED — NEEDS RESPONSE" if followup == "REPLIED — REVIEW RESPONSE" else
                        "NEGLECTED / OVERDUE" if row["neglected"] else
                        "FOLLOW-UP DUE" if followup == "DUE" else
                        "WAITING FOR REPLY" if followup == "WAIT" and mail else
                        "FOLLOW-UP SCHEDULED" if followup == "WAIT" else
                        "QUOTE READY" if row["quote"] == "READY FOR QUOTE" else
                        "NEEDS INFORMATION" if row["missing"] else "REVIEW")
        if row["duplicate"].startswith("DUPLICATE"):
            row.update(priority="MEDIUM", action="Review possible duplicate identity",
                       reason="Two Test Lab Leads have the same exact email; no automatic merge or outreach.")
        elif followup == "REPLIED — REVIEW RESPONSE":
            row.update(priority="HIGH", action="Review the linked reply, confirm new details, and respond",
                       reason="Verified thread-bound reply supplies new project details; review them before responding.")
        elif followup == "AMBIGUOUS":
            row.update(priority="MEDIUM", action="Resolve Mail identity before outreach",
                       reason="The exact thread association is ambiguous; suppress automated outreach.")
        elif row["neglected"]:
            row.update(priority="HIGH", action="Review missed follow-up obligation now",
                       reason="Open CRM Task and elapsed deadline; no reply or recent outbound is evidenced.")
        elif followup == "DUE":
            row.update(priority="HIGH", action="Review inbox, then complete due follow-up",
                       reason="Open CRM follow-up obligation has reached its Montreal deadline.")
        elif followup == "WAIT":
            row.update(priority="LOW", action="Wait until the scheduled follow-up; monitor for reply",
                       reason="Recent outbound or future CRM deadline means another message is premature.")
        elif row["quote"] == "READY FOR QUOTE":
            timeline = str(lead.get("Project_Timeline") or "").casefold()
            urgency = bool(re.search(r"urgent|within [0-9]+ (day|week)|this week|asap", timeline))
            row.update(priority="HIGH", action="Review scope and prepare a human quote",
                       reason="Recorded service, site, scope and timeline support quote review."
                              + (" Near-term timeline raises urgency." if urgency else ""))
        elif (not lead.get("Service_Types") and not lead.get("Scope") and not deadline
              and re.search(r"no project planned|research only|just exploring|no current project",
                            str(lead.get("Project_Timeline") or "") + " " + str(lead.get("Description") or ""), re.I)):
            row.update(priority="LOW", action="Qualify only if the prospect confirms a project",
                       reason="No service, scope or committed follow-up; age alone does not make this urgent.")
            row["state"] = "LOW PRIORITY"
        else:
            row.update(priority="MEDIUM", action="Ask for missing project details before quoting",
                       reason="Open inquiry needs " + ", ".join(row["missing"][:3]).lower() + ".")
        row["qualification"] = ("Reply received — confirm reported scope" if reply == "REPLIED" and
                                (mail.get("reply_facts") or {}).get("scope") and not lead.get("Scope") else
                                "Quote review" if row["quote"] == "READY FOR QUOTE" else
                                "Discovery needed" if row["status"] in ACTIVE else "Status review")
        row["draft"] = _draft(lead, row, mail, followup)
        row["mail"] = {"last_outbound": mail.get("last_outbound"), "last_inbound": mail.get("last_inbound"),
                       "reply_state": reply} if mail else None
        contacts_found = set(row["relationship"]["contact_ids"])
        accounts_found = set(row["relationship"]["account_ids"])
        verified = []
        for contact in contacts:
            if str(contact.get("id")) not in contacts_found:
                continue
            linked = contact.get("Account_Name") or {}
            account_id = str(linked.get("id")) if isinstance(linked, dict) else ""
            if account_id in accounts_found:
                verified.append("Contact " + str(contact["id"]) + " → Account " + account_id)
                for deal in deals:
                    deal_account = deal.get("Account_Name") or {}
                    deal_contact = deal.get("Contact_Name") or {}
                    if (isinstance(deal_account, dict) and isinstance(deal_contact, dict)
                            and str(deal_account.get("id")) == account_id
                            and str(deal_contact.get("id")) == str(contact["id"])):
                        verified.append("Account/Contact → Deal " + str(deal["id"]))
        row["relationship"]["verified_links"] = verified
        if verified:
            row["relationship"]["basis"] = "Lead match is suggested; listed Contact/Account/Deal links are verified in CRM"
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    state_order = {"REPLIED — NEEDS RESPONSE": 0, "NEGLECTED / OVERDUE": 1,
                   "FOLLOW-UP DUE": 2, "QUOTE READY": 3, "NEEDS INFORMATION": 4,
                   "POSSIBLE DUPLICATE": 5, "WAITING FOR REPLY": 8}
    view["rows"].sort(key=lambda row: (order[row["priority"]], state_order.get(row["state"], 6),
                                        -aware(row["modified_at"]).timestamp()))
    summary = Counter({key: 0 for key in ("high_priority", "low_priority", "possible_duplicates",
                       "needs_attention_now", "waiting_for_reply", "replies_needing_response",
                       "followup_due", "overdue", "neglected", "potentially_quote_ready",
                       "missing_critical_information", "new_or_unreviewed")})
    for row in view["rows"]:
        summary["high_priority"] += row["priority"] == "HIGH"
        summary["low_priority"] += row["priority"] == "LOW"
        summary["possible_duplicates"] += row["state"] == "POSSIBLE DUPLICATE"
        summary["needs_attention_now"] += row["priority"] != "LOW" and row["followup"] != "WAIT"
        summary["waiting_for_reply"] += row["state"] == "WAITING FOR REPLY"
        summary["replies_needing_response"] += row["state"] == "REPLIED — NEEDS RESPONSE"
        summary["followup_due"] += row["followup"] == "DUE"
        summary["overdue"] += row["followup"] == "OVERDUE"
        summary["neglected"] += row["neglected"]
        summary["potentially_quote_ready"] += row["quote"] == "READY FOR QUOTE"
        summary["missing_critical_information"] += bool(row["missing"])
        summary["new_or_unreviewed"] += row["status"] == "Not Contacted"
    view["summary"] = dict(summary)
    view["label"] = "Isolated provider-backed OPTIBRAIN TEST sample; excluded from live pipeline"
    view["scope"] = "lab"
    return view
