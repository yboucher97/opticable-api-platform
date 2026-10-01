#!/usr/bin/env python3
"""One-shot, guarded Phase 11 Deal → project Test Lab proof.

No timer calls this script. Every CRM write uses the existing journal and protected
record firewall. An ambiguous acknowledgement stops for provider reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from test_lab_operations import (LAB, MARKER, STATE, document, event, folders, link,
    listing, load, owned, provider, read, save, stable_id, write)

TORONTO = ZoneInfo("America/Toronto")
ACCOUNT = "5062683000007928001"  # Existing owned Phase 9 Test Lab relationship.
CONTACT = "5062683000007929001"
SOURCE_SITE = "5062683000007933004"
KEY = "closure:deal"


def ref(row: dict, field: str) -> str:
    value = row.get(field)
    return str(value.get("id") or "") if isinstance(value, dict) else ""


def aware(value: str) -> datetime:
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.utcoffset() is None:
        raise ValueError("A timezone-aware instant is required")
    local = moment.astimezone(TORONTO)
    if moment.isoformat()[-6:] != local.isoformat()[-6:]:
        raise ValueError("Schedule offset must match America/Toronto on that date")
    return moment


def overlaps(start: datetime, minutes: int, other: datetime, other_minutes: int) -> bool:
    return start < other + timedelta(minutes=other_minutes) and other < start + timedelta(minutes=minutes)


def create_deal(client, state: dict, lab: dict) -> str:
    for module, identity in (("Accounts", ACCOUNT), ("Contacts", CONTACT),
                             ("Service_Locations", SOURCE_SITE)):
        owned(lab, module, read(client, module, identity))
    if KEY in state["operations"]:
        item = state["operations"][KEY]
        if item.get("state") != "verified" or not item.get("id"):
            raise ValueError("Deal create outcome needs read-only reconciliation")
        deal = owned(lab, "Deals", read(client, "Deals", item["id"]))
        return str(deal["id"])
    row = {"Deal_Name": f"{MARKER} — Loading dock cameras and cabling closure",
           "Description": f"{MARKER}\nSynthetic accepted installation. Existing owned warehouse customer/site. No real field work or revenue.",
           "Account_Name": {"id": ACCOUNT}, "Contact_Name": {"id": CONTACT},
           "Stage": "Contracts Signed", "Service_Types": "Cameras; Structured Cabling",
           "First_Source": "Phase 11 Test Lab", "Ingestion_Source": "manual / CRM",
           "First_Site": "Montreal warehouse", "OptiBrain_Test": True, "Amount": 0}
    result = write(client, state, lab, KEY, "Deals", row)
    return str(result["id"])


def resolve_deal(client, lab: dict, deal_id: str, *, new: bool,
                 existing_site: str | None = None) -> tuple[dict, str, str, str]:
    deal = owned(lab, "Deals", read(client, "Deals", deal_id))
    if (new and deal.get("Stage") != "Contracts Signed") or (not new and deal.get("Stage") not in {"Contracts Signed", "Closed Won"}):
        raise ValueError("Deal is not in the accepted onboarding stage")
    if not str(deal.get("Service_Types") or "").strip():
        raise ValueError("Accepted Deal needs an actual service scope")
    account_id, contact_id = ref(deal, "Account_Name"), ref(deal, "Contact_Name")
    if not account_id or not contact_id:
        raise ValueError("Accepted Deal needs Account and Contact")
    account = owned(lab, "Accounts", read(client, "Accounts", account_id))
    contact = owned(lab, "Contacts", read(client, "Contacts", contact_id))
    if ref(contact, "Account_Name") != account_id:
        raise ValueError("Contact does not belong to the Deal Account")
    if existing_site:
        site_id = existing_site
    else:
        sites = [row for row in listing(client, "Service_Locations",
                 "id,Name,Linked_Account,Primary_Contact,OptiBrain_Test")
                 if ref(row, "Linked_Account") == account_id
                 and ref(row, "Primary_Contact") == contact_id]
        if len(sites) != 1:
            raise ValueError("Site resolution is absent or ambiguous")
        site_id = str(sites[0]["id"])
    site = owned(lab, "Service_Locations", read(client, "Service_Locations", site_id))
    if ref(site, "Linked_Account") != account_id or ref(site, "Primary_Contact") != contact_id:
        raise ValueError("Site relationship changed")
    return deal, account_id, contact_id, site_id


def reconcile(client, state: dict, lab: dict, project: dict) -> int:
    """Observe meaningful provider state, including edits made outside this command."""
    before = len(project["events"])
    deal = owned(lab, "Deals", read(client, "Deals", project["provider"]["Deals"]))
    service = owned(lab, "Services", read(client, "Services", project["services"][0]))
    work_id = project["work_orders"][0]
    work = owned(lab, "Installations", read(client, "Installations", work_id))
    if (ref(service, "Linked_Deal") != deal["id"]
            or ref(service, "Linked_Service_Location") != project["provider"]["Service_Locations"]
            or ref(work, "Linked_Service") != service["id"]):
        raise ValueError("Provider operational relationship drifted")
    status = str(work.get("Installation_Status") or "")
    schedule = work.get("Scheduled_Date")
    schedule_instant = aware(schedule).astimezone(timezone.utc).isoformat() if schedule else None
    assignment = str(work.get("Assigned_To") or "")
    current = {"work_status": status, "scheduled_utc": schedule_instant,
               "assignment": assignment, "service_stage": service.get("Service_Stage"),
               "installed_on": service.get("OptiBrain_Installed_On"), "deal_stage": deal.get("Stage")}
    previous = project.get("observed") or {}
    wid = stable_id("Installations", work_id)
    if status == "Scheduled" and previous.get("work_status") != "Scheduled":
        event(state, project, "WORK_ORDER_SCHEDULED", wid, schedule_instant or "unscheduled")
    if schedule_instant != previous.get("scheduled_utc") and previous.get("scheduled_utc"):
        version = sha256(json.dumps([schedule_instant, assignment]).encode()).hexdigest()
        event(state, project, "WORK_ORDER_SCHEDULE_CHANGED", wid, version)
    if previous and assignment != previous.get("assignment"):
        event(state, project, "WORK_ORDER_ASSIGNMENT_CHANGED", wid, assignment)
    if status == "In Progress":
        event(state, project, "WORK_ORDER_STARTED", wid, "started")
    if status == "Completed":
        event(state, project, "WORK_ORDER_COMPLETED", wid, "completed")
    if service.get("Service_Stage") == "Active" and service.get("OptiBrain_Installed_On") and status == "Completed":
        event(state, project, "SERVICE_INSTALLED", stable_id("Services", str(service["id"])),
              str(service["OptiBrain_Installed_On"]))
    if status == "Completed" and service.get("Service_Stage") == "Active" and deal.get("Stage") == "Closed Won":
        project["status"] = "COMPLETED"
        event(state, project, "PROJECT_COMPLETED", project["id"], "completed")
    else:
        project["status"] = {"Requested": "READY TO SCHEDULE", "Scheduled": "SCHEDULED",
                             "In Progress": "IN PROGRESS"}.get(status, "PLANNING")
    project["scheduled"] = schedule
    project["assignment"] = assignment or None
    project["observed"] = current
    save(state)
    return len(project["events"]) - before


def onboard(client, state: dict, lab: dict, deal_id: str) -> dict:
    project_id = stable_id("Deals", deal_id)
    project = state["projects"].get(project_id)
    deal, account_id, contact_id, site_id = resolve_deal(
        client, lab, deal_id, new=project is None,
        existing_site=(project or {}).get("provider", {}).get("Service_Locations"))
    if project is None:
        project = {"id": project_id, "status": "PLANNING", "provider": {
            "Accounts": account_id, "Contacts": contact_id,
            "Service_Locations": site_id, "Deals": deal_id},
            "services": [], "work_orders": [], "tickets": [], "ticket_work_orders": {},
            "tasks": [], "documents": [], "events": [], "scheduled": None,
            "scope": deal["Service_Types"], "test_only": True,
            "onboarded_date": datetime.now(TORONTO).date().isoformat()}
        state["projects"][project_id] = project
        save(state)
    elif project["provider"] != {"Accounts": account_id, "Contacts": contact_id,
                                  "Service_Locations": site_id, "Deals": deal_id}:
        raise ValueError("Onboarding relationship changed")
    customer = link(state, "Accounts", account_id)
    link(state, "Contacts", contact_id, customer=customer)
    site = link(state, "Service_Locations", site_id, customer=customer)
    link(state, "Deals", deal_id, customer=customer, site=site, project=project_id)
    folders(state, project)
    date = project["onboarded_date"]
    document(state, project, f"{date}_{project_id}_QuoteScope.txt",
             (f"OPTIBRAIN TEST ONLY\nSource Deal {deal_id}\nScope: {deal['Service_Types']}\n"
              "Synthetic loading-dock camera and cabling project; no real quote or work.\n").encode())
    event(state, project, "DEAL_ACCEPTED", project_id, str(deal["Created_Time"]))
    if not project["services"]:
        service = write(client, state, lab, f"onboard:{deal_id}:service", "Services", {
            "Name": f"{MARKER} — Loading dock camera system {project_id}",
            "Linked_Service_Location": {"id": site_id}, "Linked_Deal": {"id": deal_id},
            "Service_Type": "Camera Installation", "Service_Stage": "Ready for Scheduling",
            "Contract_Type": "Installation", "OptiBrain_Test": True})
        project["services"].append(str(service["id"])); save(state)
    service_id = project["services"][0]
    owned(lab, "Services", read(client, "Services", service_id))
    link(state, "Services", service_id, customer=customer, site=site, project=project_id)
    if not project["work_orders"]:
        work = write(client, state, lab, f"onboard:{deal_id}:work", "Installations", {
            "Name": f"{MARKER} — Loading dock installation {project_id}",
            "Linked_Service": {"id": service_id}, "Installation_Type": "Initial Installation",
            "Installation_Status": "Requested",
            "Instructions_Notes": "OPTIBRAIN TEST ONLY — install loading-dock cameras and structured cabling; confirm access and mounting plan."})
        project["work_orders"].append(str(work["id"])); save(state)
    work_id = project["work_orders"][0]
    owned(lab, "Installations", read(client, "Installations", work_id))
    wid = link(state, "Installations", work_id, customer=customer, site=site, project=project_id)
    event(state, project, "PROJECT_CREATED", project_id, str(deal["Created_Time"]))
    event(state, project, "WORK_ORDER_CREATED", wid, str(read(client, "Installations", work_id)["Created_Time"]))
    reconcile(client, state, lab, project)
    return project


def schedule(client, state: dict, lab: dict, project: dict, when: str,
             assignment: str, duration_minutes: int = 180,
             now: datetime | None = None) -> None:
    start = aware(when)
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None or start <= now:
        raise ValueError("Field schedule must be a future aware instant")
    if not assignment.startswith("OPTIBRAIN TEST — ") or not 30 <= duration_minutes <= 480:
        raise ValueError("Assignment or duration is outside bounded Test Lab scheduling")
    work_id = project["work_orders"][0]
    work = owned(lab, "Installations", read(client, "Installations", work_id))
    if work.get("Installation_Status") != "Requested":
        raise ValueError("Work Order is not ready to schedule")
    for other in state["projects"].values():
        for other_id in other.get("work_orders", []):
            if other_id == work_id: continue
            row = owned(lab, "Installations", read(client, "Installations", other_id))
            if (row.get("Installation_Status") in {"Scheduled", "In Progress"}
                    and row.get("Assigned_To") == assignment and row.get("Scheduled_Date")
                    and overlaps(start, duration_minutes, aware(row["Scheduled_Date"]),
                                 int(other.get("duration_minutes") or 180))):
                raise ValueError("Assigned Test Lab slot conflicts with another Work Order")
    write(client, state, lab, f"onboard:{project['provider']['Deals']}:scheduled",
          "Installations", {"Installation_Status": "Scheduled", "Scheduled_Date": when,
                            "Assigned_To": assignment}, identity=work_id)
    project["duration_minutes"] = duration_minutes; save(state)
    reconcile(client, state, lab, project)


def transition(client, state: dict, lab: dict, project: dict, step: str) -> None:
    deal_id = project["provider"]["Deals"]
    work_id, service_id = project["work_orders"][0], project["services"][0]
    work = owned(lab, "Installations", read(client, "Installations", work_id))
    if step == "start":
        if work.get("Installation_Status") != "Scheduled": raise ValueError("Work must be scheduled")
        write(client, state, lab, f"onboard:{deal_id}:started", "Installations",
              {"Installation_Status": "In Progress"}, identity=work_id)
    elif step == "complete":
        if work.get("Installation_Status") != "In Progress": raise ValueError("Work must be in progress")
        write(client, state, lab, f"onboard:{deal_id}:completed", "Installations", {
            "Installation_Status": "Completed", "Completion_Notes":
            "OPTIBRAIN TEST ONLY — simulated camera and cabling installation and verification; no physical work."}, identity=work_id)
        reconcile(client, state, lab, project)
        today = datetime.now(TORONTO).date().isoformat()
        write(client, state, lab, f"onboard:{deal_id}:service-active", "Services",
              {"Service_Stage": "Active", "OptiBrain_Installed_On": today}, identity=service_id)
        write(client, state, lab, f"onboard:{deal_id}:deal-closed", "Deals",
              {"Stage": "Closed Won"}, identity=deal_id)
        document(state, project, f"{today}_{project['id']}_ServiceReport.txt",
                 b"OPTIBRAIN TEST ONLY\nSimulated loading-dock camera and cabling completion. No physical work.\n")
    else: raise ValueError("Unknown Work Order transition")
    reconcile(client, state, lab, project)


def main() -> None:
    if os.geteuid() != 0 or len(sys.argv) < 2:
        raise SystemExit("root required; usage: onboard_test_deal.py create|onboard DEAL|schedule DEAL TIME|start DEAL|complete DEAL|reconcile DEAL")
    action = sys.argv[1]
    if action not in {"create", "onboard", "schedule", "start", "complete", "reconcile"}:
        raise ValueError("Unknown one-shot action")
    client = provider(); state = load(STATE); lab = load(LAB)
    if action == "create":
        if len(sys.argv) != 2: raise ValueError("create takes no ID")
        print("TEST Deal", create_deal(client, state, lab)); return
    if len(sys.argv) < 3 or not sys.argv[2].isdigit(): raise ValueError("Exact Deal ID required")
    deal_id = sys.argv[2]
    if action == "onboard":
        project = onboard(client, state, lab, deal_id)
    else:
        project = state["projects"].get(stable_id("Deals", deal_id))
        if not project or project["provider"]["Deals"] != deal_id: raise ValueError("Deal is not onboarded")
        if action == "schedule":
            if len(sys.argv) != 4: raise ValueError("Schedule requires a Montreal aware ISO time")
            schedule(client, state, lab, project, sys.argv[3], "OPTIBRAIN TEST — Internal lab crew")
        elif action in {"start", "complete"}: transition(client, state, lab, project, action)
        elif action == "reconcile": print("new events", reconcile(client, state, lab, project))
    print("project", project["id"], "status", project["status"],
          "services", project["services"], "work_orders", project["work_orders"],
          "events", len(project["events"]))


if __name__ == "__main__": main()
