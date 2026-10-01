"""Read-only Phase 11 operations projection over owned CRM records and a small crosswalk.

The crosswalk is written only by the manually invoked Test Lab proof. Public API
routes never create provider records, folders, or events.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
PROJECTION = Path("/etc/optibrain/phase11-operations.json")
LAB = Path("/etc/optibrain/phase8-test-lab-registry.json")
MARKER = "OPTIBRAIN TEST — PHASE "
PREFIXES = {"Accounts": "OB-C", "Contacts": "OB-P", "Service_Locations": "OB-S",
            "Deals": "OB-J", "Installations": "OB-WO", "Cases": "OB-T", "Services": "OB-SV",
            "Tasks": "OB-TK"}


def stable_id(module: str, identity: str) -> str:
    """Mint once, then persist the provider-independent value in the crosswalk."""
    if module not in PREFIXES or not str(identity).isdigit():
        raise ValueError("Unknown operational object")
    suffix = sha256(f"optibrain-operations-v1\0{module}\0{identity}".encode()).hexdigest()[:12].upper()
    return f"{PREFIXES[module]}-{suffix}"


def event_id(kind: str, internal_id: str, evidence_version: str) -> str:
    if not kind or not internal_id or not evidence_version:
        raise ValueError("Operational event requires evidence")
    return "OB-E-" + sha256(f"{kind}\0{internal_id}\0{evidence_version}".encode()).hexdigest()[:20].upper()


def local_time(value: str | None) -> str | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("Operational timestamps must be timezone-aware")
    return dt.astimezone(TORONTO).strftime("%b %-d, %Y %-I:%M %p %Z")


def classify_document(name: str) -> str:
    name = Path(name).name.casefold()
    if name.endswith((".jpg", ".jpeg", ".png", ".heic")):
        return "PHOTO"
    for token, kind in (("quote", "QUOTE"), ("contract", "CONTRACT"),
                        ("plan", "PLAN"), ("workorder", "WORK ORDER"),
                        ("service", "SERVICE REPORT"), ("equipment", "EQUIPMENT"),
                        ("invoice", "INVOICE")):
        if token in name:
            return kind
    return "OTHER"


def _one(client, module: str, identity: str) -> dict:
    response = client.request("zohoapis", "GET", f"/crm/v8/{module}/{identity}")
    rows = (response.get("data") or {}).get("data") or []
    if response.get("ok") is not True or len(rows) != 1 or str(rows[0].get("id")) != identity:
        raise ValueError("Exact operational provider read failed")
    return rows[0]


def _ref(row: dict, field: str) -> str:
    value = row.get(field)
    return str(value.get("id") or "") if isinstance(value, dict) else ""


def _owned(row: dict, module: str, registry: dict) -> bool:
    identity = str(row.get("id") or "")
    if identity not in set((registry.get("records") or {}).get(module) or []):
        return False
    if module in {"Installations", "Services", "Service_Locations"}:
        return str(row.get("Name") or "").startswith(MARKER) and (
            module == "Installations" or row.get("OptiBrain_Test") is True)
    if module == "Cases":
        return str(row.get("Subject") or "").startswith(MARKER) and str(row.get("Description") or "").startswith(MARKER)
    if module == "Tasks":
        return str(row.get("Subject") or "").startswith(MARKER) and str(row.get("Description") or "").startswith(MARKER)
    return row.get("OptiBrain_Test") is True


def work_action(status: str, scheduled: str | None) -> tuple[str, str]:
    if status == "Requested":
        return "Schedule work", "Work is requested and has no confirmed field slot."
    if status == "Scheduled":
        return "Confirm site access", "A field slot is scheduled; confirm access and materials."
    if status == "In Progress":
        return "Complete work and record result", "Installation is in progress."
    if status == "Completed":
        return "No action", "Work completion is recorded."
    if status in {"Failed", "Revisit Required"}:
        return "Review field issue", "The visit did not complete successfully."
    return "Review work state", "CRM work status needs an operator review."


def ticket_action(status: str, linked_orders: list[dict]) -> tuple[str, str]:
    if status == "Closed":
        return "No action", "Ticket resolution is recorded."
    pending = [order for order in linked_orders if order["status"] != "Completed"]
    if pending:
        return pending[0]["action"], "Open ticket has linked field work: " + pending[0]["reason"]
    if linked_orders:
        return "Resolve ticket", "Related field work is completed; review the resolution."
    return "Assess service issue", "Open support issue needs triage or field work."


def build_operations(client, *, scope: str, projection_path: Path = PROJECTION,
                     lab_path: Path = LAB, now: datetime | None = None) -> dict:
    if scope not in {"live", "lab"}:
        raise ValueError("Unknown operations scope")
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("Aware clock required")
    if scope == "live":
        return {"scope": scope, "read_at": local_time(now.isoformat()), "projects": [],
                "summary": {k: 0 for k in ("needs_attention", "ready_to_schedule", "scheduled",
                    "in_progress", "blocked", "open_tickets", "due_work_orders", "recently_completed")},
                "note": "No verified real operational project is registered; protected CRM records remain read-only."}
    projection = json.loads(projection_path.read_text())
    registry = json.loads(lab_path.read_text())
    if (projection.get("schema") != 1 or not isinstance(projection.get("projects"), dict)
            or not isinstance(projection.get("crosswalk"), dict)):
        raise ValueError("Operations projection invalid")
    crosswalk = projection["crosswalk"]
    def internal(module: str, provider_id: str) -> str:
        matches = [key for key, value in crosswalk.items()
                   if value.get("module") == module and value.get("provider_id") == provider_id
                   and value.get("internal_id") == key and value.get("test_only") is True
                   and re.fullmatch(re.escape(PREFIXES[module]) + r"-[0-9A-F]{12}", key)]
        if len(matches) != 1:
            raise ValueError("Operational provider crosswalk missing or ambiguous")
        created = datetime.fromisoformat(str(crosswalk[matches[0]].get("created_at_utc") or ""))
        if created.utcoffset() is None:
            raise ValueError("Operational crosswalk created time is ambiguous")
        return matches[0]
    projects = []
    for project_id, record in projection["projects"].items():
        ids = record["provider"]
        if internal("Deals", ids["Deals"]) != project_id:
            raise ValueError("Project identity changed")
        rows = {module: _one(client, module, ids[module]) for module in
                ("Accounts", "Contacts", "Service_Locations", "Deals")}
        if not all(_owned(row, module, registry) for module, row in rows.items()):
            raise ValueError("Operational project escaped Test Lab")
        if (_ref(rows["Contacts"], "Account_Name") != ids["Accounts"]
                or _ref(rows["Service_Locations"], "Linked_Account") != ids["Accounts"]
                or _ref(rows["Service_Locations"], "Primary_Contact") != ids["Contacts"]
                or _ref(rows["Deals"], "Account_Name") != ids["Accounts"]
                or _ref(rows["Deals"], "Contact_Name") != ids["Contacts"]):
            raise ValueError("Operational customer/site relationship changed")
        source_lead_id = record.get("source_lead_id")
        if source_lead_id:
            lead = _one(client, "Leads", source_lead_id)
            if (not _owned(lead, "Leads", registry)
                    or source_lead_id not in str(rows["Deals"].get("Description") or "")):
                raise ValueError("Source Lead relationship changed")
        services = []
        for service_id in record.get("services", []):
            row = _one(client, "Services", service_id)
            if not _owned(row, "Services", registry) or _ref(row, "Linked_Service_Location") != ids["Service_Locations"] or _ref(row, "Linked_Deal") != ids["Deals"]:
                raise ValueError("Installed Service relationship changed")
            services.append({"id": internal("Services", service_id), "provider_id": service_id,
                             "name": row.get("Name"), "stage": row.get("Service_Stage"),
                             "installed_on": row.get("OptiBrain_Installed_On")})
        service_ids = {x["provider_id"] for x in services}
        orders = []
        for installation_id in record.get("work_orders", []):
            row = _one(client, "Installations", installation_id)
            if not _owned(row, "Installations", registry) or _ref(row, "Linked_Service") not in service_ids:
                raise ValueError("Work Order relationship changed")
            status = str(row.get("Installation_Status") or "Requested")
            action, why = work_action(status, row.get("Scheduled_Date"))
            orders.append({"id": internal("Installations", installation_id), "provider_id": installation_id,
                           "name": row.get("Name"), "status": status,
                           "scheduled_at": row.get("Scheduled_Date"),
                           "scheduled": local_time(row.get("Scheduled_Date")),
                           "assignment": row.get("Assigned_To"),
                           "duration_minutes": record.get("duration_minutes") if installation_id == record.get("work_orders", [None])[0] else None,
                           "service_id": internal("Services", _ref(row, "Linked_Service")),
                           "action": action, "reason": why, "result": row.get("Completion_Notes")})
        tickets = []
        for case_id in record.get("tickets", []):
            row = _one(client, "Cases", case_id)
            if not _owned(row, "Cases", registry) or _ref(row, "Account_Name") != ids["Accounts"] or _ref(row, "Deal_Name") != ids["Deals"] or _ref(row, "Related_To") != ids["Contacts"]:
                raise ValueError("Ticket relationship changed")
            status = str(row.get("Status") or "New")
            linked = [x for x in orders if x["provider_id"] in record.get("ticket_work_orders", {}).get(case_id, [])]
            action, why = ticket_action(status, linked)
            tickets.append({"id": internal("Cases", case_id), "provider_id": case_id,
                            "subject": row.get("Subject"), "status": status,
                            "action": action, "reason": why, "solution": row.get("Solution")})
        tasks = []
        for task_id in record.get("tasks", []):
            row = _one(client, "Tasks", task_id)
            if not _owned(row, "Tasks", registry) or _ref(row, "What_Id") != ids["Deals"] or row.get("$se_module") != "Deals":
                raise ValueError("Operational Task route changed")
            tasks.append({"id": internal("Tasks", task_id), "provider_id": task_id,
                          "subject": row.get("Subject"), "status": row.get("Status"),
                          "due_on": row.get("Due_Date"), "category": record.get("task_categories", {}).get(task_id)})
        pending = [x for x in orders if x["status"] != "Completed" and x["action"] != "No action"]
        open_tickets = [x for x in tickets if x["status"] != "Closed"]
        if open_tickets:
            primary = open_tickets[0]; action = primary["action"]; why = primary["reason"]
        elif pending:
            primary = pending[0]; action = primary["action"]; why = primary["reason"]
        elif any(t["status"] not in {"Completed", "Deferred"} for t in tasks):
            action, why = "Complete project document task", "An owned closeout task is still open."
        elif record.get("status") != "COMPLETED":
            action, why = "Review project closeout", "All recorded work is complete; confirm project completion."
        else:
            action, why = "No action", "Project and work orders are complete."
        projects.append({"id": project_id, "customer_id": internal("Accounts", ids["Accounts"]),
                         "contact_id": internal("Contacts", ids["Contacts"]),
                         "site_id": internal("Service_Locations", ids["Service_Locations"]),
                         "provider_ids": ids,
                         "account": rows["Accounts"].get("Account_Name"),
                         "contact": rows["Contacts"].get("Full_Name"),
                         "site": rows["Service_Locations"].get("Name"),
                         "deal": rows["Deals"].get("Deal_Name"), "deal_id": ids["Deals"],
                         "source_lead_id": source_lead_id,
                         "source": rows["Deals"].get("First_Source"),
                         "scope": record.get("scope") or rows["Deals"].get("Service_Types"),
                         "status": record["status"], "scheduled": local_time(record.get("scheduled")),
                         "action": action, "reason": why, "work_orders": orders, "tickets": tickets,
                         "services": services, "tasks": tasks, "documents": record.get("documents", []),
                         "folder": record.get("folder"), "events": record.get("events", []),
                         "test_only": True})
    projects.sort(key=lambda x: (x["action"] == "No action", x["id"]))
    work = [w for p in projects for w in p["work_orders"]]
    tickets = [t for p in projects for t in p["tickets"]]
    summary = {"needs_attention": sum(p["action"] != "No action" for p in projects),
               "ready_to_schedule": sum(w["status"] == "Requested" for w in work),
               "scheduled": sum(w["status"] == "Scheduled" for w in work),
               "in_progress": sum(w["status"] == "In Progress" for w in work),
               "blocked": sum(w["status"] in {"Failed", "Revisit Required"} for w in work),
               "open_tickets": sum(t["status"] != "Closed" for t in tickets),
               "due_work_orders": sum(bool(w["status"] not in {"Completed", "Cancelled"} and
                   w["scheduled_at"] and
                   datetime.fromisoformat(w["scheduled_at"].replace("Z", "+00:00")) < now)
                   for p in projects for w in p["work_orders"]),
               "recently_completed": sum(p["status"] == "COMPLETED" for p in projects)}
    return {"scope": scope, "read_at": local_time(now.isoformat()), "projects": projects,
            "summary": summary, "note": "Synthetic TEST ONLY; excluded from live operations and revenue."}


def render_operations(view: dict) -> str:
    h = lambda value: escape(str(value if value is not None else "—"), quote=True)
    blocks = []
    for p in view["projects"]:
        blocks.append(f"<article><h2><a href='/v1/operator/phase11/project/{h(p['id'])}'>{h(p['id'])}</a> · {h(p['account'])}</h2>"
                      f"<p>{h(p['site'])} · {h(p['status'])} · {h(p['deal'])}</p>"
                      f"<p>Scope: {h(p['scope'])} · Schedule: {h(p['scheduled'])} · Assigned: {h(p['work_orders'][0].get('assignment') if p['work_orders'] else None)}</p>"
                      f"<p><b>Next:</b> {h(p['action'])} — {h(p['reason'])}</p>"
                      f"<small>{len(p['work_orders'])} work orders · {len(p['tickets'])} tickets · "
                      f"{len(p['services'])} services · {len(p['tasks'])} tasks · {len(p['documents'])} documents</small></article>")
    counts = " · ".join(f"{h(k.replace('_',' ').title())}: {h(v)}" for k, v in view["summary"].items())
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain operations</title>"
            "<style>body{font:16px/1.45 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#182536}"
            "article{border:1px solid #ccd;border-radius:.5rem;padding:1rem;margin:1rem 0}</style>"
            f"<h1>Operations · {h(view['scope'].upper())}</h1><p>{h(counts)}</p><p>{h(view['note'])}</p>"
            + "".join(blocks) + f"<small>Fresh CRM read {h(view['read_at'])}</small></html>")


def render_project(project: dict) -> str:
    h = lambda value: escape(str(value if value is not None else "—"), quote=True)
    def section(title, rows, formatter):
        return f"<h2>{h(title)}</h2><ul>" + "".join(f"<li>{formatter(row)}</li>" for row in rows) + "</ul>"
    orders = section("Work orders", project["work_orders"], lambda w:
                     f"{h(w['id'])} (Zoho {h(w['provider_id'])}) · {h(w['status'])} · {h(w['scheduled'])} · {h(w.get('duration_minutes'))} min · assigned {h(w.get('assignment'))} · {h(w['action'])}")
    services = section("Services and installation handoff", project["services"], lambda s:
                       f"{h(s['id'])} (Zoho {h(s['provider_id'])}) · {h(s['name'])} · {h(s['stage'])} · installed {h(s['installed_on'])}")
    tickets = section("Service tickets", project["tickets"], lambda t:
                      f"{h(t['id'])} · {h(t['subject'])} · {h(t['status'])}")
    docs = section("Documents", project["documents"], lambda d:
                   f"{h(d['name'])} · {h(d['category'])} · SHA-256 {h(d['sha256'][:12])}")
    tasks = section("Tasks", project["tasks"], lambda t:
                    f"{h(t['id'])} · {h(t['category'])} · {h(t['subject'])} · {h(t['status'])} · due {h(t['due_on'])}")
    events = section("History", project["events"], lambda e:
                     f"{h(e['kind'])} · {h(local_time(e['at']))} · {h(e['id'])}")
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>OptiBrain project</title>"
            "<style>body{font:16px/1.45 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#182536}</style>"
            f"<h1>{h(project['id'])} · {h(project['account'])}</h1><p>{h(project['site'])} · {h(project['status'])}</p>"
            f"<p>Contact: {h(project['contact'])} · Scope: {h(project['scope'])} · Schedule: {h(project['scheduled'])}</p>"
            f"<p>Canonical customer {h(project['customer_id'])} · contact {h(project['contact_id'])} · site {h(project['site_id'])}</p>"
            f"<p>Zoho Account {h(project['provider_ids']['Accounts'])} · Contact {h(project['provider_ids']['Contacts'])} · Site {h(project['provider_ids']['Service_Locations'])}</p>"
            f"<p>Source opportunity {h(project['deal_id'])} · {h(project['source'])}"
            + (f" · <a href='/v1/operator/phase9/source-trace/{h(project['source_lead_id'])}'>intake/source trace</a>"
               if project.get("source_lead_id") else "") + "</p>"
            f"<p>Next: {h(project['action'])} — {h(project['reason'])}</p>"
            f"<p>Folder: {h((project.get('folder') or {}).get('path'))}</p>"
            + orders + services + tickets + tasks + docs + events + "</html>")
