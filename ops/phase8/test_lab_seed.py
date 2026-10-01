#!/usr/bin/env python3
"""Manual, root-only, journaled provider-backed Phase 8 Test Lab seed.

Creates one record at a time. Any unconfirmed write stops for reconciliation.
Never targets a record from the protected pre-mission inventory.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
ROOT = Path("/var/lib/optibrain/phase8/test-lab")
REGISTRY = ROOT / "registry.json"
JOURNAL = ROOT / "seed-journal.json"
MARKER = "OPTIBRAIN TEST — PHASE 8"
SCENARIOS = [
    ("urgent", "Urgent Cabling", "Lab Urgent Systems", "urgent@optibrain.invalid",
     "test_ai_website", "Pre-Qualified", "Structured cabling", "100 Test Lab Boulevard",
     "48 CAT6 drops, rack cleanup, two switch uplinks", "Installation needed within 2 weeks", None),
    ("quote", "Wi-Fi Quote", "Lab Wireless Group", "quote@optibrain.invalid",
     "test_main_website", "Pre-Qualified", "Wi-Fi", "200 Test Lab Avenue",
     "12 access points across 3 floors; existing floor plans available", "Next month", None),
    ("overdue", "Overdue Access", "Lab Access Group", "overdue@optibrain.invalid",
     "test_zoho_form", "Attempted to Contact", "Access control", "300 Test Lab Road",
     None, "This quarter", "2026-09-24T17:00:00-04:00"),
    ("waiting", "Waiting Cameras", "Lab Camera Group", "hckyan97+obp8wait@gmail.com",
     "test_email_manual", "Attempted to Contact", "Cameras", "400 Test Lab Street",
     None, "This quarter", "2026-10-02T17:00:00-04:00"),
    ("replied", "Replied Wi-Fi", "Lab Reply Group", "info@opticable.ca",
     "test_email_manual", "Attempted to Contact", "Wi-Fi", "500 Test Lab Street",
     None, "This quarter", "2026-10-02T17:00:00-04:00"),
    ("incomplete", "Incomplete Discovery", "Lab Discovery Group", "incomplete@optibrain.invalid",
     "test_zoho_form", "Not Contacted", None, None,
     None, None, None),
    ("low", "Early Research", "Lab Research Group", "early@optibrain.invalid",
     "test_main_website", "Not Contacted", None, None,
     None, "No project planned; research only", None),
    ("duplicate_a", "Duplicate A", "Lab Duplicate Group", "duplicate@optibrain.invalid",
     "test_ai_website", "Not Contacted", "Structured cabling", None,
     None, None, None),
    ("duplicate_b", "Duplicate B", "Lab Duplicate Group", "duplicate@optibrain.invalid",
     "test_zoho_form", "Not Contacted", "Structured cabling", None,
     None, None, None),
]


def atomic(path, value):
    temp = path.with_name("." + path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def record_ack(response):
    rows = (response.get("data") or {}).get("data")
    if response.get("ok") is not True or response.get("status") not in {200, 201, 202} or not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "success":
        raise ValueError("Test Lab create acknowledgement ambiguous; reconcile, do not retry")
    identity = str((rows[0].get("details") or {}).get("id") or "")
    if not re.fullmatch(r"[0-9]{1,30}", identity):
        raise ValueError("Test Lab create has no provider ID; reconcile, do not retry")
    return identity


def main():
    if os.geteuid() != 0 or sys.argv[1:] != ["--execute"]:
        raise SystemExit("Root and --execute required")
    pid = subprocess.check_output(["systemctl", "show", "opticable-workflow-api.service", "-p", "MainPID", "--value"], text=True).strip()
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            os.environ[key.decode()] = value.decode()
    os.environ["OPTIBRAIN_PHASE8_TEST_LAB"] = "phase8-protected-test-lab-v1"
    sys.path.insert(0, str(APP))
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    settings = load_settings()
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    registry = load(REGISTRY, None)
    if not registry:
        raise ValueError("Protected Test Lab registry missing")
    journal = load(JOURNAL, {})
    for (key, title, company, email, source, status, service, street, scope, timeline, due) in SCENARIOS:
        if key in registry["scenarios"]:
            print(key, "already registered", registry["scenarios"][key]["lead_id"], flush=True)
            continue
        if key in journal:
            raise ValueError(f"{key} has unconfirmed prior attempt; reconcile before continuing")
        row = {"First_Name": "OptiBrain Test", "Last_Name": MARKER + " — " + title,
               "Company": MARKER + " — " + company, "Email": email,
               "Lead_Status": status, "Ingestion_Source": source,
               "Source_Record_ID": "optibrain-phase8-lab-" + key,
               "Description": MARKER + "\nSynthetic scenario: " + key + "\nNever use for customer outreach or revenue reporting.",
               "OptiBrain_Test": True}
        for field, value in (("Service_Types", service), ("Street", street),
                             ("Scope", scope), ("Project_Timeline", timeline),
                             ("Next_Followup_At", due)):
            if value is not None:
                row[field] = value
        body = {"data": [row], "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
        journal[key] = {"state": "attempted", "at_utc": datetime.now(timezone.utc).isoformat(),
                        "payload_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
        atomic(JOURNAL, journal)
        with reviewed_test_lab_call(client, "POST", "/crm/v8/Leads", body):
            response = client.request("zohoapis", "POST", "/crm/v8/Leads", body=body,
                                      reason=f"Create isolated OptiBrain Test Lab Lead {key}", confirm=True)
        identity = record_ack(response)
        journal[key]["ack_id"] = identity
        atomic(JOURNAL, journal)
        registry["records"]["Leads"].append(identity)
        registry["scenarios"][key] = {"lead_id": identity, "scenario": key,
                                      "expected": "pending validation", "email": email,
                                      "source": source, "cleanup": "retain for Phase 9-12 regression; exclude from live metrics"}
        atomic(REGISTRY, registry)
        data = client.request("zohoapis", "GET", f"/crm/v8/Leads/{identity}")
        got = (data.get("data") or {}).get("data") or []
        if len(got) != 1 or str(got[0].get("id")) != identity or got[0].get("OptiBrain_Test") is not True or got[0].get("Source_Record_ID") != row["Source_Record_ID"]:
            raise ValueError(f"{key} readback mismatch; stop")
        journal[key]["state"] = "verified"
        atomic(JOURNAL, journal)
        print(key, identity, "verified", flush=True)


if __name__ == "__main__":
    main()
