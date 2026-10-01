#!/usr/bin/env python3
"""Create two bounded Test Lab CRM-origin intakes with truthful source labels."""
import grp
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
ROOT = Path("/var/lib/optibrain/phase9/test-lab")
STATE = ROOT / "registry.json"
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
PROJECTION = Path("/etc/optibrain/phase8-test-lab-registry.json")
MARKER = "OPTIBRAIN TEST — PHASE 9"
SCENARIOS = {"manual_crm": "manual-p9@optibrain.invalid",
             "unknown_source": "unknown-p9@optibrain.invalid"}


def atomic(path, value, mode=0o600, gid=None):
    temp = path.with_name("." + path.name + ".phase9tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as out:
        json.dump(value, out, indent=2, sort_keys=True, ensure_ascii=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    if gid is not None:
        os.chown(temp, 0, gid)
    os.chmod(temp, mode)
    os.replace(temp, path)


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


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        raise SystemExit("Root and one scenario: manual_crm or unknown_source")
    scenario = sys.argv[1]
    email = SCENARIOS[scenario]
    state = json.loads(STATE.read_text())
    lab = json.loads(LAB.read_text())
    baseline = json.loads(BASELINE.read_text())
    if lab["baseline_sha256"] != hashlib.sha256(BASELINE.read_bytes()).hexdigest():
        raise ValueError("Protected baseline changed")
    if scenario in state.setdefault("manual_events", {}):
        raise ValueError("Scenario already attempted; reconcile, do not retry")
    client = provider()
    for module in ("Leads", "Contacts"):
        response = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                                  query={"fields": "id,Email", "per_page": 100, "page": 1})
        data = response.get("data") or {}
        if response.get("ok") is not True or not isinstance(data.get("data"), list) or (data.get("info") or {}).get("more_records"):
            raise ValueError("CRM identity list incomplete")
        if any(str(x.get("Email") or "").casefold() == email for x in data["data"]):
            raise ValueError("TEST_ONLY email already exists")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    inquiry = str(uuid4())
    row = {"First_Name": "Phase 9", "Last_Name": MARKER + " — " + scenario,
           "Company": MARKER + " — Manual Lab", "Email": email,
           "Normalized_Email": email, "OptiBrain_Test": True,
           "Description": MARKER + "\nSynthetic direct CRM intake; no customer identity.",
           "Lead_Status": "Not Contacted", "Source_Record_ID": "phase9-manual-" + scenario,
           "Inquiry_ID": inquiry}
    if scenario == "manual_crm":
        row.update(Ingestion_Source="manual_crm", First_Source="manual_crm",
                   Last_Source="manual_crm", First_Touch_Time=now, Last_Touch_Time=now)
    body = {"data": [row], "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
    receipt = {"source": "manual_crm" if scenario == "manual_crm" else "unknown",
               "source_detail": "direct CRM Test Lab creation", "inquiry_id": inquiry,
               "email": email, "occurred_at": now, "request": row,
               "attribution": {}, "form_id": None, "crm_action": "created_lead"}
    state["manual_events"][scenario] = {"state": "attempted", "receipt": receipt,
                                         "payload_hash": hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()}
    atomic(STATE, state)
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    with reviewed_test_lab_call(client, "POST", "/crm/v8/Leads", body):
        answer = client.request("zohoapis", "POST", "/crm/v8/Leads", body=body,
                                reason="Create isolated Phase 9 manual/unknown TEST_ONLY Lead", confirm=True)
    rows = (answer.get("data") or {}).get("data") or []
    if answer.get("ok") is not True or len(rows) != 1 or rows[0].get("status") != "success":
        raise ValueError("CRM manual create acknowledgement ambiguous; reconcile")
    identity = str((rows[0].get("details") or {}).get("id") or "")
    if not identity.isdigit() or identity in baseline["modules"]["Leads"]["ids"]:
        raise ValueError("Created Lead identity invalid/protected")
    state["manual_events"][scenario]["lead_id"] = identity
    atomic(STATE, state)
    if identity not in lab["records"]["Leads"]:
        lab["records"]["Leads"].append(identity)
        atomic(LAB, lab)
    read = client.request("zohoapis", "GET", f"/crm/v8/Leads/{identity}")
    records = (read.get("data") or {}).get("data") or []
    if len(records) != 1 or records[0].get("OptiBrain_Test") is not True or records[0].get("Inquiry_ID") != inquiry:
        raise ValueError("Manual Lead readback mismatch")
    atomic(PROJECTION, lab, mode=0o640, gid=grp.getgrnam("opticable-workflow-api").gr_gid)
    from workflow.automation.phase9_intake import IntakeLedger
    ledger = IntakeLedger(Path("/var/lib/opticable-workflow-api/output/automation/phase9-intake.db"))
    result = ledger.record(receipt, records[0])
    ledger.feedback(kind="LEAD_CREATED", canonical_id=identity, related_module="Leads",
                    related_id=identity, occurred_at=records[0]["Created_Time"],
                    evidence={"lead_id": identity, "inquiry_id": inquiry})
    state["manual_events"][scenario].update(state="verified", event_id=result["event_id"],
                                             decision=result["decision"])
    atomic(STATE, state)
    print(json.dumps({"scenario": scenario, "lead_id": identity,
                      "event_id": result["event_id"], "source": receipt["source"]}))


if __name__ == "__main__":
    main()
