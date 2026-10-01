"""Root-only, exact-call CRM write grant for records created in the Phase 8 Test Lab.

The protected snapshot is taken before the first write. Every update or relationship
target must be absent from that snapshot and present in the durable lab registry.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from .crm_write_boundary import _AUTHORITY, fingerprint

POLICY = "phase8-protected-test-lab-v1"
ROOT = Path("/var/lib/optibrain/phase8/test-lab")
BASELINE = ROOT / "PROTECTED_PREEXISTING_RECORDS.json"
REGISTRY = ROOT / "registry.json"
SERVICE_BASELINE = Path("/var/lib/optibrain/phase10/service-protected-baseline.json")
SERVICE_MODULES = frozenset({"Services", "Service_Locations", "Installations"})
MODULES = frozenset({"Leads", "Contacts", "Accounts", "Deals", "Tasks", "Events", "Calls", "Notes"}) | SERVICE_MODULES
MARKER = "OPTIBRAIN TEST — PHASE "


def _read(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _identity(value):
    return bool(re.fullmatch(r"[0-9]{1,30}", str(value or "")))


def validate_lab_request(method, path, body, headers):
    """Return module and target. Fail closed for every unregistered record reference."""
    if os.geteuid() != 0 or os.environ.get("OPTIBRAIN_PHASE8_TEST_LAB") != POLICY:
        raise ValueError("Test Lab CRM authority is disabled")
    baseline = _read(BASELINE)
    registry = _read(REGISTRY)
    if baseline.get("schema") != 1 or registry.get("schema") != 1:
        raise ValueError("Test Lab registry or baseline invalid")
    if registry.get("baseline_sha256") != hashlib.sha256(BASELINE.read_bytes()).hexdigest():
        raise ValueError("Protected baseline changed")
    service_baseline = _read(SERVICE_BASELINE)
    if (service_baseline.get("schema") != 1
            or set(service_baseline.get("modules") or {}) != SERVICE_MODULES
            or registry.get("service_baseline_sha256") != hashlib.sha256(SERVICE_BASELINE.read_bytes()).hexdigest()):
        raise ValueError("Protected service baseline changed")
    if method == "POST" and path == "/crm/v8/settings/fields":
        if headers or not isinstance(body, dict) or set(body) != {"fields"}:
            raise ValueError("Schema create envelope invalid")
        fields = body["fields"]
        expected = {"OptiBrain Test": "boolean", "Scope": "text",
                    "Project Timeline": "text"}
        if (not isinstance(fields, list) or not 1 <= len(fields) <= 3
                or any(not isinstance(field, dict) or set(field) != {"field_label", "data_type"}
                       or expected.get(field["field_label"]) != field["data_type"] for field in fields)
                or len({field["field_label"] for field in fields}) != len(fields)):
            raise ValueError("Schema create is outside reviewed Test Lab fields")
        return "Leads", None
    match = re.fullmatch(r"/crm/v8/(Leads|Contacts|Accounts|Deals|Tasks|Events|Calls|Notes|Services|Service_Locations|Installations)(?:/([0-9]{1,30}))?", path)
    if not match:
        raise ValueError("Test Lab only permits named CRM record modules")
    module, target = match.groups()
    if module in SERVICE_MODULES:
        ids = service_baseline["modules"].get(module)
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            raise ValueError(f"Protected {module} baseline incomplete")
        protected = set(ids)
    else:
        inventory = baseline["modules"].get(module)
        if not inventory or inventory.get("status") != "complete":
            raise ValueError(f"Protected {module} baseline incomplete")
        protected = set(inventory["ids"])
    owned = set((registry.get("records") or {}).get(module) or [])
    if protected & owned:
        raise ValueError("Protected and Test Lab IDs overlap")
    if headers and set(headers) != {"If-Unmodified-Since"}:
        raise ValueError("Unexpected CRM headers")
    if method == "POST" and target is None:
        if headers:
            raise ValueError("Create must not carry a version header")
    elif method == "PUT" and target is not None:
        if target in protected or target not in owned:
            raise ValueError("Target is protected or not registered as Test Lab owned")
        version = (headers or {}).get("If-Unmodified-Since")
        if not version or datetime.fromisoformat(version.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("Test Lab update requires a timezone-aware source version")
    else:
        raise ValueError("Test Lab permits single-record create or update only")
    if not isinstance(body, dict) or body.get("trigger") != [] or len(body.get("data") or []) != 1:
        raise ValueError("Test Lab requires one trigger-free record")
    if set(body) - {"data", "trigger", "skip_feature_execution"}:
        raise ValueError("Unexpected CRM envelope")
    if body.get("skip_feature_execution", [{"name": "cadences"}]) != [{"name": "cadences"}]:
        raise ValueError("CRM cadences must remain disabled")
    row = body["data"][0]
    if not isinstance(row, dict) or not row:
        raise ValueError("Test Lab record is empty")
    if method == "POST":
        if module not in SERVICE_MODULES and not str(row.get("Description") or "").startswith(MARKER):
            raise ValueError("Test Lab create requires Description marker")
        if module in SERVICE_MODULES and (row.get("OptiBrain_Test") is not True
                                         or not str(row.get("Name") or "").startswith(MARKER)):
            raise ValueError("Test Lab service create requires visible name and test flag")
        if module == "Services" and not isinstance(row.get("Linked_Service_Location"), dict):
            raise ValueError("Test Lab Service requires an owned Service Location")
        if module == "Service_Locations" and not isinstance(row.get("Linked_Account"), dict):
            raise ValueError("Test Lab Service Location requires an owned Account")
        if module in {"Leads", "Contacts", "Accounts", "Deals"} and not any(
                MARKER in str(row.get(field) or "") for field in ("Last_Name", "Account_Name", "Deal_Name", "Company")):
            raise ValueError("Test Lab create requires visible name marker")
    elif row.get("id") != target:
        raise ValueError("Test Lab update ID mismatch")
    if row.get("OptiBrain_Test") is False or row.get("Description") is not None and not str(row["Description"]).startswith(MARKER):
        raise ValueError("Test Lab marker cannot be removed")
    if "Email" in row and row["Email"]:
        address = str(row["Email"]).casefold()
        if not (address.endswith("@optibrain.invalid")
                or re.fullmatch(r"hckyan97\+obp9[a-z0-9]+@gmail\.com", address)
                or address in {"hckyan97+obp8wait@gmail.com", "info@opticable.ca"}):
            raise ValueError("Test Lab email is not synthetic or verified operator-controlled")
    if module == "Tasks" and not str(row.get("Subject") or "").startswith(MARKER) and method == "POST":
        raise ValueError("Test Lab Task subject needs visible marker")
    for field, related_module in (("What_Id", "Leads"), ("Account_Name", "Accounts"),
                                  ("Contact_Name", "Contacts"),
                                  ("Linked_Account", "Accounts"),
                                  ("Primary_Contact", "Contacts"),
                                  ("Linked_Deal", "Deals"),
                                  ("Linked_Service_Location", "Service_Locations"),
                                  ("Linked_Service", "Services")):
        value = row.get(field)
        if not isinstance(value, dict):
            continue
        related_id = str(value.get("id") or "")
        related_protected = (set(service_baseline["modules"][related_module]) if related_module in SERVICE_MODULES
                             else set(baseline["modules"][related_module]["ids"]))
        if not _identity(related_id) or related_id in related_protected or related_id not in set((registry.get("records") or {}).get(related_module) or []):
            raise ValueError(f"{field} points outside Test Lab")
    if module == "Tasks" and method == "POST":
        if row.get("$se_module") != "Leads" or not isinstance(row.get("What_Id"), dict):
            raise ValueError("Test Lab Task must attach to an owned Lead")
    return module, target


@contextmanager
def reviewed_test_lab_call(client, method, path, body, headers=None):
    validate_lab_request(method, path, body, headers)
    if _AUTHORITY.get() is not None:
        raise ValueError("Nested CRM authority forbidden")
    value = {"client": client, "hash": fingerprint(method, path, body, headers),
             "policy": POLICY, "used": False}
    token = _AUTHORITY.set(value)
    try:
        yield
    finally:
        _AUTHORITY.reset(token)
