#!/usr/bin/env python3
"""Human-invoked, journal-before-send Phase 9 public intake proof.

Only the preflighted operator-controlled alias may be used. An attempted request
is never retried by this tool; reconcile Inquiry_ID in CRM before any new action.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

import httpx

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
ROOT = Path("/var/lib/optibrain/phase9/test-lab")
REGISTRY = ROOT / "registry.json"
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
PROJECTION = Path("/etc/optibrain/phase8-test-lab-registry.json")
EMAIL = "hckyan97+obp9intake1@gmail.com"
MARKER = "OPTIBRAIN TEST — PHASE 9"
SCENARIOS = {"new_ai": ("https://ai.opticable.ca", "ai_website"),
             "return_ai": ("https://ai.opticable.ca", "ai_website"),
             "cross_main": ("https://opticable.ca", "opticable_website")}


def atomic(path, value, *, mode=0o600, group=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if group is not None:
        os.chown(temp, 0, group)
    os.chmod(temp, mode)
    os.replace(temp, path)


def load(path):
    return json.loads(path.read_text())


def client_from_service():
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


def rows(response):
    if response.get("ok") is True and response.get("status") == 204:
        return []
    data = (response.get("data") or {}).get("data")
    if response.get("ok") is not True or not isinstance(data, list):
        raise ValueError("Provider search/read ambiguous; stop")
    return data


def find(client, module, field, value):
    # Zoho Search is eventually consistent after a successful create/update.
    # A complete bounded list is the independent reconciliation source.
    names = {"Leads": "id,Email,Inquiry_ID", "Contacts": "id,Email,Inquiry_ID",
             "Deals": "id,Inquiry_ID"}
    if module not in names or field not in {"Email", "Inquiry_ID"}:
        raise ValueError("Unsupported bounded CRM identity lookup")
    response = client.request("zohoapis", "GET", f"/crm/v8/{module}",
                              query={"fields": names[module], "per_page": 100, "page": 1})
    found = rows(response)
    if ((response.get("data") or {}).get("info") or {}).get("more_records"):
        raise ValueError("CRM identity list exceeds bounded safety check")
    return [row for row in found if str(row.get(field) or "").casefold() == str(value).casefold()]


def read_lead(client, lead_id):
    found = rows(client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}"))
    if len(found) != 1 or str(found[0].get("id")) != str(lead_id):
        raise ValueError("Exact Lead readback unavailable")
    return found[0]


def protect(client, state, scenario):
    baseline = load(BASELINE)
    lab = load(LAB)
    if lab.get("baseline_sha256") != hashlib.sha256(BASELINE.read_bytes()).hexdigest():
        raise ValueError("Protected CRM baseline changed")
    expected = state.get("lead_id") if scenario != "new_ai" else None
    email_matches = find(client, "Leads", "Email", EMAIL)
    contact_matches = find(client, "Contacts", "Email", EMAIL)
    if contact_matches or len(email_matches) != (1 if expected else 0):
        raise ValueError("Controlled alias collides with Lead/Contact identity")
    if email_matches and (str(email_matches[0]["id"]) != expected
                          or expected not in lab["records"]["Leads"]):
        raise ValueError("Identity not registered Test Lab owned")
    if email_matches and str(email_matches[0]["id"]) in baseline["modules"]["Leads"]["ids"]:
        raise ValueError("Protected Lead collision")
    if expected:
        indexed = rows(client.request("zohoapis", "GET", "/crm/v8/Leads/search",
                                      query={"email": EMAIL}))
        if {str(row.get("id")) for row in indexed} != {expected}:
            raise ValueError("Provider search index has not converged; do not risk duplicate Lead")
    return expected


def request_for(state, scenario):
    origin, source = SCENARIOS[scenario]
    now = datetime.now(timezone.utc).isoformat()
    inquiry = str(uuid4())
    message = {"new_ai": "OPTIBRAIN TEST — PHASE 9. Synthetic warehouse cameras inquiry: 12 cameras in a Montreal test site, installation in three weeks.",
               "return_ai": "OPTIBRAIN TEST — PHASE 9. Returning synthetic inquiry: please include access control at the same test warehouse.",
               "cross_main": "OPTIBRAIN TEST — PHASE 9. Returning via main-origin connector with synthetic structured cabling scope."}[scenario]
    traffic_source = "phase9_test" if scenario != "cross_main" else "phase9_return_test"
    attribution = {"first_source": traffic_source, "first_medium": "cpc" if scenario == "new_ai" else "referral",
                   "first_campaign": "opticable_phase9_test", "first_landing_url": origin + "/fr/contact/",
                   "first_site": origin, "first_touch_time": now,
                   "last_source": traffic_source, "last_medium": "cpc" if scenario == "new_ai" else "referral",
                   "last_campaign": "opticable_phase9_test" if scenario != "cross_main" else "opticable_phase9_return_test",
                   "last_content": scenario, "last_term": "test_only", "last_landing_url": origin + "/fr/contact/",
                   "last_site": origin, "last_touch_time": now}
    body = {"name": MARKER + " — Intake One", "company": MARKER + " — Warehouse Lab",
            "email": EMAIL, "phone": "", "city": "Montreal", "message": message,
            "website": "", "language": "en", "page_path": "/fr/evaluation" if scenario != "cross_main" else "/fr/contact/",
            "source_record_id": "phase9-" + scenario + "-" + str(uuid4()),
            "inquiry_id": inquiry, "consent": True, "attribution": attribution}
    return {"origin": origin, "source": source, "occurred_at": now, "request": body,
            "email": EMAIL, "inquiry_id": inquiry, "attribution": attribution,
            "source_detail": "public connector Origin " + origin,
            "form_id": "ai-evaluation" if scenario != "cross_main" else "main-origin-api"}


def mark_new(client, lead_id):
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    lab = load(LAB)
    baseline = load(BASELINE)
    if lead_id in baseline["modules"]["Leads"]["ids"]:
        raise ValueError("New Lead is protected; stop")
    if lead_id not in lab["records"]["Leads"]:
        lab["records"]["Leads"].append(lead_id)
        atomic(LAB, lab)
    lead = read_lead(client, lead_id)
    if lead.get("OptiBrain_Test") is True and str(lead.get("Description") or "").startswith(MARKER):
        return lead
    if str(lead.get("Email") or "").casefold() != EMAIL or not str(lead.get("Company") or "").startswith(MARKER):
        raise ValueError("Unmarked Lead identity is not the controlled Test Lab alias")
    body = {"data": [{"id": lead_id, "Description": MARKER + "\n" + str(lead.get("Description") or ""),
                       "OptiBrain_Test": True}], "trigger": [],
            "skip_feature_execution": [{"name": "cadences"}]}
    headers = {"If-Unmodified-Since": lead["Modified_Time"]}
    with reviewed_test_lab_call(client, "PUT", f"/crm/v8/Leads/{lead_id}", body, headers):
        answer = client.request("zohoapis", "PUT", f"/crm/v8/Leads/{lead_id}", body=body,
                                headers=headers, reason="Mark newly created Phase 9 Lead TEST_ONLY", confirm=True)
    if answer.get("ok") is not True:
        raise ValueError("TEST_ONLY marker update unconfirmed; reconcile, never retry blindly")
    lead = read_lead(client, lead_id)
    if lead.get("OptiBrain_Test") is not True or not str(lead.get("Description") or "").startswith(MARKER):
        raise ValueError("TEST_ONLY marker readback mismatch")
    atomic(PROJECTION, lab, mode=0o640, group=__import__("grp").getgrnam("opticable-workflow-api").gr_gid)
    return lead


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in {*SCENARIOS, "replay_new_ai"}:
        raise SystemExit("Run as root with one scenario: new_ai, replay_new_ai, return_ai, cross_main")
    scenario = sys.argv[1]
    client = client_from_service()
    ROOT.mkdir(parents=True, exist_ok=True)
    state = load(REGISTRY) if REGISTRY.exists() else {"schema": 1, "email": EMAIL, "events": {},
                                                       "lead_id": None, "baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest()}
    if state["email"] != EMAIL or state["baseline_sha256"] != hashlib.sha256(BASELINE.read_bytes()).hexdigest():
        raise ValueError("Test Lab identity or baseline changed")
    if scenario == "replay_new_ai":
        original = state["events"].get("new_ai")
        if not original or original.get("state") != "verified" or scenario in state["events"]:
            raise ValueError("Replay needs verified original and no prior attempt")
        receipt = original["receipt"]
        expected = protect(client, state, "return_ai")
        if expected != state["lead_id"]:
            raise ValueError("Replay Lead identity changed")
    else:
        if scenario != "new_ai" and not state.get("lead_id"):
            raise ValueError("Create controlled Lead first")
        if scenario in state["events"]:
            raise ValueError("Attempt already journaled; reconcile, do not retry")
        expected = protect(client, state, scenario)
        receipt = request_for(state, scenario)
        if find(client, "Leads", "Inquiry_ID", receipt["inquiry_id"]):
            raise ValueError("Inquiry ID already exists")
    state["events"][scenario] = {"state": "attempted", "receipt": receipt,
                                  "request_hash": hashlib.sha256(json.dumps(receipt["request"], sort_keys=True).encode()).hexdigest()}
    atomic(REGISTRY, state)
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        response = http.post("https://connect.opticable.ca/public/lead", json=receipt["request"],
                             headers={"Origin": receipt["origin"], "Content-Type": "application/json"})
    state["events"][scenario]["http_status"] = response.status_code
    state["events"][scenario]["public_response"] = response.text[:2000]
    atomic(REGISTRY, state)
    candidates = find(client, "Leads", "Inquiry_ID", receipt["inquiry_id"])
    if len(candidates) != 1:
        raise ValueError("Public outcome ambiguous; reconcile inquiry ID before another request")
    lead_id = str(candidates[0]["id"])
    if response.status_code != 200 or response.json().get("accepted") is not True or (expected and lead_id != expected):
        raise ValueError("Public response/readback mismatch; stop")
    if scenario == "new_ai":
        state["lead_id"] = lead_id
        atomic(REGISTRY, state)
        crm = mark_new(client, lead_id)
    else:
        crm = read_lead(client, lead_id)
        if crm.get("OptiBrain_Test") is not True or not str(crm.get("Description") or "").startswith(MARKER):
            raise ValueError("Returning Lead lost TEST_ONLY marker")
    sys.path.insert(0, str(APP))
    from workflow.automation.phase9_intake import IntakeLedger
    ledger = IntakeLedger(Path("/var/lib/opticable-workflow-api/output/automation/phase9-intake.db"))
    result = ledger.record({**receipt, "crm_action": response.json().get("action")}, crm)
    if scenario == "new_ai":
        ledger.feedback(kind="LEAD_CREATED", canonical_id=lead_id, related_module="Leads",
                        related_id=lead_id, occurred_at=crm["Created_Time"],
                        evidence={"lead_id": lead_id, "inquiry_id": receipt["inquiry_id"]})
    state["events"][scenario].update(state="verified", event_id=result["event_id"],
                                      decision=result["decision"], lead_id=lead_id,
                                      crm_version=crm["Modified_Time"])
    atomic(REGISTRY, state)
    print(json.dumps({"scenario": scenario, "lead_id": lead_id, "event_id": result["event_id"],
                      "decision": result["decision"], "action": response.json().get("action")}, sort_keys=True))


if __name__ == "__main__":
    main()
