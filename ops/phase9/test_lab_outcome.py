#!/usr/bin/env python3
"""Manually invoked, journaled Test Lab qualification and opportunity trace."""
import grp
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
ROOT = Path("/var/lib/optibrain/phase9/test-lab")
STATE = ROOT / "registry.json"
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
PROJECTION = Path("/etc/optibrain/phase8-test-lab-registry.json")
MARKER = "OPTIBRAIN TEST — PHASE 9"
EMAIL = "hckyan97+obp9intake1@gmail.com"


def atomic(path, value, *, mode=0o600, gid=None):
    temp = path.with_name("." + path.name + ".phase9tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if gid is not None:
        os.chown(temp, 0, gid)
    os.chmod(temp, mode)
    os.replace(temp, path)


def load(path):
    return json.loads(path.read_text())


def provider():
    pid = subprocess.check_output(["systemctl", "show", "opticable-workflow-api.service",
                                   "-p", "MainPID", "--value"], text=True).strip()
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            os.environ[key.decode()] = value.decode()
    os.environ["OPTIBRAIN_PHASE8_TEST_LAB"] = "phase8-protected-test-lab-v1"
    sys.path.insert(0, str(APP))
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    settings = load_settings()
    return ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))


def read(client, module, identity):
    result = client.request("zohoapis", "GET", f"/crm/v8/{module}/{identity}")
    rows = (result.get("data") or {}).get("data") or []
    if result.get("ok") is not True or len(rows) != 1 or str(rows[0].get("id")) != str(identity):
        raise ValueError("Exact provider readback failed")
    return rows[0]


def complete_list(client, module, fields):
    result = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                            query={"fields": fields, "per_page": 100, "page": 1})
    data = result.get("data") or {}
    if result.get("ok") is not True or not isinstance(data.get("data"), list) or (data.get("info") or {}).get("more_records"):
        raise ValueError("Bounded CRM module list incomplete")
    return data["data"]


def grant_write(client, method, module, body, *, target=None, version=None):
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    path = f"/crm/v8/{module}" + (f"/{target}" if target else "")
    headers = {"If-Unmodified-Since": version} if target else None
    with reviewed_test_lab_call(client, method, path, body, headers):
        result = client.request("zohoapis", method, path, body=body, headers=headers,
                                reason="Phase 9 isolated TEST_ONLY qualification/opportunity", confirm=True)
    if result.get("ok") is not True:
        raise ValueError("Provider mutation unconfirmed; reconcile, do not retry")
    rows = (result.get("data") or {}).get("data") or []
    if len(rows) != 1 or rows[0].get("status") != "success":
        raise ValueError("Provider acknowledgement ambiguous; reconcile")
    return str((rows[0].get("details") or {}).get("id") or "")


def main():
    if os.geteuid() != 0 or sys.argv[1:] != ["--execute"]:
        raise SystemExit("Root and --execute required")
    state = load(STATE)
    if not all(state.get("events", {}).get(key, {}).get("state") == "verified"
               for key in ("new_ai", "return_ai", "cross_main")):
        raise ValueError("Provider-backed intake chain is incomplete")
    baseline = load(BASELINE)
    lab = load(LAB)
    if lab["baseline_sha256"] != hashlib.sha256(BASELINE.read_bytes()).hexdigest():
        raise ValueError("Protected baseline changed")
    lead_id = str(state["lead_id"])
    if lead_id in baseline["modules"]["Leads"]["ids"] or lead_id not in lab["records"]["Leads"]:
        raise ValueError("Opportunity Lead is not exclusively Test Lab owned")
    client = provider()
    lead = read(client, "Leads", lead_id)
    if (lead.get("Email") != EMAIL or lead.get("OptiBrain_Test") is not True
            or not str(lead.get("Description") or "").startswith(MARKER)):
        raise ValueError("Opportunity Lead marker/identity changed")
    journal = state.setdefault("outcome", {})
    if "qualification" not in journal:
        body = {"data": [{"id": lead_id, "Lead_Status": "Pre-Qualified",
                           "Service_Types": "Cameras", "Street": "12 Test Lab Warehouse Road, Montreal",
                           "Scope": "12 synthetic cameras covering warehouse entry and loading zones",
                           "Project_Timeline": "Within three weeks"}],
                "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
        journal["qualification"] = {"state": "attempted", "payload_hash": hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()}
        atomic(STATE, state)
        grant_write(client, "PUT", "Leads", body, target=lead_id, version=lead["Modified_Time"])
        lead = read(client, "Leads", lead_id)
        if not (lead["Lead_Status"] == "Pre-Qualified" and lead["Service_Types"] == "Cameras"
                and lead["Street"].startswith("12 Test Lab") and "12 synthetic cameras" in lead["Scope"]):
            raise ValueError("Qualification readback mismatch")
        journal["qualification"].update(state="verified", crm_version=lead["Modified_Time"])
        atomic(STATE, state)
    elif journal["qualification"]["state"] != "verified":
        raise ValueError("Qualification attempted; reconcile before continuation")
    else:
        lead = read(client, "Leads", lead_id)
    from workflow.automation.phase9_intake import IntakeLedger
    from workflow.automation.sales_queue import analyze_queue
    ledger = IntakeLedger(Path("/var/lib/opticable-workflow-api/output/automation/phase9-intake.db"))
    decision = analyze_queue([lead], [], [], None, now=datetime.now(timezone.utc),
                             leads_complete=True, relationships_complete=True)["rows"][0]
    if decision["quote"] != "READY FOR QUOTE":
        raise ValueError("Provider-backed Lead is not quote-ready")
    for kind in ("QUALIFIED_LEAD", "QUOTE_READY"):
        ledger.feedback(kind=kind, canonical_id=lead_id, related_module="Leads", related_id=lead_id,
                        occurred_at=lead["Modified_Time"],
                        evidence={"lead_id": lead_id, "version": lead["Modified_Time"],
                                  "service": lead["Service_Types"], "scope": lead["Scope"]})

    def create(name, module, row, unique_field):
        existing = journal.get(name)
        if existing:
            if existing.get("state") != "verified":
                raise ValueError(name + " creation attempted; reconcile before continuation")
            record = read(client, module, existing["id"])
            if record.get("OptiBrain_Test") is not True or not str(record.get("Description") or "").startswith(MARKER):
                raise ValueError(name + " registered record lost TEST_ONLY marker")
            return record
        matches = [x for x in complete_list(client, module, f"id,{unique_field}")
                   if str(x.get(unique_field) or "") == str(row[unique_field])]
        if matches:
            raise ValueError(name + " name already exists; reconcile before create")
        body = {"data": [row], "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
        journal[name] = {"state": "attempted", "payload_hash": hashlib.sha256(json.dumps(body,sort_keys=True,default=str).encode()).hexdigest()}
        atomic(STATE, state)
        identity = grant_write(client, "POST", module, body)
        if not identity.isdigit() or identity in baseline["modules"][module]["ids"]:
            raise ValueError(name + " create ID ambiguous/protected")
        journal[name]["id"] = identity
        atomic(STATE, state)
        if identity not in lab["records"][module]:
            lab["records"][module].append(identity)
            atomic(LAB, lab)
        record = read(client, module, identity)
        if record.get("OptiBrain_Test") is not True or not str(record.get("Description") or "").startswith(MARKER):
            raise ValueError(name + " readback marker missing")
        journal[name]["state"] = "verified"
        atomic(STATE, state)
        atomic(PROJECTION, lab, mode=0o640, gid=grp.getgrnam("opticable-workflow-api").gr_gid)
        return record

    account_name = str(lead["Company"])
    account = create("account", "Accounts", {"Account_Name": account_name, "OptiBrain_Test": True,
                     "Description": MARKER + "\nSynthetic source-to-opportunity Account; no customer revenue."}, "Account_Name")
    first = {key: lead.get(key) for key in ("First_Source", "First_Medium", "First_Campaign",
             "First_Touch_Time", "Last_Source", "Last_Medium", "Last_Campaign", "Last_Touch_Time")
             if lead.get(key) is not None}
    contact = create("contact", "Contacts", {"First_Name": "Phase 9 Test",
                     "Last_Name": MARKER + " — Intake Contact", "Email": EMAIL,
                     "OptiBrain_Test": True,
                     "Account_Name": {"id": str(account["id"])},
                     "Description": MARKER + "\nSynthetic Contact from controlled Lead " + lead_id,
                     "Ingestion_Source": lead["Ingestion_Source"], "Inquiry_ID": lead["Inquiry_ID"], **first}, "Email")
    deal = create("deal", "Deals", {"Deal_Name": MARKER + " — Warehouse cameras opportunity",
                 "Stage": "Qualification", "OptiBrain_Test": True,
                 "Account_Name": {"id": str(account["id"])},
                 "Contact_Name": {"id": str(contact["id"])},
                 "Description": MARKER + "\nSynthetic, no amount, no Books transaction. Lead " + lead_id,
                 "Ingestion_Source": lead["Ingestion_Source"], "Inquiry_ID": lead["Inquiry_ID"], **first}, "Deal_Name")
    if (str((contact.get("Account_Name") or {}).get("id")) != str(account["id"])
            or str((deal.get("Account_Name") or {}).get("id")) != str(account["id"])
            or str((deal.get("Contact_Name") or {}).get("id")) != str(contact["id"])):
        raise ValueError("Provider relationship readback mismatch")
    if deal.get("Amount") not in (None, 0, 0.0):
        raise ValueError("Synthetic Deal has unexpected value")
    if any(deal.get(key) != lead.get(key) for key in first):
        raise ValueError("Deal lost source attribution")
    ledger.feedback(kind="OPPORTUNITY_CREATED", canonical_id=lead_id, related_module="Deals",
                    related_id=str(deal["id"]), occurred_at=deal["Created_Time"],
                    evidence={"lead_id": lead_id, "contact_id": str(contact["id"]),
                              "account_id": str(account["id"]), "deal_id": str(deal["id"]),
                              "first_source": deal.get("First_Source"), "latest_source": deal.get("Last_Source")})
    print(json.dumps({"lead": lead_id, "account": str(account["id"]),
                      "contact": str(contact["id"]), "deal": str(deal["id"]),
                      "quote": decision["quote"], "amount": deal.get("Amount")},sort_keys=True))


if __name__ == "__main__":
    main()
