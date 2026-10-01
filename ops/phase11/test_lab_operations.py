#!/usr/bin/env python3
"""Manual Phase 11 TEST_ONLY provider proof; every write is journaled before transport.

Commands are deliberately one-shot. No timer or autonomous Codex dispatch invokes
this file. An uncertain provider outcome requires read-only reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))
from workflow.automation.operations import stable_id, event_id, classify_document

ROOT = Path("/var/lib/optibrain/phase11/test-lab")
STATE = ROOT / "registry.json"
PROJECTION = Path("/etc/optibrain/phase11-operations.json")
FILES = ROOT / "files"
CASE_BASELINE = Path("/var/lib/optibrain/phase11/cases-protected-baseline.json")
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
LAB_PROJECTION = Path("/etc/optibrain/phase8-test-lab-registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
SERVICE_BASELINE = Path("/var/lib/optibrain/phase10/service-protected-baseline.json")
MARKER = "OPTIBRAIN TEST — PHASE 11"
ACCOUNT = "5062683000007928001"
CONTACT = "5062683000007929001"
DEAL = "5062683000007913007"
SITE = "5062683000007933004"


def atomic(path: Path, value: dict, *, mode=0o600, gid=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush(); os.fsync(handle.fileno())
    if gid is not None: os.chown(tmp, 0, gid)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load(path): return json.loads(path.read_text())


def save(state):
    atomic(STATE, state)
    atomic(PROJECTION, state, mode=0o640, gid=grp.getgrnam("opticable-workflow-api").gr_gid)


def save_lab(lab):
    atomic(LAB, lab)
    atomic(LAB_PROJECTION, lab, mode=0o640, gid=grp.getgrnam("opticable-workflow-api").gr_gid)


def provider():
    pid = subprocess.check_output(["systemctl", "show", "opticable-workflow-api.service",
                                   "-p", "MainPID", "--value"], text=True).strip()
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            os.environ[key.decode()] = value.decode()
    os.environ["OPTIBRAIN_PHASE8_TEST_LAB"] = "phase8-protected-test-lab-v1"
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    settings = load_settings()
    return ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))


def read(client, module, identity):
    result = client.request("zohoapis", "GET", f"/crm/v8/{module}/{identity}")
    rows = (result.get("data") or {}).get("data") or []
    if result.get("ok") is not True or len(rows) != 1 or str(rows[0].get("id")) != str(identity):
        raise ValueError(f"Exact {module} provider read failed")
    return rows[0]


def listing(client, module, fields):
    result = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                            query={"fields": fields, "page": 1, "per_page": 200})
    data = result.get("data") or {}
    rows = data.get("data") or []
    if result.get("ok") is not True or (data.get("info") or {}).get("more_records"):
        raise ValueError(f"Bounded {module} inventory unavailable")
    return rows


def initialize(client):
    if STATE.exists():
        print("already initialized", STATE)
        return
    cases = listing(client, "Cases", "id,Subject,Created_Time")
    snapshot = {"schema": 1, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "ids": sorted(str(row["id"]) for row in cases)}
    if CASE_BASELINE.exists():
        if load(CASE_BASELINE) != snapshot:
            raise ValueError("Existing Case snapshot needs review; not overwritten")
    else:
        atomic(CASE_BASELINE, snapshot)
    lab = load(LAB)
    lab.setdefault("records", {}).setdefault("Cases", [])
    lab["case_baseline_sha256"] = hashlib.sha256(CASE_BASELINE.read_bytes()).hexdigest()
    save_lab(lab)
    state = {"schema": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
             "case_baseline_sha256": lab["case_baseline_sha256"],
             "projects": {}, "crosswalk": {}, "operations": {}}
    save(state)
    print("protected Cases", len(cases), "registry", STATE)


def owned(lab, module, row):
    identity = str(row.get("id") or "")
    if identity not in set((lab.get("records") or {}).get(module) or []):
        raise ValueError(f"{module} record is not registered TEST_ONLY")
    marker = row.get("Name") if module in {"Services", "Service_Locations", "Installations"} else \
             row.get("Subject") if module in {"Cases", "Tasks"} else \
             row.get("Description")
    if not str(marker or "").startswith("OPTIBRAIN TEST — PHASE "):
        raise ValueError(f"{module} provider marker missing")
    if module not in {"Installations", "Cases", "Tasks"} and row.get("OptiBrain_Test") is not True:
        raise ValueError(f"{module} provider test flag missing")
    return row


def matches(actual, row):
    for key, expected in row.items():
        if isinstance(expected, dict) and "id" in expected:
            if str((actual.get(key) or {}).get("id") or "") != str(expected["id"]):
                return False
        elif key == "Scheduled_Date" and expected and actual.get(key):
            a = datetime.fromisoformat(str(actual[key]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
            if a.utcoffset() is None or b.utcoffset() is None or a != b: return False
        elif key != "id" and actual.get(key) != expected:
            return False
    return True


def write(client, state, lab, key, module, row, *, identity=None):
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    from workflow.automation.crm_write_boundary import fingerprint
    prior = state["operations"].get(key)
    if prior:
        if prior.get("id") and prior.get("state") == "verified":
            actual = read(client, module, prior["id"])
            if matches(actual, row): return actual
        raise ValueError(f"{key} was already attempted; reconcile provider before retry")
    before = read(client, module, identity) if identity else None
    if before: owned(lab, module, before)
    method = "PUT" if identity else "POST"
    path = f"/crm/v8/{module}" + (f"/{identity}" if identity else "")
    data = {"id": identity, **row} if identity else row
    body = {"data": [data], "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
    headers = {"If-Unmodified-Since": before["Modified_Time"]} if before else None
    state["operations"][key] = {"state": "attempted", "module": module,
        "target": identity, "at_utc": datetime.now(timezone.utc).isoformat(),
        "payload_hash": fingerprint(method, path, body, headers)}
    save(state)
    with reviewed_test_lab_call(client, method, path, body, headers):
        result = client.request("zohoapis", method, path, body=body, headers=headers,
                                reason="Phase 11 isolated TEST_ONLY operational proof", confirm=True)
    rows = (result.get("data") or {}).get("data") or []
    got = str((rows[0].get("details") or {}).get("id") or "") if len(rows) == 1 else ""
    if result.get("ok") is not True or len(rows) != 1 or rows[0].get("status") != "success" or not got.isdigit():
        raise ValueError(f"{key} provider acknowledgement ambiguous; reconcile first")
    if identity and got != identity:
        raise ValueError("Provider updated unexpected ID")
    state["operations"][key]["id"] = got
    save(state)
    if not identity:
        protected = (load(CASE_BASELINE)["ids"] if module == "Cases" else
                     load(SERVICE_BASELINE)["modules"][module] if module in {"Services", "Service_Locations", "Installations"} else
                     load(BASELINE)["modules"][module]["ids"])
        if got in set(protected):
            raise ValueError("Provider created protected ID")
        lab["records"].setdefault(module, []).append(got)
        save_lab(lab)
    actual = read(client, module, got)
    if not matches(actual, row):
        raise ValueError(f"{key} provider readback differs; reconcile")
    state["operations"][key]["state"] = "verified"
    save(state)
    return actual


def link(state, module, provider_id, *, customer=None, site=None, project=None):
    internal = stable_id(module, provider_id)
    current = state["crosswalk"].get(internal)
    item = {"internal_id": internal, "module": module, "provider_id": provider_id,
            "customer_id": customer, "site_id": site, "project_id": project,
            "test_only": True}
    if current and any(current.get(key) != value for key, value in item.items()):
        raise ValueError("Immutable crosswalk changed")
    if current:
        item = current
    else:
        item["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    state["crosswalk"][internal] = item
    save(state)
    return internal


def event(state, project, kind, internal_id, provider_version):
    identity = event_id(kind, internal_id, provider_version)
    events = project.setdefault("events", [])
    terminal_once = {"PROJECT_CREATED", "PROJECT_COMPLETED", "WORK_ORDER_CREATED",
                     "WORK_ORDER_COMPLETED", "SERVICE_INSTALLED", "SERVICE_TICKET_OPENED",
                     "SERVICE_TICKET_RESOLVED", "TASK_ROUTED", "DEAL_ACCEPTED"}
    if kind in terminal_once and any(x["kind"] == kind and x["object"] == internal_id for x in events):
        return False
    if any(x["id"] == identity for x in events): return False
    events.append({"id": identity, "kind": kind, "object": internal_id,
                   "at": datetime.now(timezone.utc).isoformat(), "evidence_version": provider_version})
    save(state)
    return True


def folders(state, project):
    ids = project["provider"]
    p = ROOT / "files" / stable_id("Accounts", ids["Accounts"]) / stable_id("Service_Locations", ids["Service_Locations"]) / project["id"]
    if project.get("folder") and project["folder"].get("path") != str(p):
        raise ValueError("Project folder path changed")
    for name in ("01 Quote", "02 Plans", "03 Photos", "04 Work Orders", "05 Service Reports", "06 Closeout"):
        (p / name).mkdir(parents=True, exist_ok=True, mode=0o750)
    project["folder"] = {"provider": "local", "path": str(p), "id": project["id"]}
    save(state)
    return p


def document(state, project, name, content):
    base = folders(state, project)
    if (name != Path(name).name or
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}_" + re.escape(project["id"]) + r"_[A-Za-z0-9_.-]+", name)):
        raise ValueError("Document name must be safe and project-scoped")
    datetime.strptime(name[:10], "%Y-%m-%d")
    category = classify_document(name)
    folder = {"QUOTE": "01 Quote", "PLAN": "02 Plans", "PHOTO": "03 Photos",
              "WORK ORDER": "04 Work Orders", "SERVICE REPORT": "05 Service Reports"}.get(category, "06 Closeout")
    path = base / folder / name
    digest = hashlib.sha256(content).hexdigest()
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("Document name collision")
    if not path.exists():
        with path.open("xb") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
    doc = {"name": name, "category": category, "sha256": digest, "path": str(path), "test_only": True}
    if doc not in project.setdefault("documents", []):
        project["documents"].append(doc); save(state)
        event(state, project, "DOCUMENT_ADDED", project["id"], digest)
    return doc


def seed(client, state, lab):
    for module, ident in (("Accounts", ACCOUNT), ("Contacts", CONTACT),
                          ("Deals", DEAL), ("Service_Locations", SITE)):
        owned(lab, module, read(client, module, ident))
    project_id = stable_id("Deals", DEAL)
    project = state["projects"].get(project_id)
    if project is None:
        project = {"id": project_id, "status": "PLANNING",
                   "provider": {"Accounts": ACCOUNT, "Contacts": CONTACT,
                                "Service_Locations": SITE, "Deals": DEAL},
                   "services": [], "work_orders": [], "tickets": [], "ticket_work_orders": {},
                   "documents": [], "events": [], "scheduled": None}
        state["projects"][project_id] = project
        save(state)
    cid = link(state, "Accounts", ACCOUNT)
    link(state, "Contacts", CONTACT, customer=cid)
    sid = link(state, "Service_Locations", SITE, customer=cid)
    link(state, "Deals", DEAL, customer=cid, site=sid, project=project_id)
    folders(state, project)
    document(state, project, f"2026-10-01_{project_id}_Quote_v1.txt",
             b"OPTIBRAIN TEST ONLY\nWarehouse camera installation and cabling scope.\nNo customer or financial data.\n")
    service = write(client, state, lab, "camera:service", "Services", {
        "Name": f"{MARKER} — Warehouse camera installation",
        "Linked_Service_Location": {"id": SITE}, "Linked_Deal": {"id": DEAL},
        "Service_Type": "Camera Installation", "Service_Stage": "Ready for Scheduling",
        "Contract_Type": "Installation", "OptiBrain_Test": True})
    service_id = str(service["id"])
    if service_id not in project["services"]: project["services"].append(service_id); save(state)
    link(state, "Services", service_id, customer=cid, site=sid, project=project_id)
    work = write(client, state, lab, "camera:work", "Installations", {
        "Name": f"{MARKER} — Camera install {project_id}", "Linked_Service": {"id": service_id},
        "Installation_Type": "Initial Installation", "Installation_Status": "Requested",
        "Instructions_Notes": "Synthetic warehouse camera installation; confirm access and mounting locations."})
    work_id = str(work["id"])
    if work_id not in project["work_orders"]: project["work_orders"].append(work_id); save(state)
    wid = link(state, "Installations", work_id, customer=cid, site=sid, project=project_id)
    event(state, project, "PROJECT_CREATED", project_id, project["created_version"] if "created_version" in project else str(read(client,"Deals",DEAL)["Created_Time"]))
    event(state, project, "WORK_ORDER_CREATED", wid, work["Created_Time"])
    print("project", project_id, "service", service_id, "work", work_id)


def primary(state):
    if len(state["projects"]) != 1: raise ValueError("Expected one isolated Test Lab project")
    return next(iter(state["projects"].values()))


def advance(client, state, lab, step):
    p = primary(state); work_id = p["work_orders"][0]; service_id = p["services"][-1]
    if step == "schedule":
        planned = "2026-10-02T10:00:00-04:00"
        work = write(client,state,lab,"camera:scheduled","Installations",
                     {"Installation_Status":"Scheduled","Scheduled_Date":planned},identity=work_id)
        p["status"]="SCHEDULED";p["scheduled"]=planned;save(state)
        event(state,p,"PROJECT_SCHEDULED",p["id"],work["Modified_Time"])
    elif step == "start":
        work=write(client,state,lab,"camera:in_progress","Installations",
                   {"Installation_Status":"In Progress"},identity=work_id)
        p["status"]="IN PROGRESS";save(state)
        event(state,p,"WORK_ORDER_STARTED",stable_id("Installations",work_id),work["Modified_Time"])
    elif step == "complete":
        work=write(client,state,lab,"camera:completed","Installations",
                   {"Installation_Status":"Completed","Completion_Notes":"OPTIBRAIN TEST ONLY — 12 cameras and cabling installed; commissioning check passed."},identity=work_id)
        event(state,p,"WORK_ORDER_COMPLETED",stable_id("Installations",work_id),work["Modified_Time"])
        service=write(client,state,lab,"camera:installed_service","Services",
                      {"Service_Stage":"Active","OptiBrain_Installed_On":"2026-10-01"},identity=service_id)
        event(state,p,"SERVICE_INSTALLED",stable_id("Services",service_id),service["Modified_Time"])
        deal=write(client,state,lab,"camera:deal_complete","Deals",{"Stage":"Closed Won"},identity=DEAL)
        p["status"]="COMPLETED";save(state)
        event(state,p,"PROJECT_COMPLETED",p["id"],deal["Modified_Time"])
        document(state,p,f"2026-10-01_{p['id']}_ServiceReport.txt",
                 b"OPTIBRAIN TEST ONLY\nCamera installation completed; 12 cameras commissioned.\n")
    else: raise ValueError("Unknown transition")
    print(step,p["id"],p["status"])


def ticket(client,state,lab):
    p=primary(state); account=ACCOUNT; contact=CONTACT; deal=DEAL
    case=write(client,state,lab,"camera:case","Cases",{
        "Subject":f"{MARKER} — Camera offline at warehouse",
        "Description":f"{MARKER}\nSynthetic camera 7 offline after installation; field check required.",
        "Account_Name":{"id":account},"Related_To":{"id":contact},"Deal_Name":{"id":deal},
        "Status":"New","Case_Origin":"Web","Priority":"Medium","Type":"Problem"})
    case_id=str(case["id"])
    if case_id not in p["tickets"]:p["tickets"].append(case_id);save(state)
    cid=stable_id("Accounts",account);sid=stable_id("Service_Locations",SITE)
    tid=link(state,"Cases",case_id,customer=cid,site=sid,project=p["id"])
    event(state,p,"SERVICE_TICKET_OPENED",tid,case["Created_Time"])
    work=write(client,state,lab,"camera:repair_work","Installations",{
        "Name":f"{MARKER} — Camera service {p['id']}",
        "Linked_Service":{"id":p["services"][-1]},"Installation_Type":"Repair",
        "Installation_Status":"Requested",
        "Instructions_Notes":"Synthetic camera 7 power and network assessment."})
    work_id=str(work["id"])
    if work_id not in p["work_orders"]:p["work_orders"].append(work_id);save(state)
    p["ticket_work_orders"][case_id]=[work_id];save(state)
    wid=link(state,"Installations",work_id,customer=cid,site=sid,project=p["id"])
    event(state,p,"WORK_ORDER_CREATED",wid,work["Created_Time"])
    print("ticket",case_id,"repair",work_id)


def resolve(client,state,lab):
    p=primary(state);case_id=p["tickets"][0];work_id=p["ticket_work_orders"][case_id][0]
    for key,status in (("repair:scheduled","Scheduled"),("repair:started","In Progress"),
                       ("repair:completed","Completed")):
        fields={"Installation_Status":status}
        if status=="Scheduled":fields["Scheduled_Date"]="2026-10-01T08:00:00-04:00"
        if status=="Completed":fields["Completion_Notes"]="OPTIBRAIN TEST ONLY — camera power restored; image verified."
        work=write(client,state,lab,key,"Installations",fields,identity=work_id)
        if status=="Completed":event(state,p,"WORK_ORDER_COMPLETED",stable_id("Installations",work_id),work["Modified_Time"])
    case=write(client,state,lab,"camera:case_resolved","Cases",{
        "Status":"Closed","Solution":"OPTIBRAIN TEST ONLY — power connector reseated; feed verified."},identity=case_id)
    event(state,p,"SERVICE_TICKET_RESOLVED",stable_id("Cases",case_id),case["Modified_Time"])
    service_id=p["services"][-1]
    service=write(client,state,lab,"camera:service_checked","Services",
                  {"OptiBrain_Last_Service_On":"2026-10-01"},identity=service_id)
    event(state,p,"SERVICE_CHECK_COMPLETED",stable_id("Services",service_id),service["Modified_Time"])
    print("ticket resolved",case_id)


def replay(client,state,lab):
    p=primary(state); before=len(p["events"]); folder=folders(state,p)
    for module, ids, kind in (("Installations",p["work_orders"],"WORK_ORDER_COMPLETED"),
                              ("Cases",p["tickets"],"SERVICE_TICKET_RESOLVED")):
        for ident in ids:
            row=owned(lab,module,read(client,module,ident))
            if (module=="Installations" and row.get("Installation_Status")=="Completed") or \
               (module=="Cases" and row.get("Status")=="Closed"):
                event(state,p,kind,stable_id(module,ident),row["Modified_Time"])
    print("replay events added",len(p["events"])-before,"folder",folder)


def organize(client,state,lab):
    """Idempotent project/folder check without replaying historical CRM creates."""
    p=primary(state)
    before=(len(p["work_orders"]),len(p["services"]),len(p["tickets"]),len(p.get("tasks",[])),
           len(p["documents"]),len(p["events"]),len(state["crosswalk"]))
    folder=folders(state,p)
    for module,ids in (("Accounts",[ACCOUNT]),("Contacts",[CONTACT]),
                       ("Deals",[DEAL]),("Service_Locations",[SITE]),
                       ("Services",p["services"]),("Installations",p["work_orders"]),
                       ("Cases",p["tickets"]),("Tasks",p.get("tasks",[]))):
        for ident in ids:owned(lab,module,read(client,module,ident))
    for doc in p["documents"]:
        path=Path(doc["path"])
        if not path.is_relative_to(folder) or hashlib.sha256(path.read_bytes()).hexdigest()!=doc["sha256"]:
            raise ValueError("Project document content or location drifted")
    after=(len(p["work_orders"]),len(p["services"]),len(p["tickets"]),len(p.get("tasks",[])),
           len(p["documents"]),len(p["events"]),len(state["crosswalk"]))
    if before!=after:raise ValueError("Organization replay created duplicate objects")
    print("organization stable",p["id"],"counts",after,"folder",folder)


def task(client,state,lab):
    p=primary(state)
    row={"Subject":f"{MARKER} — Archive warehouse installation photos",
         "Description":f"{MARKER}\nCategory DOCUMENT; project {p['id']}; site {stable_id('Service_Locations',SITE)}.",
         "What_Id":{"id":DEAL},"$se_module":"Deals","Status":"Not Started",
         "Due_Date":"2026-10-02"}
    record=write(client,state,lab,"camera:document_task","Tasks",row)
    identity=str(record["id"])
    if identity not in p.setdefault("tasks",[]):p["tasks"].append(identity);save(state)
    p.setdefault("task_categories",{})[identity]="DOCUMENT";save(state)
    cid=stable_id("Accounts",ACCOUNT);sid=stable_id("Service_Locations",SITE)
    tid=link(state,"Tasks",identity,customer=cid,site=sid,project=p["id"])
    event(state,p,"TASK_ROUTED",tid,record["Created_Time"])
    print("task",identity,"project",p["id"])


def link_source(client,state,lab):
    p=primary(state)
    phase9=load(Path("/var/lib/optibrain/phase9/test-lab/registry.json"))
    lead_id=str(phase9.get("lead_id") or "")
    outcome=phase9.get("outcome") or {}
    if (not lead_id.isdigit() or any(str((outcome.get(name) or {}).get("id")) != expected
        for name, expected in (("account",ACCOUNT),("contact",CONTACT),("deal",DEAL)))):
        raise ValueError("Phase 9 source relationship not verified")
    owned(lab,"Leads",read(client,"Leads",lead_id))
    if lead_id not in str(read(client,"Deals",DEAL).get("Description") or ""):
        raise ValueError("Deal does not cite source Lead")
    if p.get("source_lead_id") and p["source_lead_id"]!=lead_id:
        raise ValueError("Source Lead identity changed")
    p["source_lead_id"]=lead_id;save(state)
    print("source Lead linked",lead_id,"project",p["id"])


def normalize_schedule(client,state,lab):
    """Keep the synthetic completed visit's planned slot before its completion."""
    p=primary(state)
    planned="2026-10-01T07:30:00-04:00"
    row=write(client,state,lab,"camera:synthetic_schedule_normalized","Installations",
              {"Scheduled_Date":planned},identity=p["work_orders"][0])
    p["scheduled"]=planned;save(state)
    event(state,p,"SCHEDULE_RECONCILED",stable_id("Installations",row["id"]),row["Modified_Time"])
    print("synthetic schedule reconciled",planned)


def backfill_crosswalk_times(client,state,lab):
    count=0
    for internal,item in state["crosswalk"].items():
        row=owned(lab,item["module"],read(client,item["module"],item["provider_id"]))
        source=datetime.fromisoformat(str(row["Created_Time"]).replace("Z","+00:00"))
        if source.utcoffset() is None:raise ValueError("Naive CRM created time")
        created=source.astimezone(timezone.utc).isoformat()
        if item.get("created_at_utc") and item["created_at_utc"] != created:
            raise ValueError("Crosswalk created time changed")
        if not item.get("created_at_utc"):
            item["created_at_utc"]=created;count+=1
    save(state)
    print("crosswalk provider-created times set",count)


def repair_event_replay(state):
    p=primary(state)
    terminal_once={"PROJECT_CREATED","PROJECT_COMPLETED","WORK_ORDER_CREATED",
                   "WORK_ORDER_COMPLETED","SERVICE_INSTALLED","SERVICE_TICKET_OPENED",
                   "SERVICE_TICKET_RESOLVED","TASK_ROUTED"}
    prior=load(STATE)
    seen=set();keep=[];removed=[]
    for row in p["events"]:
        key=(row["kind"],row["object"])
        if row["kind"] in terminal_once and key in seen:removed.append(row)
        else:keep.append(row);seen.add(key)
    if not removed:
        print("event ledger clean");return
    snapshot=ROOT/"registry-before-event-replay-repair.json"
    if snapshot.exists():raise ValueError("Repair snapshot already exists; review before modifying")
    atomic(snapshot,prior)
    p["events"]=keep
    state.setdefault("event_repairs",[]).append({"at_utc":datetime.now(timezone.utc).isoformat(),
        "reason":"Zoho Modified_Time changed after terminal completion; replay must not duplicate terminal event",
        "removed_event_ids":[x["id"] for x in removed],"preserved_snapshot":str(snapshot)})
    save(state)
    print("terminal replay duplicates archived and removed",len(removed))


def main():
    if os.geteuid()!=0:raise SystemExit("root required")
    if len(sys.argv)!=2 or sys.argv[1] not in {"init","seed","schedule","start","complete","ticket","resolve","replay","organize","task","link-source","normalize-schedule","repair-event-replay","backfill-crosswalk-times"}:
        raise SystemExit("usage: test_lab_operations.py init|seed|schedule|start|complete|ticket|resolve|replay|organize|task|link-source|normalize-schedule|repair-event-replay|backfill-crosswalk-times")
    client=provider();action=sys.argv[1]
    if action=="init":initialize(client);return
    state=load(STATE);lab=load(LAB)
    if state["case_baseline_sha256"] != lab.get("case_baseline_sha256"):
        raise ValueError("Case protected baseline digest mismatch")
    if action=="seed":seed(client,state,lab)
    elif action in {"schedule","start","complete"}:advance(client,state,lab,action)
    elif action=="ticket":ticket(client,state,lab)
    elif action=="resolve":resolve(client,state,lab)
    elif action=="replay":replay(client,state,lab)
    elif action=="organize":organize(client,state,lab)
    elif action=="task":task(client,state,lab)
    elif action=="link-source":link_source(client,state,lab)
    elif action=="normalize-schedule":normalize_schedule(client,state,lab)
    elif action=="repair-event-replay":repair_event_replay(state)
    elif action=="backfill-crosswalk-times":backfill_crosswalk_times(client,state,lab)


if __name__=="__main__":main()
