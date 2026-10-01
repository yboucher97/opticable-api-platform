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
MODULES = frozenset({"Leads", "Contacts", "Accounts", "Deals", "Tasks", "Events", "Calls", "Notes"})
MARKER = "OPTIBRAIN TEST — PHASE 8"


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
    match = re.fullmatch(r"/crm/v8/(Leads|Contacts|Accounts|Deals|Tasks|Events|Calls|Notes)(?:/([0-9]{1,30}))?", path)
    if not match:
        raise ValueError("Test Lab only permits named CRM record modules")
    module, target = match.groups()
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
        if not str(row.get("Description") or "").startswith(MARKER):
            raise ValueError("Test Lab create requires Description marker")
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
                or address in {"hckyan97+obp8wait@gmail.com", "info@opticable.ca"}):
            raise ValueError("Test Lab email is not synthetic or verified operator-controlled")
    if module == "Tasks" and not str(row.get("Subject") or "").startswith(MARKER) and method == "POST":
        raise ValueError("Test Lab Task subject needs visible marker")
    for field, related_module in (("What_Id", "Leads"), ("Account_Name", "Accounts"),
                                  ("Contact_Name", "Contacts")):
        value = row.get(field)
        if not isinstance(value, dict):
            continue
        related_id = str(value.get("id") or "")
        if not _identity(related_id) or related_id in set(baseline["modules"][related_module]["ids"]) or related_id not in set((registry.get("records") or {}).get(related_module) or []):
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
