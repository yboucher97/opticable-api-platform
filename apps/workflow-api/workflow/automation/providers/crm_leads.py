"""CRM hints -> versioned lead review events -> bounded Phase 3 actions.

No conversion, merge, owner reassignment, communication, or accounting writes.
First/last attribution and site/account/contact relationships stay provider-owned.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re

from ...zoho_gateway import ZohoWriteUnconfirmedError
from ..desired_journal import DesiredJournal
from ..crm_inventory import normalize
from ..event_schema import canonical, digest
from ..events import EventLedger
from ..models import AutomationEvent, utc_now_iso

FIELDS = "id,Email,Phone,Mobile,Normalized_Email,Normalized_Phone,Modified_Time,Created_Time,Lead_Status,Converted__s,Service_Types,City,State,Ingestion_Source,Next_Followup_At,Email_Opt_Out"


def records(response, *, empty=False):
    if empty and response.get("ok") is True and response.get("status") == 204:
        return []
    rows = (response.get("data") or {}).get("data")
    if response.get("ok") is not True or response.get("status") != 200 or not isinstance(rows, list):
        raise ValueError("CRM record read failed closed")
    return rows


def lead_plan(record, *, now=None):
    if not re.fullmatch(r"[0-9]{1,30}", str(record.get("id", ""))):
        raise ValueError("Invalid lead id")
    version = record.get("Modified_Time")
    when = datetime.fromisoformat(str(version).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("Lead version lacks timezone")
    patch = {}
    email = str(record.get("Email") or "").strip().casefold()
    if email and "@" in email and record.get("Normalized_Email") != email:
        patch["Normalized_Email"] = email
    phone = str(record.get("Phone") or record.get("Mobile") or "").strip()
    # Preserve international prefix; do not guess country/extension semantics.
    if phone and re.fullmatch(r"\+?[0-9 ()\-.]{7,30}", phone):
        normalized = ("+" if phone.startswith("+") else "") + re.sub(r"\D", "", phone)
        if record.get("Normalized_Phone") != normalized:
            patch["Normalized_Phone"] = normalized
    active = record.get("Converted__s") is False and record.get("Lead_Status") in {"Not Contacted", "Attempted to Contact", "Contact in Future", "Pre-Qualified"}
    stamp = datetime.fromisoformat(str(record.get("Created_Time") or version).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Lead creation lacks timezone")
    stale = active and ((now or datetime.now(timezone.utc)) - stamp).total_seconds() >= 86400
    return {"lead_id": str(record["id"]), "version": when.astimezone(timezone.utc).isoformat(),
            "patch": patch if record.get("Converted__s") is False else {}, "followup": active,
            "stale": stale, "needs_human": active, "routing": normalize({k: record.get(k) for k in ("Service_Types", "City", "State", "Ingestion_Source")})}


def register_crm_lead_actions(engine, client, store):
    ledger, journal = EventLedger(store), DesiredJournal(store)

    def read_lead(identity):
        if not re.fullmatch(r"[0-9]{1,30}", str(identity)):
            raise ValueError("Invalid lead id")
        rows = records(client.request("zohoapis", "GET", "/crm/v8/Leads/" + identity, query={"fields": FIELDS}))
        if len(rows) != 1 or str(rows[0].get("id")) != identity:
            raise ValueError("Lead hydration identity mismatch")
        return rows[0]

    def observe(context, step):
        event = context["event"]
        ids = event["payload"].get("ids", [])
        if not 1 <= len(ids) <= 10 or len(set(ids)) != len(ids):
            raise ValueError("Lead notification batch requires bounded reviewed reconciliation")
        emitted = []
        for identity in ids:
            plan = lead_plan(read_lead(identity))
            # Different notifications for the same record version collapse.
            child = AutomationEvent(event_type="opticable.crm.lead.reviewed", source="crm-lead-observer",
                source_account=event.get("source_account"), provider_event_id=digest([identity, plan["version"]]),
                subject_type="Leads", subject_id=identity, causation_id=event["event_id"],
                correlation_id=event.get("correlation_id"), depth=event.get("depth", 0) + 1,
                payload={"lead_id": identity, "version": plan["version"]})
            # Alert and event must survive (or roll back) together. A restart
            # after capture cannot permanently suppress the internal alert.
            with store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                accepted, child_id, _ = ledger._capture(conn, child)
                if accepted:
                    metadata = {"event_id": child_id, "version": plan["version"], "stale": plan["stale"],
                                "routing": plan["routing"], "patch_hash": digest(plan["patch"]),
                                "next_action": "review_lead" if plan["followup"] else "none"}
                    conn.execute("INSERT INTO automation_audit(at,category,action,actor,correlation_id,target,success,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                        (utc_now_iso(), "crm_lead_review", "human_followup" if plan["needs_human"] else "observed",
                         "automation-engine", event.get("correlation_id"), identity, 1, canonical(metadata)))
            emitted.append(child_id)
        return {"review_event_ids": emitted}

    def write_once(key, body, path, method, verify, *, headers=None):
        if journal.unresolved(key):
            raise ZohoWriteUnconfirmedError("Previous CRM write requires human reconciliation")
        evidence = {"provider": "zoho_crm", "path": path, "body_hash": digest(body), "policy": "phase5-lead-v1"}
        journal.record("started", key, evidence, "phase3-crm-lead-action")
        try:
            response = client.request("zohoapis", method, path, body=body, headers=headers or {},
                                      reason="Phase 5 bounded internal lead lifecycle", confirm=True)
            rows = (response.get("data") or {}).get("data")
            if response.get("ok") is not True or response.get("status") not in {200, 201, 202} or not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "success":
                raise ZohoWriteUnconfirmedError("CRM write outcome is unverified")
            operation = str((rows[0].get("details") or {}).get("id") or "")
            if not verify(operation):
                raise ZohoWriteUnconfirmedError("CRM post-write verification requires human review")
        except Exception as exc:
            journal.record("manual", key, {**evidence, "error": type(exc).__name__}, "phase3-crm-lead-action")
            raise ZohoWriteUnconfirmedError("CRM provider outcome requires human reconciliation") from None
        journal.record("verified", key, {**evidence, "operation_id": operation,
                         "request_id": response.get("request_id"), "verification": True}, "phase3-crm-lead-action")
        return operation

    def reconcile(context, step):
        identity = str(context["event"]["payload"]["lead_id"])
        if os.environ.get("OPTIBRAIN_CRM_LEAD_WRITES") != "phase5-lead-v1":
            return {"mode": "observe", "lead_id": identity}
        with journal.lock():
            record = read_lead(identity)
            plan = lead_plan(record)
            if plan["version"] != context["event"]["payload"]["version"]:
                return {"mode": "superseded", "lead_id": identity}
            if plan["patch"]:
                key = "crm-lead-normalize:" + identity
                def verify_normalization(_):
                    current = read_lead(identity)
                    return all(current.get(k) == v for k, v in plan["patch"].items())
                write_once(key, {"data": [{"id": identity, **plan["patch"]}], "trigger": [],
                                "skip_feature_execution": [{"name": "cadences"}]},
                           "/crm/v8/Leads/" + identity, "PUT",
                           verify_normalization, headers={"If-Unmodified-Since": record["Modified_Time"]})
            task_key, task_id = "crm-lead-followup:" + identity, None
            if journal.unresolved(task_key):
                raise ZohoWriteUnconfirmedError("Follow-up creation requires reconciliation")
            previous = journal.last(task_key, ("verified",))
            if plan["followup"] and previous is None:
                subject = "OptiBrain follow-up " + identity
                tasks = records(client.request("zohoapis", "GET", "/crm/v8/Tasks/search",
                    query={"criteria": "(Subject:equals:" + subject + ")", "per_page": 2}), empty=True)
                if len(tasks) > 1 or (tasks and str((tasks[0].get("Who_Id") or {}).get("id")) != identity):
                    raise ValueError("Follow-up task identity collision")
                if tasks:
                    task_id = str(tasks[0]["id"])
                    journal.record("verified", task_key, {"operation_id": task_id, "verification": True, "reconciled": True}, "phase3-crm-lead-action")
                else:
                    due = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
                    def verify_task(operation):
                        rows = records(client.request("zohoapis", "GET", "/crm/v8/Tasks/" + operation))
                        return len(rows) == 1 and rows[0].get("Subject") == subject and str((rows[0].get("Who_Id") or {}).get("id")) == identity
                    task_id = write_once(task_key, {"data": [{"Subject": subject, "Who_Id": identity,
                        "$se_module": "Leads", "Status": "Not Started", "Due_Date": due}], "trigger": []},
                        "/crm/v8/Tasks", "POST", verify_task)
            elif previous:
                task_id = previous["metadata"].get("operation_id")
            return {"mode": "reconciled", "lead_id": identity, "task_id": task_id,
                    "normalized": bool(plan["patch"])}

    engine.register_action("crm.lead.observe", observe, retry_safe=True)
    engine.register_action("crm.lead.reconcile", reconcile)  # Never retry a provider write.
