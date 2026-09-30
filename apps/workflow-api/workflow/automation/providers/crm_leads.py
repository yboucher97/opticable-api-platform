"""CRM hints -> versioned lead review events -> bounded internal actions.

No conversion, merge, owner reassignment, customer communication, or accounting
writes. Phase 6 extends the existing Phase 5 writer rather than creating a
parallel provider mutation path.
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
from ..sales_decision import (
    POLICY_VERSION as PHASE6_POLICY,
    SalesDecision,
    TORONTO,
    build_sales_decision,
    validate_sales_decision,
)

PHASE5_POLICY = "phase5-lead-v1"

FIELDS = "id,Email,Phone,Mobile,Normalized_Email,Normalized_Phone,Modified_Time,Created_Time,Lead_Status,Converted__s,Service_Types,City,State,Ingestion_Source,Next_Followup_At,Email_Opt_Out"


def records(response, *, empty=False):
    if empty and response.get("ok") is True and response.get("status") in {204, 304}:
        return []
    rows = (response.get("data") or {}).get("data")
    if response.get("ok") is not True or response.get("status") != 200 or not isinstance(rows, list):
        raise ValueError("CRM record read failed closed")
    return rows


def _normalization_patch(record):
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
    return patch


def _utc_iso(value):
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("CRM timestamp lacks timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _field_subset(record, fields):
    value = {}
    for field in sorted(set(fields)):
        current = record.get(field)
        if field == "Next_Followup_At":
            current = _utc_iso(current)
        value[field] = current
    return value


def _phase5_task_due(now: datetime) -> str:
    """The legacy Phase 5 task Due_Date is a Montreal business date."""
    if now.tzinfo is None:
        raise ValueError("Task clock lacks timezone")
    return (now.astimezone(TORONTO).date() + timedelta(days=1)).isoformat()


def lead_plan(record, *, now=None):
    if not re.fullmatch(r"[0-9]{1,30}", str(record.get("id", ""))):
        raise ValueError("Invalid lead id")
    version = record.get("Modified_Time")
    when = datetime.fromisoformat(str(version).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("Lead version lacks timezone")
    patch = _normalization_patch(record)
    active = record.get("Converted__s") is False and record.get("Lead_Status") in {"Not Contacted", "Attempted to Contact", "Contact in Future", "Pre-Qualified"}
    stamp = datetime.fromisoformat(str(record.get("Created_Time") or version).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Lead creation lacks timezone")
    stale = active and ((now or datetime.now(timezone.utc)) - stamp).total_seconds() >= 86400
    return {"lead_id": str(record["id"]), "version": when.astimezone(timezone.utc).isoformat(),
            "patch": patch if record.get("Converted__s") is False else {}, "followup": active,
            "stale": stale, "needs_human": active, "routing": normalize({k: record.get(k) for k in ("Service_Types", "City", "State", "Ingestion_Source")})}


def phase6_lead_patch(record, decision: SalesDecision):
    """Return the only Lead fields Phase 6 may mutate automatically."""

    identity = str(record.get("id") or "")
    if decision.lead_id != identity or decision.version != _utc_iso(record.get("Modified_Time")):
        raise ValueError("Sales decision does not match current Lead version")
    if record.get("Converted__s") is not False:
        return {}

    patch = _normalization_patch(record)
    if decision.active and decision.followup_at:
        current = _utc_iso(record.get("Next_Followup_At"))
        desired = _utc_iso(decision.followup_at)
        if current != desired:
            patch["Next_Followup_At"] = desired

    existing_service = str(record.get("Service_Types") or "").strip()
    if (
        not existing_service
        and decision.service_type_source == "trusted_hint"
        and decision.service_type
    ):
        patch["Service_Types"] = decision.service_type

    allowed = {"Normalized_Email", "Normalized_Phone", "Next_Followup_At", "Service_Types"}
    if not set(patch).issubset(allowed):
        raise ValueError("Phase 6 Lead patch escaped allowlist")
    return patch


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
        observed_at = datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            raise ValueError("Lead observation time lacks timezone")
        emitted = []
        for identity in ids:
            record = read_lead(identity)
            plan = lead_plan(record, now=observed_at)
            decision = build_sales_decision(record, now=observed_at)
            # Different notifications for the same provider record version collapse.
            child = AutomationEvent(event_type="opticable.crm.lead.reviewed", source="crm-lead-observer",
                source_account=event.get("source_account"), provider_event_id=digest([identity, plan["version"]]),
                subject_type="Leads", subject_id=identity, causation_id=event["event_id"],
                correlation_id=event.get("correlation_id"), depth=event.get("depth", 0) + 1,
                payload={"lead_id": identity, "version": plan["version"],
                         "sales_decision": decision.model_dump()})
            # Alert and event must survive (or roll back) together. A restart
            # after capture cannot permanently suppress the internal alert.
            with store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                accepted, child_id, _ = ledger._capture(conn, child)
                if accepted:
                    metadata = {"event_id": child_id, "version": plan["version"], "stale": plan["stale"],
                                "routing": plan["routing"], "patch_hash": digest(plan["patch"]),
                                "decision_hash": decision.decision_hash, "priority": decision.priority,
                                "next_action": decision.next_action, "followup_at": decision.followup_at}
                    conn.execute("INSERT INTO automation_audit(at,category,action,actor,correlation_id,target,success,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                        (utc_now_iso(), "crm_lead_review", "human_followup" if plan["needs_human"] else "observed",
                         "automation-engine", event.get("correlation_id"), identity, 1, canonical(metadata)))
            emitted.append(child_id)
        return {"review_event_ids": emitted}

    def write_once(key, body, path, method, verify, *, headers=None, policy=PHASE5_POLICY,
                   actor="phase3-crm-lead-action", desired_subset=None):
        if journal.unresolved(key):
            raise ZohoWriteUnconfirmedError("Previous CRM write requires human reconciliation")
        evidence = {"provider": "zoho_crm", "path": path, "body_hash": digest(body), "policy": policy}
        if isinstance(desired_subset, dict) and desired_subset:
            evidence.update(fields=sorted(desired_subset), desired_hash=digest(desired_subset))
        journal.record("started", key, evidence, actor)
        try:
            from ..crm_write_boundary import reviewed_reconciler_call
            if policy == PHASE6_POLICY:
                with reviewed_reconciler_call(client, method, path, body, headers or {}, policy):
                    response = client.request("zohoapis", method, path, body=body, headers=headers or {},
                                              reason="Phase 6 bounded internal lead lifecycle", confirm=True)
            else:
                response = client.request("zohoapis", method, path, body=body, headers=headers or {},
                                          reason="Phase 5 bounded internal lead lifecycle", confirm=True)
            rows = (response.get("data") or {}).get("data")
            if response.get("ok") is not True or response.get("status") not in {200, 201, 202} or not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "success":
                raise ZohoWriteUnconfirmedError("CRM write outcome is unverified")
            operation = str((rows[0].get("details") or {}).get("id") or "")
            if not verify(operation):
                raise ZohoWriteUnconfirmedError("CRM post-write verification requires human review")
        except Exception as exc:
            journal.record("manual", key, {**evidence, "error": type(exc).__name__}, actor)
            raise ZohoWriteUnconfirmedError("CRM provider outcome requires human reconciliation") from None
        journal.record("verified", key, {**evidence, "operation_id": operation,
                         "request_id": response.get("request_id"), "verification": True}, actor)
        return operation

    def phase5_reconcile(identity, context):
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
                due = _phase5_task_due(datetime.now(timezone.utc))
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

    def reconcile_phase6_lead_ambiguity(key, record):
        if not journal.unresolved(key):
            return False
        previous = journal.last(key, ("started", "manual"))
        metadata = previous["metadata"] if previous else {}
        fields = metadata.get("fields")
        expected_hash = metadata.get("desired_hash")
        if not isinstance(fields, list) or not fields or not isinstance(expected_hash, str):
            raise ZohoWriteUnconfirmedError("Previous Phase 6 Lead write requires human reconciliation")
        current = _field_subset(record, fields)
        if digest(current) != expected_hash:
            raise ZohoWriteUnconfirmedError("Previous Phase 6 Lead write requires human reconciliation")
        journal.record("verified", key,
                       {"provider": "zoho_crm", "path": metadata.get("path"),
                        "body_hash": metadata.get("body_hash"), "policy": PHASE6_POLICY,
                        "fields": fields, "desired_hash": expected_hash,
                        "verification": True, "reconciled_by_readback": True},
                       "phase6-crm-lead-action")
        return True

    def phase6_decision(record, event):
        payload = event["payload"]
        supplied = payload.get("sales_decision")
        if supplied is not None:
            decision = validate_sales_decision(supplied)
        else:
            observed_at = datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
            decision = build_sales_decision(record, now=observed_at)
        if decision.lead_id != str(record.get("id")) or decision.version != _utc_iso(payload.get("version")):
            raise ValueError("Reviewed sales decision identity mismatch")
        return decision

    def phase6_task(identity, decision):
        if not decision.active or not decision.followup_at:
            return None
        generation = digest([PHASE6_POLICY, identity, decision.next_action, decision.followup_at])[:16]
        subject = ("OptiBrain " + decision.next_action.replace("_", " ") + " " + identity + " " + generation)[:120]
        task_key = "crm-lead-phase6-task:" + identity + ":" + generation
        due = datetime.fromisoformat(decision.followup_at.replace("Z", "+00:00")).astimezone(TORONTO).date().isoformat()

        def exact_task(task):
            return (re.fullmatch(r"[0-9]{1,30}", str(task.get("id") or "")) is not None
                    and task.get("Subject") == subject
                    and str((task.get("Who_Id") or {}).get("id")) == identity
                    and task.get("Due_Date") == due
                    and task.get("Status") in {"Not Started", "In Progress", "Completed"})

        def search_exact():
            tasks = records(client.request("zohoapis", "GET", "/crm/v8/Tasks/search",
                query={"criteria": "(Subject:equals:" + subject + ")", "per_page": 2}), empty=True)
            if len(tasks) > 1 or (tasks and not exact_task(tasks[0])):
                raise ValueError("Phase 6 follow-up task identity collision")
            return tasks

        if journal.unresolved(task_key):
            tasks = search_exact()
            if not tasks:
                raise ZohoWriteUnconfirmedError("Phase 6 follow-up creation requires human reconciliation")
            task_id = str(tasks[0]["id"])
            journal.record("verified", task_key,
                           {"operation_id": task_id, "verification": True, "reconciled_by_readback": True,
                            "policy": PHASE6_POLICY, "generation": generation},
                           "phase6-crm-lead-action")
            return task_id

        previous = journal.last(task_key, ("verified",))
        if previous:
            return previous["metadata"].get("operation_id")

        tasks = search_exact()
        if tasks:
            task_id = str(tasks[0]["id"])
            journal.record("verified", task_key,
                           {"operation_id": task_id, "verification": True, "reconciled": True,
                            "policy": PHASE6_POLICY, "generation": generation},
                           "phase6-crm-lead-action")
            return task_id

        def verify_task(operation):
            rows = records(client.request("zohoapis", "GET", "/crm/v8/Tasks/" + operation))
            return len(rows) == 1 and str(rows[0].get("id")) == operation and exact_task(rows[0])
        return write_once(task_key,
                          {"data": [{"Subject": subject, "Who_Id": identity, "$se_module": "Leads",
                                     "Status": "Not Started", "Due_Date": due}], "trigger": []},
                          "/crm/v8/Tasks", "POST", verify_task,
                          policy=PHASE6_POLICY, actor="phase6-crm-lead-action")

    def phase6_reconcile(identity, context):
        event = context["event"]
        record = read_lead(identity)
        reviewed_version = _utc_iso(event["payload"].get("version"))
        if _utc_iso(record.get("Modified_Time")) != reviewed_version:
            return {"mode": "superseded", "lead_id": identity}

        decision = phase6_decision(record, event)
        update_key = "crm-lead-phase6-update:" + identity
        reconciled_prior_write = reconcile_phase6_lead_ambiguity(update_key, record)
        patch = phase6_lead_patch(record, decision)
        updated_fields = sorted(patch)

        if patch:
            desired_subset = _field_subset(patch, patch.keys())
            def verify_lead(_):
                current = read_lead(identity)
                return _field_subset(current, patch.keys()) == desired_subset
            write_once(update_key,
                       {"data": [{"id": identity, **patch}], "trigger": [],
                        "skip_feature_execution": [{"name": "cadences"}]},
                       "/crm/v8/Leads/" + identity, "PUT", verify_lead,
                       headers={"If-Unmodified-Since": record["Modified_Time"]},
                       policy=PHASE6_POLICY, actor="phase6-crm-lead-action",
                       desired_subset=desired_subset)

        task_id = phase6_task(identity, decision)
        return {"mode": "phase6-reconciled", "lead_id": identity,
                "decision_hash": decision.decision_hash, "task_id": task_id,
                "updated_fields": updated_fields,
                "reconciled_prior_write": reconciled_prior_write}

    def reconcile(context, step):
        identity = str(context["event"]["payload"]["lead_id"])
        policy = os.environ.get("OPTIBRAIN_CRM_LEAD_WRITES", "")
        if policy not in {PHASE5_POLICY, PHASE6_POLICY}:
            return {"mode": "observe", "lead_id": identity}
        with journal.lock():
            if policy == PHASE6_POLICY:
                return phase6_reconcile(identity, context)
            return phase5_reconcile(identity, context)

    engine.register_action("crm.lead.observe", observe, retry_safe=True)
    engine.register_action("crm.lead.reconcile", reconcile)  # Never retry a provider write.
