#!/usr/bin/env python3
"""One-shot, journal-before-write repair of the unique form-created TEST_ONLY Lead.

The form has already created the Lead. This tool never creates a second one.
"""
from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path
import sys

from test_lab_intake import atomic, client_from_service, find, read_lead

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))

from workflow.automation.phase9_form_receipts import FormReceiptLedger
from workflow.automation.phase9_intake import IntakeLedger
from workflow.automation.test_lab_boundary import reviewed_test_lab_call

MAIL_DB = Path("/var/lib/optibrain/phase9/mission2/form-receipts-stage.db")
INTAKE_DB = Path("/var/lib/opticable-workflow-api/output/automation/phase9-intake.db")
JOURNAL = Path("/var/lib/optibrain/phase9/mission2/form-crm-adopt-v2.json")
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
PROJECTION = Path("/etc/optibrain/phase8-test-lab-registry.json")
EMAIL = "hckyan97+obp9form1@gmail.com"
PHONE = "5145550187"
PROVIDER_ID = "1790820040661162800"
LEAD_ID = "5062683000007935001"
MARKER = "OPTIBRAIN TEST — PHASE 9"


def main():
    if os.geteuid() != 0 or JOURNAL.exists():
        raise ValueError("One-shot form adoption requires root and an untouched journal")
    receipts = [r for r in FormReceiptLedger(MAIL_DB).list() if r["provider_message_id"] == PROVIDER_ID]
    if (len(receipts) != 1 or receipts[0]["test_only"] != 1
            or receipts[0]["canonical_id"] != LEAD_ID
            or receipts[0]["provider_match_status"] != "MATCHED_MISSING_EMAIL"):
        raise ValueError("Unique form notification to CRM match not proven")
    receipt = receipts[0]
    evidence = json.loads(receipt["evidence_json"])
    baseline = json.loads(BASELINE.read_text())
    lab = json.loads(LAB.read_text())
    if (lab["baseline_sha256"] != hashlib.sha256(BASELINE.read_bytes()).hexdigest()
            or LEAD_ID in baseline["modules"]["Leads"]["ids"]):
        raise ValueError("Protected CRM baseline conflicts with form Lead")
    client = client_from_service()
    lead = read_lead(client, LEAD_ID)
    created = datetime.fromisoformat(lead["Created_Time"])
    if (created.utcoffset() is None or abs((created - datetime.fromisoformat(receipt["occurred_at"])).total_seconds()) > 300
            or lead.get("Email") is not None or lead.get("Phone") != PHONE
            or lead.get("Company") != evidence["fields"]["company"]
            or lead.get("First_Name") != "Phase Nine" or lead.get("Last_Name") != "OPTIBRAIN TEST PHASE 9"
            or lead.get("OptiBrain_Test") is not False
            or find(client, "Leads", "Email", EMAIL) or find(client, "Contacts", "Email", EMAIL)):
        raise ValueError("Form-created Lead or unique identity changed; stop")
    crm_touch = datetime.fromisoformat(receipt["occurred_at"]).isoformat(timespec="seconds")
    data = {"id": LEAD_ID, "Email": EMAIL, "Normalized_Email": EMAIL,
            "OptiBrain_Test": True,
            "Description": MARKER + "\n" + evidence["fields"].get("notes", ""),
            "Ingestion_Source": "zoho_form", "First_Source": "zoho_form", "Last_Source": "zoho_form",
            "First_Touch_Time": crm_touch, "Last_Touch_Time": crm_touch,
            "Inquiry_ID": receipt["event_id"], "Source_Record_ID": PROVIDER_ID,
            "Lead_Status": "Not Contacted"}
    body = {"data": [data], "trigger": [], "skip_feature_execution": [{"name": "cadences"}]}
    headers = {"If-Unmodified-Since": lead["Modified_Time"]}
    atomic(JOURNAL, {"state": "attempted", "event_id": receipt["event_id"], "lead_id": LEAD_ID,
                     "payload_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                     "attempted_at": datetime.now(timezone.utc).isoformat()})
    if LEAD_ID not in lab["records"]["Leads"]:
        lab["records"]["Leads"].append(LEAD_ID)
        atomic(LAB, lab)
    with reviewed_test_lab_call(client, "PUT", f"/crm/v8/Leads/{LEAD_ID}", body, headers):
        answer = client.request("zohoapis", "PUT", f"/crm/v8/Leads/{LEAD_ID}", body=body,
                                headers=headers, reason="Repair exact form-created TEST_ONLY Lead mapping",
                                confirm=True)
    results = (answer.get("data") or {}).get("data") or []
    if answer.get("ok") is not True or len(results) != 1 or results[0].get("status") != "success":
        raise ValueError("CRM mapping repair acknowledgement ambiguous; reconcile before retry")
    crm = read_lead(client, LEAD_ID)
    if (crm.get("OptiBrain_Test") is not True or crm.get("Email") != EMAIL
            or crm.get("Inquiry_ID") != receipt["event_id"] or crm.get("First_Source") != "zoho_form"
            or not str(crm.get("Description") or "").startswith(MARKER)):
        raise ValueError("Form TEST_ONLY Lead readback mismatch")
    atomic(PROJECTION, lab, mode=0o640, group=grp.getgrnam("opticable-workflow-api").gr_gid)
    FormReceiptLedger(MAIL_DB).link_test_lead(receipt["event_id"], crm, set(lab["records"]["Leads"]))
    intake = IntakeLedger(INTAKE_DB)
    result = intake.record({"source": "zoho_form", "source_detail": evidence["source_detail"],
                            "inquiry_id": receipt["event_id"], "occurred_at": receipt["occurred_at"],
                            "email": EMAIL, "request": evidence["fields"], "form_id": evidence["form_id"],
                            "attribution": {}, "crm_action": "form_created_test_lead_reconciled"}, crm)
    intake.feedback(kind="LEAD_CREATED", canonical_id=LEAD_ID, related_module="Leads",
                    related_id=LEAD_ID, occurred_at=crm["Created_Time"],
                    evidence={"form_receipt": receipt["event_id"], "lead_id": LEAD_ID})
    journal = json.loads(JOURNAL.read_text())
    journal.update(state="verified", intake_event_id=result["event_id"],
                   decision=result["decision"], crm_version=crm["Modified_Time"])
    atomic(JOURNAL, journal)
    print(json.dumps({"lead_id": LEAD_ID, "form_event_id": receipt["event_id"],
                      "intake_event_id": result["event_id"], "state": "verified"}))


if __name__ == "__main__":
    main()
