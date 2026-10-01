#!/usr/bin/env python3
"""Manual, journal-before-transport Phase 10 CRM Test Lab proof.

Run seed, negative, restore as separate human-invoked operations. An attempted
provider call never retries automatically; reconcile its unique marker first.
"""
import grp
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
ROOT = Path("/var/lib/optibrain/phase10/test-lab")
STATE = ROOT / "registry.json"
LAB = Path("/var/lib/optibrain/phase8/test-lab/registry.json")
BASELINE = Path("/var/lib/optibrain/phase8/test-lab/PROTECTED_PREEXISTING_RECORDS.json")
PROJECTION = Path("/etc/optibrain/phase8-test-lab-registry.json")
MARKER = "OPTIBRAIN TEST — PHASE 10"

SCENARIOS = {
 "cabling_cross_sell": dict(service="Structured cabling", stage="Closed Won", installed="2026-05-01",
   last="2026-08-01", description="Completed office cabling. Customer mentioned planned wireless coverage for new floor."),
 "camera_maintenance": dict(service="Cameras", stage="Closed Won", installed="2025-11-01",
   last="2026-03-01", maintenance="2026-09-25", description="12-camera warehouse system; annual health check requested."),
 "recurring_service": dict(service="Managed Wi-Fi", stage="Closed Won", installed="2026-02-01",
   last="2026-09-20", recurrence="Monthly", renewal="2027-06-01",
   description="Managed office Wi-Fi service with monthly support review."),
 "renewal_due": dict(service="PTP link", stage="Closed Won", installed="2025-11-01",
   last="2026-08-01", recurrence="Annual", renewal="2027-01-01",
   description="Recurring point-to-point wireless link service."),
 "dormant": dict(service="Structured cabling", stage="Closed Won", installed="2023-01-01",
   last="2024-01-01", description="Completed cabling project; no later service engagement."),
 "camera_upsell": dict(service="Cameras", stage="Closed Won", installed="2026-05-01",
   last="2026-09-01", description="Installed cameras. New expansion wing has a coverage gap."),
 "no_action": dict(service="Access control", stage="Closed Won", installed="2026-08-01",
   last="2026-09-20", maintenance="2027-03-01",
   description="Access control commissioned and checked recently; no outstanding requests."),
}


def atomic(path, value, *, mode=0o600, gid=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if gid is not None:
        os.chown(tmp, 0, gid)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


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
    response = client.request("zohoapis", "GET", f"/crm/v8/{module}/{identity}")
    rows = (response.get("data") or {}).get("data") or []
    if response.get("ok") is not True or len(rows) != 1 or str(rows[0].get("id")) != identity:
        raise ValueError("Exact provider readback missing")
    return rows[0]


def matches(actual, row):
    if (actual.get("OptiBrain_Test") is not True
            or not str(actual.get("Description") or "").startswith("OPTIBRAIN TEST — PHASE ")):
        return False
    for field, expected in row.items():
        if field in {"Account_Name", "Contact_Name"} and isinstance(expected, dict):
            if str((actual.get(field) or {}).get("id")) != expected["id"]:
                return False
        elif field != "id" and actual.get(field) != expected:
            return False
    return True


def write(client, lab, state, key, module, row, *, identity=None):
    from workflow.automation.test_lab_boundary import reviewed_test_lab_call
    from workflow.automation.crm_write_boundary import fingerprint
    method = "PUT" if identity else "POST"
    path = f"/crm/v8/{module}" + (f"/{identity}" if identity else "")
    before = read(client, module, identity) if identity else None
    body = {"data": [{"id": identity, **row} if identity else row], "trigger": [],
            "skip_feature_execution": [{"name": "cadences"}]}
    headers = {"If-Unmodified-Since": before["Modified_Time"]} if before else None
    history = state.setdefault("operations", {})
    if key in history:
        if history[key].get("state") == "verified":
            actual = read(client, module, history[key]["id"])
            if not matches(actual, row):
                raise ValueError(f"{key} verified record drifted; review provider state")
            return actual
        prior = history[key]
        if prior.get("id") and prior.get("module") == module and prior.get("target") == identity:
            actual = read(client, module, prior["id"])
            if matches(actual, row):
                prior["state"] = "verified"
                prior["reconciled_by_readback"] = True
                atomic(STATE, state)
                return actual
        raise ValueError(f"{key} already attempted; reconcile before another provider call")
    history[key] = {"state": "attempted", "module": module, "target": identity,
                    "at_utc": datetime.now(timezone.utc).isoformat(),
                    "payload_hash": fingerprint(method, path, body, headers)}
    atomic(STATE, state)
    with reviewed_test_lab_call(client, method, path, body, headers):
        result = client.request("zohoapis", method, path, body=body, headers=headers,
                                reason="Phase 10 isolated TEST_ONLY lifecycle proof", confirm=True)
    rows = (result.get("data") or {}).get("data") or []
    got = str((rows[0].get("details") or {}).get("id") or "") if len(rows) == 1 else ""
    if result.get("ok") is not True or len(rows) != 1 or rows[0].get("status") != "success" or not got.isdigit():
        raise ValueError(f"{key} provider acknowledgement ambiguous; reconcile")
    if identity and got != identity:
        raise ValueError("Provider updated unexpected ID")
    history[key]["id"] = got
    atomic(STATE, state)
    if not identity:
        if got in set(load(BASELINE)["modules"][module]["ids"]):
            raise ValueError("Provider created protected ID")
        lab["records"][module].append(got)
        atomic(LAB, lab)
        atomic(PROJECTION, lab, mode=0o640,
               gid=grp.getgrnam("opticable-workflow-api").gr_gid)
    actual = read(client, module, got)
    if not matches(actual, row):
        raise ValueError(f"{key} provider readback differs from requested TEST_ONLY record")
    history[key]["state"] = "verified"
    atomic(STATE, state)
    return actual


def seed(client, lab, state):
    for name, facts in SCENARIOS.items():
        label = name.replace("_", " ").title()
        account = write(client, lab, state, name + ":account", "Accounts",
            {"Account_Name": f"{MARKER} — {label}", "OptiBrain_Test": True,
             "Description": MARKER + "\nSynthetic customer lifecycle account."})
        aid = str(account["id"])
        contact = write(client, lab, state, name + ":contact", "Contacts",
            {"First_Name": "Lifecycle", "Last_Name": f"{MARKER} — {label}",
             "Email": f"phase10{name}@optibrain.invalid", "Account_Name": {"id": aid},
             "OptiBrain_Test": True,
             "Description": MARKER + "\nSynthetic linked lifecycle contact."})
        deal = {"Deal_Name": f"{MARKER} — {label} Service", "Stage": facts["stage"],
                "Account_Name": {"id": aid}, "Contact_Name": {"id": str(contact["id"])},
                "Service_Types": facts["service"], "OptiBrain_Test": True,
                "Description": MARKER + "\n" + facts["description"],
                "OptiBrain_Installed_On": facts["installed"],
                "OptiBrain_Last_Service_On": facts["last"]}
        for key, field in (("maintenance", "OptiBrain_Maintenance_Due"),
                           ("renewal", "OptiBrain_Renewal_On"),
                           ("recurrence", "OptiBrain_Recurrence")):
            if facts.get(key): deal[field] = facts[key]
        record = write(client, lab, state, name + ":deal", "Deals", deal)
        state.setdefault("scenarios", {})[name] = {"account_id": aid,
            "contact_id": str(contact["id"]), "deal_id": str(record["id"])}
        atomic(STATE, state)
        print(name, aid, record["id"], flush=True)
    # Reuse the Phase 9 source-attributed Account, Contact and Deal.
    source = load(Path("/var/lib/optibrain/phase9/test-lab/registry.json"))
    outcome = source.get("outcome") or {}
    if not all((outcome.get(k) or {}).get("state") == "verified" for k in ("account", "contact", "deal")):
        raise ValueError("Phase 9 source relationship is not verified")
    deal_id = str(outcome["deal"]["id"])
    record = read(client, "Deals", deal_id)
    if record.get("OptiBrain_Test") is not True or deal_id not in lab["records"]["Deals"]:
        raise ValueError("Source-attributed Deal is not Test Lab owned")
    write(client, lab, state, "active_project:deal", "Deals",
          {"Stage": "Installation", "Service_Types": "Cameras"}, identity=deal_id)
    state["scenarios"]["active_project"] = {"account_id": str(outcome["account"]["id"]),
        "contact_id": str(outcome["contact"]["id"]), "deal_id": deal_id,
        "phase9_source_continuity": True}
    atomic(STATE, state)


def transition(client, lab, state, negative):
    changes = ({"dormant": ("OptiBrain_Last_Service_On", "2026-09-30"),
                "camera_maintenance": ("OptiBrain_Maintenance_Due", "2027-03-01"),
                "renewal_due": ("OptiBrain_Renewal_On", "2026-10-25")}
               if negative else
               {"dormant": ("OptiBrain_Last_Service_On", "2024-01-01"),
                "camera_maintenance": ("OptiBrain_Maintenance_Due", "2026-09-25")})
    for name, (field, value) in changes.items():
        deal_id = state["scenarios"][name]["deal_id"]
        write(client, lab, state, ("negative" if negative else "restore") + ":" + name,
              "Deals", {field: value}, identity=deal_id)
        print(name, field, value, flush=True)


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in {"seed", "negative", "restore"}:
        raise SystemExit("Root and one explicit seed/negative/restore operation required")
    baseline = load(BASELINE)
    lab = load(LAB)
    if lab.get("baseline_sha256") != hashlib.sha256(BASELINE.read_bytes()).hexdigest():
        raise ValueError("Protected baseline changed")
    if sum(len(x["ids"]) for x in baseline["modules"].values()) != 99:
        raise ValueError("Protected record count changed")
    ROOT.mkdir(parents=True, exist_ok=True)
    state = load(STATE) if STATE.exists() else {"schema": 1, "protected_baseline_sha256": lab["baseline_sha256"],
                                                "operations": {}, "scenarios": {}}
    if state["protected_baseline_sha256"] != lab["baseline_sha256"]:
        raise ValueError("Phase 10 Test Lab baseline changed")
    atomic(STATE, state)
    client = provider()
    if sys.argv[1] == "seed": seed(client, lab, state)
    elif sys.argv[1] == "negative": transition(client, lab, state, True)
    else: transition(client, lab, state, False)


if __name__ == "__main__":
    main()
