"""Bounded, GET-only CRM metadata snapshots. Never persist raw provider dumps."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .event_schema import digest
from .events import redact

MODULES = ("Leads", "Contacts", "Accounts", "Deals", "Buildings", "Service_Locations",
           "Installations", "Services", "Installation_X_Services", "Accounts_X_Buildings",
           "Contacts_X_Buildings", "Tasks", "CustomModule5001", "CustomModule5002",
           "CustomModule5003", "CustomModule5004")
VOLATILE = {"created_time", "modified_time", "created_by", "modified_by", "last_executed_time"}
SENSITIVE = re.compile(r"(?i)(token|secret|password|credential|authorization|cookie|url|uri|"
                       r"^headers$|^parameters$|^params$|^script$|^source_code$|^body$|(?:api|private|client)[_-]?key)")
FIELD_KEYS = ("id", "api_name", "field_label", "data_type", "length", "decimal_place", "required",
              "system_mandatory", "unique", "custom_field", "pick_list_values", "lookup",
              "multiselectlookup", "global_picklist", "auto_number", "convert_mapping", "validation_rule")


def normalize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 24:
        raise ValueError("metadata nesting bound")
    # Valid environment-variable names are references, never credential values.
    if key.endswith("_env") and isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", value):
        return value
    if value is not None and SENSITIVE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: normalize(v, key=k, depth=depth + 1) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        # Only ID/API-identified collections are unordered. Criteria groups,
        # sections and picklists retain their operational sequence.
        result = [normalize(v, depth=depth + 1) for v in value]
        if key in {"modules", "fields", "layouts", "workflow_rules", "webhooks", "tasks", "functions",
                   "related_lists", "global_picklists", "assignment_rules", "scoring_rules", "validation_rules"}:
            result.sort(key=lambda x: str(x.get("id", x.get("api_name", ""))) if isinstance(x, dict) else str(x))
        return result
    if isinstance(value, str):
        return re.sub(r"https?://[^\s\"<>]+", "[REDACTED_URL]", redact(value))
    return value


def project(data: dict, kind: str) -> dict:
    """Retain configuration topology; avoid redundant per-layout field dumps."""
    data = normalize(data)
    if kind == "fields":
        return {"fields": [{k: f[k] for k in FIELD_KEYS if k in f} for f in data.get("fields", [])]}
    if kind == "layouts":
        for layout in data.get("layouts", []):
            for section in layout.get("sections", []):
                section["fields"] = [{k: f[k] for k in FIELD_KEYS if k in f} for f in section.get("fields", [])]
    if kind == "functions":
        return {"functions": [{k: f[k] for k in ("id", "name", "api_name", "category", "language", "state", "arguments")
                               if k in f} for f in data.get("functions", [])]}
    return data


def entry(response: dict, kind: str) -> dict:
    status = response.get("status")
    data = response.get("data")
    if status == 204 and response.get("ok") is True:
        return {"status": "empty", "http_status": 204, "data": {kind: []}}
    if response.get("ok") is not True or status != 200 or not isinstance(data, dict):
        return {"status": "unavailable", "http_status": status, "error": str((data or {}).get("code", "read_failed"))
                if isinstance(data, dict) else "read_failed"}
    more = (data.get("info") or {}).get("more_records", False)
    return {"status": "incomplete" if more else "complete", "http_status": status,
            "data": project(data, kind)}


def snapshot(entries: dict[str, dict]) -> dict:
    content = {k: v for k, v in sorted(entries.items())}
    return {"api_version": "opticable.io/crm-inventory-v1", "provider": "zoho_crm",
            "captured_at": datetime.now(timezone.utc).isoformat(), "entries": content,
            "content_hash": digest(content), "complete": all(v["status"] in {"complete", "empty"} for v in content.values())}


def drift(before: dict, after: dict) -> dict:
    if before.get("api_version") != after.get("api_version"):
        raise ValueError("inventory format mismatch")
    old, new = before["entries"], after["entries"]
    changes = [{"entry": k, "before_hash": digest(old.get(k)), "after_hash": digest(new.get(k)),
                "status": new.get(k, {}).get("status", "missing")} for k in sorted(set(old) | set(new))
               if digest(old.get(k)) != digest(new.get(k))]
    return {"before_hash": before["content_hash"], "after_hash": after["content_hash"], "changes": changes,
            "unknown": [k for k, v in new.items() if v["status"] not in {"complete", "empty"}]}


class CrmInventoryCollector:
    def __init__(self, client, *, max_calls: int = 120):
        if not 1 <= max_calls <= 200:
            raise ValueError("inventory call bound")
        self.client, self.max_calls, self.calls = client, max_calls, 0

    def read(self, path: str, query: dict | None = None) -> dict:
        self.calls += 1
        if self.calls > self.max_calls:
            raise ValueError("inventory call budget exhausted")
        try:
            return self.client.request("zohoapis", "GET", path, query=query or {})
        except Exception as exc:
            return {"ok": False, "status": getattr(getattr(exc, "response", None), "status_code", None),
                    "data": {"code": type(exc).__name__}}

    def collect(self, modules: tuple[str, ...] = MODULES) -> dict:
        if len(modules) > 20 or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", m) for m in modules):
            raise ValueError("inventory module bound")
        entries = {"modules": entry(self.read("/crm/v8/settings/modules"), "modules")}
        for module in modules:
            for kind in ("fields", "layouts", "related_lists"):
                entries[f"{kind}:{module}"] = entry(self.read(f"/crm/v8/settings/{kind}", {"module": module}), kind)
            for kind, path in (("assignment_rules", "automation/assignment_rules"),
                               ("validation_rules", "validation_rules"), ("cadences", "automation/cadences")):
                entries[f"{kind}:{module}"] = entry(self.read(f"/crm/v8/settings/{path}", {"module": module}), kind)
        for kind, path in (("workflow_rules", "automation/workflow_rules"), ("webhooks", "automation/webhooks"),
                           ("tasks", "automation/tasks"), ("field_updates", "automation/field_updates"),
                           ("email_notifications", "automation/email_notifications"),
                           ("scoring_rules", "automation/scoring_rules"), ("global_picklists", "global_picklists"),
                           ("functions", "functions"), ("custom_buttons", "custom_buttons")):
            entries[kind] = entry(self.read(f"/crm/v8/settings/{path}"), kind)
        for rule in entries["workflow_rules"].get("data", {}).get("workflow_rules", [])[:20]:
            entries["workflow:" + rule["id"]] = entry(self.read("/crm/v8/settings/automation/workflow_rules/" + rule["id"]), "workflow_rules")
        for picklist in entries["global_picklists"].get("data", {}).get("global_picklists", [])[:8]:
            entries["global_picklist:" + picklist["id"]] = entry(self.read("/crm/v8/settings/global_picklists/" + picklist["id"]), "global_picklists")
        # Lead conversion topology is supplied by layout/field convert_mapping.
        return snapshot(entries)
