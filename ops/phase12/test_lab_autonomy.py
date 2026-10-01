#!/usr/bin/env python3
"""One-shot provider-backed Phase 12 proof. Never called by a timer.

Every CRM mutation still passes through the existing exact-call Test Lab firewall.
An interrupted or uncertain action must be reconciled from Zoho before any retry.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "apps/workflow-api"))
sys.path.insert(0, str(HERE.parent / "phase11"))
from workflow.automation.business_autonomy import (Action, BusinessJournal, Policy,
    classify_crm_record, decide, digest, dispatch, reconcile_ambiguous)
from test_lab_operations import (LAB, BASELINE, STATE, load, owned, provider, read,
    write)
from onboard_test_deal import ACCOUNT, CONTACT, onboard

DB = Path("/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db")
EVIDENCE = Path("/var/lib/optibrain/phase12/test-lab/evidence.json")
TASK = "5062683000007908026"
CONTROLLED_LEAD = "5062683000007915001"
POLICY = Policy(automatic_mutations=True, auto_test_task=True,
                auto_test_project=True, auto_test_internal=True)


def save_evidence(value: dict) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    temp = EVIDENCE.with_name(".evidence.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush(); os.fsync(handle.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, EVIDENCE)


def context():
    client = provider()
    lab, baseline, state = load(LAB), load(BASELINE), load(STATE)
    journal = BusinessJournal(DB)
    return client, lab, baseline, state, journal


def ownership(module: str, row: dict, lab: dict, baseline: dict) -> str:
    return classify_crm_record(module, row,
        registered_test_ids=set(lab["records"].get(module, [])),
        protected_ids=set(baseline["modules"][module]["ids"]))


def fresh(client, lab, baseline, module, identity):
    row = read(client, module, identity)
    row["ownership"] = ownership(module, row, lab, baseline)
    return row


def status_update(client, lab, baseline, state, journal, *, status: str,
                  key: str, lose_ack: bool = False):
    before = fresh(client, lab, baseline, "Tasks", TASK)
    if before["ownership"] != "TEST_ONLY": raise ValueError("Task ownership changed")
    action = Action("crm.task.update", "Tasks", TASK, key, {"Status": status},
                    expected_version=before["Modified_Time"],
                    expected_state={"Status": before["Status"]})
    def execute():
        actual = write(client, state, lab, key, "Tasks", {"Status": status}, identity=TASK)
        if lose_ack: raise TimeoutError("Controlled lost-ack simulation after verified Zoho write")
        return str(actual["id"])
    def observe():
        row = fresh(client, lab, baseline, "Tasks", TASK)
        return TASK if row["ownership"] == "TEST_ONLY" and row["Status"] == status else None
    result = dispatch(action, ownership="TEST_ONLY", policy=POLICY, journal=journal,
                      fresh=lambda: fresh(client, lab, baseline, "Tasks", TASK),
                      execute=execute, reconcile=observe)
    if lose_ack and result["state"] == "reconcile":
        result = reconcile_ambiguous(action, journal, observe)
    return action, result


def prove_task(client, lab, baseline, state, journal):
    protected_id = baseline["modules"]["Tasks"]["ids"][0]
    protected = Action("crm.task.update", "Tasks", protected_id,
                       "phase12:protected-task-shadow-v1", {"Status": "In Progress"})
    blocked = dispatch(protected, ownership="PROTECTED", policy=POLICY, journal=journal,
                       fresh=lambda: (_ for _ in ()).throw(AssertionError("protected provider transport")),
                       execute=lambda: (_ for _ in ()).throw(AssertionError("protected write")),
                       reconcile=lambda: None)
    if blocked["state"] != "denied": raise ValueError("Protected action not denied")
    before = fresh(client, lab, baseline, "Tasks", TASK)
    if before["Status"] != "Not Started":
        raise ValueError("Task scenario changed; reconcile rather than repeat")
    auto_action, auto = status_update(client, lab, baseline, state, journal,
                                     status="In Progress", key="phase12:test-task-progress-v1")
    if auto["state"] != "succeeded": raise ValueError("Auto Task update not verified")
    # A proposal is based on the current provider version, then another action
    # changes the exact same Test Lab record before that proposal can execute.
    snapshot = fresh(client, lab, baseline, "Tasks", TASK)
    stale_action = Action("crm.task.update", "Tasks", TASK,
        "phase12:stale-task-proposal-v1", {"Status": "Deferred"},
        expected_version=snapshot["Modified_Time"], expected_state={"Status": "In Progress"})
    ambiguous_action, ambiguous = status_update(client, lab, baseline, state, journal,
        status="Completed", key="phase12:test-task-lost-ack-v1", lose_ack=True)
    if ambiguous["state"] != "succeeded": raise ValueError("Lost-ack reconciliation unavailable")
    stale = dispatch(stale_action, ownership="TEST_ONLY", policy=POLICY, journal=journal,
        fresh=lambda: fresh(client, lab, baseline, "Tasks", TASK),
        execute=lambda: (_ for _ in ()).throw(AssertionError("stale write")),
        reconcile=lambda: None)
    if stale["state"] != "stale": raise ValueError("Race condition not stopped")
    replay = dispatch(auto_action, ownership="TEST_ONLY", policy=POLICY, journal=journal,
        fresh=lambda: (_ for _ in ()).throw(AssertionError("replay read")),
        execute=lambda: (_ for _ in ()).throw(AssertionError("replay write")),
        reconcile=lambda: None)
    if replay["state"] != "succeeded": raise ValueError("Replay not idempotent")
    return {"task": TASK, "protected_shadow": blocked["state"],
            "auto": auto["state"], "lost_ack": ambiguous["state"],
            "stale": stale["state"], "replay": replay["state"],
            "final_provider_status": read(client, "Tasks", TASK)["Status"],
            "action_ids": [auto_action.action_id, ambiguous_action.action_id, stale_action.action_id]}


def prove_deal(client, lab, baseline, state, journal):
    key = "phase12:accepted-deal-v1"
    existing = state["operations"].get(key)
    if existing and existing.get("state") != "verified":
        raise ValueError("Deal create was attempted; read-only reconciliation required")
    if existing:
        deal_id = str(existing["id"])
    else:
        for module, identity in (("Accounts", ACCOUNT), ("Contacts", CONTACT)):
            owned(lab, module, read(client, module, identity))
        row = {"Deal_Name": "OPTIBRAIN TEST — PHASE 12 — Camera installation autonomy",
               "Description": "OPTIBRAIN TEST — PHASE 12\nSynthetic accepted camera and cabling project. No real work or revenue.",
               "Account_Name": {"id": ACCOUNT}, "Contact_Name": {"id": CONTACT},
               "Stage": "Contracts Signed", "Service_Types": "Cameras; Structured Cabling",
               "First_Source": "Phase 12 Test Lab", "Ingestion_Source": "manual / CRM",
               "First_Site": "Montreal warehouse", "OptiBrain_Test": True, "Amount": 0}
        deal_id = str(write(client, state, lab, key, "Deals", row)["id"])
    before = fresh(client, lab, baseline, "Deals", deal_id)
    if before["ownership"] != "TEST_ONLY" or before["Stage"] != "Contracts Signed":
        raise ValueError("Accepted Test Deal not ready")
    action = Action("crm.project.onboard", "Deals", deal_id,
                    f"phase12:project-onboard:{deal_id}:v1", {"service_scope": before["Service_Types"]},
                    expected_version=before["Modified_Time"],
                    expected_state={"Stage": "Contracts Signed", "Service_Types": before["Service_Types"]})
    def observe():
        from workflow.automation.operations import stable_id
        project_id = stable_id("Deals", deal_id)
        project = state["projects"].get(project_id)
        if not project or len(project.get("work_orders", [])) != 1 or len(project.get("services", [])) != 1:
            return None
        service = owned(lab, "Services", read(client, "Services", project["services"][0]))
        work = owned(lab, "Installations", read(client, "Installations", project["work_orders"][0]))
        if ((service.get("Linked_Deal") or {}).get("id") != deal_id or
            (work.get("Linked_Service") or {}).get("id") != service["id"]):
            return None
        return project_id
    result = dispatch(action, ownership="TEST_ONLY", policy=POLICY, journal=journal,
        fresh=lambda: fresh(client, lab, baseline, "Deals", deal_id),
        execute=lambda: onboard(client, state, lab, deal_id)["id"], reconcile=observe)
    if result["state"] != "succeeded": raise ValueError("Test project onboarding not verified")
    replay = dispatch(action, ownership="TEST_ONLY", policy=POLICY, journal=journal,
        fresh=lambda: (_ for _ in ()).throw(AssertionError("onboarding replay read")),
        execute=lambda: (_ for _ in ()).throw(AssertionError("onboarding replay write")),
        reconcile=lambda: None)
    if replay["state"] != "succeeded": raise ValueError("Onboarding replay was not idempotent")
    project = state["projects"][result["provider_id"]]
    return {"deal": deal_id, "project": result["provider_id"],
            "work_orders": project["work_orders"], "services": project["services"],
            "folder": project["folder"]["path"], "state": result["state"],
            "replay_duplicate_projects": 0, "replay_duplicate_work_orders": 0,
            "action_id": action.action_id}


def prove_policy(client, lab, baseline, journal):
    old = journal.get(Action("email.send", "Tasks", TASK,
        "phase12:test-send-approval-v1", {"purpose": "controlled draft approval boundary", "send": False}).action_id)
    if old and old["state"] == "approval_required":
        journal.transition(old["action_id"], from_states=("approval_required",), to="stale",
                           detail={"reason": "superseded_by_exact_controlled_identity_proposal"})
    lead = fresh(client, lab, baseline, "Leads", CONTROLLED_LEAD)
    if lead["ownership"] != "TEST_ONLY" or lead.get("Email") != "hckyan97+obp8wait@gmail.com":
        raise ValueError("Exact operator-controlled Test Lead changed")
    send = Action("email.send", "Leads", CONTROLLED_LEAD, "phase12:test-send-approval-v2",
        {"purpose": "controlled Phase 12 approval proof; no execution endpoint",
         "recipient": "hckyan97+obp8wait@gmail.com", "subject": "OPTIBRAIN TEST ONLY — Phase 12",
         "body_hash": digest("OPTIBRAIN TEST ONLY: approval-bound outreach fixture."),
         "from": "yboucher@opticable.ca"},
         expected_version=lead["Modified_Time"], expected_state={"Email": lead["Email"]})
    proposed = journal.prepare(send, decide(send, lead["ownership"], POLICY))
    books = Action("books.write", "Books", "", "phase12:books-denial-v1", {"operation": "invoice.create"})
    denied = journal.prepare(books, decide(books, "REAL", POLICY))
    kill = Action("crm.task.update", "Tasks", TASK, "phase12:kill-switch-v1", {"Status": "Deferred"})
    deferred = journal.prepare(kill, decide(kill, "TEST_ONLY", Policy()))
    observation = Action("crm.read", "Tasks", TASK, "phase12:read-with-kill-off-v1", {})
    observed = dispatch(observation, ownership="TEST_ONLY", policy=Policy(), journal=journal,
        fresh=lambda: fresh(client, lab, baseline, "Tasks", TASK),
        execute=lambda: (_ for _ in ()).throw(AssertionError("read called write")),
        reconcile=lambda: None)
    protected_deal = baseline["modules"]["Deals"]["ids"][0]
    shadow = Action("crm.project.onboard", "Deals", protected_deal,
        "phase12:protected-deal-shadow-v1", {"mode": "shadow"})
    blocked = journal.prepare(shadow, decide(shadow, "PROTECTED", POLICY))
    if (proposed["state"], denied["state"], deferred["state"], observed["state"], blocked["state"]) != (
        "approval_required", "denied", "deferred", "succeeded", "denied"):
        raise ValueError("Policy scenario result unexpected")
    return {"approval_required": proposed["action_id"], "books_denied": denied["action_id"],
            "kill_switch": deferred["state"], "read_with_kill_off": observed["state"],
            "protected_deal": blocked["state"], "shadow_records": 2}


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in {"task", "deal", "policy", "summary"}:
        raise SystemExit("root required: test_lab_autonomy.py task|deal|policy|summary")
    client, lab, baseline, state, journal = context()
    evidence = json.loads(EVIDENCE.read_text()) if EVIDENCE.exists() else {
        "mission": "phase12-manual-test-lab-v1", "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "protected_baseline": sum(len(x["ids"]) for x in baseline["modules"].values()),
        "real_mutations": 0, "real_sends": 0, "books_writes": 0}
    command = sys.argv[1]
    if command == "task": evidence["task"] = prove_task(client, lab, baseline, state, journal)
    elif command == "deal": evidence["deal"] = prove_deal(client, lab, baseline, state, journal)
    elif command == "policy": evidence["policy"] = prove_policy(client, lab, baseline, journal)
    evidence["journal_summary"] = journal.view()["summary"]
    save_evidence(evidence)
    print(json.dumps({"command": command, "evidence": evidence.get(command),
                      "summary": evidence["journal_summary"]}, indent=2))


if __name__ == "__main__": main()
