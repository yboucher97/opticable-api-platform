#!/usr/bin/env python3
"""One-shot actual AI public intake returning to the verified main-form Test Lead."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import httpx

from test_lab_intake import atomic, client_from_service, find, read_lead

STATE = Path("/var/lib/optibrain/phase9/mission2/form-cross-source-return.json")
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
LEAD_ID = "5062683000007935001"
EMAIL = "hckyan97+obp9form1@gmail.com"
ORIGIN = "https://ai.opticable.ca"
CAMPAIGN = "opticable_phase9_form_to_ai_test"


def main():
    if os.geteuid() != 0 or STATE.exists():
        raise ValueError("One-shot cross-source return requires root and untouched journal")
    baseline = json.loads(BASELINE.read_text())
    lab = json.loads(LAB.read_text())
    if (lab["baseline_sha256"] != hashlib.sha256(BASELINE.read_bytes()).hexdigest()
            or LEAD_ID in baseline["modules"]["Leads"]["ids"]
            or LEAD_ID not in lab["records"]["Leads"]):
        raise ValueError("Controlled Lead ownership not proven")
    client = client_from_service()
    if ({str(row["id"]) for row in find(client, "Leads", "Email", EMAIL)} != {LEAD_ID}
            or find(client, "Contacts", "Email", EMAIL)):
        raise ValueError("Controlled identity is no longer unique")
    before = read_lead(client, LEAD_ID)
    if (before.get("OptiBrain_Test") is not True or before.get("Email") != EMAIL
            or before.get("First_Source") != "zoho_form"
            or not str(before.get("Description") or "").startswith("OPTIBRAIN TEST — PHASE 9")):
        raise ValueError("Form Test Lead changed")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inquiry = str(uuid4())
    body = {"name": "Phase Nine OPTIBRAIN TEST PHASE 9",
            "company": "OPTIBRAIN TEST — PHASE 9 — Form Warehouse", "email": EMAIL,
            "phone": "5145550187", "city": "Montreal", "website": "", "consent": True,
            "language": "en", "page_path": "/fr/evaluation/",
            "message": "OPTIBRAIN TEST — PHASE 9. Returning from the AI evaluation for the same synthetic warehouse camera project.",
            "source_record_id": "phase9-form-return-" + inquiry, "inquiry_id": inquiry,
            "attribution": {"first_source": "zoho_form", "first_site": "https://opticable.ca",
                            "first_touch_time": before["First_Touch_Time"],
                            "last_source": "phase9_ai_return_test", "last_medium": "referral",
                            "last_campaign": CAMPAIGN, "last_content": "form_to_ai",
                            "last_landing_url": "https://ai.opticable.ca/fr/evaluation/",
                            "last_site": ORIGIN, "last_touch_time": now}}
    atomic(STATE, {"state": "attempted", "inquiry_id": inquiry, "email": EMAIL,
                   "lead_id": LEAD_ID, "payload_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                   "attempted_at": now})
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        answer = http.post("https://connect.opticable.ca/public/lead", json=body,
                           headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    state = json.loads(STATE.read_text())
    state.update(http_status=answer.status_code, response=answer.text[:1000])
    atomic(STATE, state)
    matches = find(client, "Leads", "Inquiry_ID", inquiry)
    if (answer.status_code != 200 or answer.json().get("action") != "updated_lead"
            or {str(row["id"]) for row in matches} != {LEAD_ID}):
        raise ValueError("Cross-source return requires reconciliation; never retry blindly")
    after = read_lead(client, LEAD_ID)
    if (after.get("First_Source") != "zoho_form" or after.get("Last_Source") != "phase9_ai_return_test"
            or after.get("Ingestion_Source") != "ai_website"
            or after.get("Last_Campaign") != CAMPAIGN or after.get("OptiBrain_Test") is not True):
        raise ValueError("First/latest attribution or TEST_ONLY marker changed")
    state.update(state="verified", first_source=after["First_Source"],
                 latest_source=after["Last_Source"], crm_version=after["Modified_Time"])
    atomic(STATE, state)
    print(json.dumps({"lead_id": LEAD_ID, "inquiry_id": inquiry, "action": "updated_lead",
                      "first_source": after["First_Source"], "latest_source": after["Last_Source"]}))


if __name__ == "__main__":
    main()
