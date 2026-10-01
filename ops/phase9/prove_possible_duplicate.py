#!/usr/bin/env python3
"""One controlled public intake with shared phone and a different TEST_ONLY email."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
import httpx

from test_lab_intake import atomic, client_from_service, find, read_lead

JOURNAL = Path("/var/lib/optibrain/phase9/mission2/possible-duplicate.json")
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
OWNED = "5062683000007935001"
EMAIL = "hckyan97+obp9amb1@gmail.com"
PHONE = "5145550187"


def main():
    if os.geteuid() != 0 or JOURNAL.exists():
        raise ValueError("One-shot duplicate proof requires root and untouched journal")
    baseline = json.loads(BASELINE.read_text())
    lab = json.loads(LAB.read_text())
    if (lab["baseline_sha256"] != hashlib.sha256(BASELINE.read_bytes()).hexdigest()
            or OWNED in baseline["modules"]["Leads"]["ids"]
            or OWNED not in lab["records"]["Leads"]):
        raise ValueError("Controlled phone owner not registered TEST_ONLY")
    client = client_from_service()
    if find(client, "Leads", "Email", EMAIL) or find(client, "Contacts", "Email", EMAIL):
        raise ValueError("Ambiguous alias already has a CRM identity")
    search = client.request("zohoapis", "GET", "/crm/v8/Leads/search", query={"phone": PHONE})
    if search.get("ok") is not True or {str(x.get("id")) for x in ((search.get("data") or {}).get("data") or [])} != {OWNED}:
        raise ValueError("Phone index does not uniquely target owned Test Lab Lead")
    before = read_lead(client, OWNED)
    if before.get("OptiBrain_Test") is not True or before.get("Phone") != PHONE or not before.get("Email"):
        raise ValueError("Controlled phone identity changed")
    inquiry = str(uuid4())
    body = {"name": "OPTIBRAIN TEST — PHASE 9 — Ambiguous Phone",
            "company": "OPTIBRAIN TEST — PHASE 9 — Form Warehouse", "email": EMAIL,
            "phone": PHONE, "city": "Montreal", "website": "", "consent": True,
            "language": "en", "page_path": "/fr/evaluation/",
            "message": "OPTIBRAIN TEST — PHASE 9. Different controlled email shares a test phone; human duplicate review required.",
            "source_record_id": "phase9-ambiguous-" + inquiry, "inquiry_id": inquiry,
            "attribution": {"last_source": "phase9_duplicate_test", "last_campaign": "opticable_phase9_ambiguous_test",
                            "last_landing_url": "https://ai.opticable.ca/fr/evaluation/",
                            "last_touch_time": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    atomic(JOURNAL, {"state": "attempted", "inquiry_id": inquiry, "email": EMAIL,
                     "candidate_id": OWNED, "candidate_version_before": before["Modified_Time"],
                     "payload_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                     "attempted_at": datetime.now(timezone.utc).isoformat()})
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        response = http.post("https://connect.opticable.ca/public/lead", json=body,
                             headers={"Origin": "https://ai.opticable.ca", "Content-Type": "application/json"})
    journal = json.loads(JOURNAL.read_text())
    journal.update(http_status=response.status_code, response=response.text[:1000])
    atomic(JOURNAL, journal)
    if (response.status_code != 202 or response.json().get("action") != "possible_duplicate"
            or response.json().get("review_required") is not True):
        raise ValueError("Possible duplicate outcome ambiguous; reconcile, do not retry")
    after = read_lead(client, OWNED)
    if (after["Modified_Time"] != before["Modified_Time"] or after.get("Email") != before.get("Email")
            or find(client, "Leads", "Email", EMAIL)):
        raise ValueError("Possible duplicate caused unintended CRM mutation")
    journal.update(state="verified", candidate_version_after=after["Modified_Time"],
                   auto_merged=False, crm_write=False)
    atomic(JOURNAL, journal)
    print(json.dumps({"state": "verified", "inquiry_id": inquiry, "action": "possible_duplicate",
                      "candidate_id": OWNED, "auto_merged": False, "crm_write": False}))


if __name__ == "__main__":
    main()
