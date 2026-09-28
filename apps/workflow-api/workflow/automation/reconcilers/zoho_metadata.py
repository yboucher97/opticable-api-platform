"""Conservative CRM adapters in the existing Desired State registry.

Unsupported write APIs are manual. Active business rules are always high risk.
Only explicitly managed resources are compared; omission never means deletion.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from ..crm_inventory import normalize
from ..desired_state import DesiredApplyResult, DesiredChange, DesiredResource

KINDS = {
    "layout": ("/crm/v8/settings/layouts", "layouts", False),
    "workflow": ("/crm/v8/settings/automation/workflow_rules", "workflow_rules", True),
    "webhook": ("/crm/v8/settings/automation/webhooks", "webhooks", True),
    "field_update": ("/crm/v8/settings/automation/field_updates", "field_updates", True),
    "assignment_rule": ("/crm/v8/settings/automation/assignment_rules", "assignment_rules", False),
    "scoring_rule": ("/crm/v8/settings/automation/scoring_rules", "scoring_rules", True),
    "validation_rule": ("/crm/v8/settings/validation_rules", "validation_rules", False),
}


def subset(current, desired):
    if isinstance(desired, dict) and isinstance(current, dict):
        return {k: subset(current.get(k), v) for k, v in desired.items()}
    if isinstance(desired, list) and isinstance(current, list):
        return [subset(c, d) for c, d in zip(current, desired)] if len(current) == len(desired) else current
    return current


class ZohoCrmMetadataReconciler:
    def __init__(self, client, kind: str):
        self.client, self.kind = client, kind
        self.path, self.collection, self.writable = KINDS[kind]
        self.name = "zoho_crm." + kind + ".v1"

    def read(self, resource):
        module = resource.identity.get("module") or resource.desired.get("module")
        if isinstance(module, dict):
            module = module.get("api_name")
        if module and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", module):
            raise ValueError("Unsafe module identity")
        identity = str(resource.identity.get("id") or "")
        if identity and not identity.isdigit():
            raise ValueError("Unsafe CRM resource id")
        response = self.client.request("zohoapis", "GET", self.path + ("/" + identity if identity else ""),
                                       query={"module": module} if module and self.kind in {"layout", "assignment_rule", "validation_rule"} else {})
        if response.get("ok") is True and response.get("status") == 204:
            if identity:
                raise ValueError("Pinned resource is unavailable")
            return None
        data = response.get("data") or {}
        rows = data.get(self.collection)
        if response.get("ok") is not True or response.get("status") != 200 or not isinstance(rows, list):
            raise ValueError("CRM metadata read failed closed")
        if len(rows) > 200 or (data.get("info") or {}).get("more_records"):
            raise ValueError("CRM metadata read incomplete")
        matches = [r for r in rows if str(r.get("id")) == identity] if identity else [r for r in rows if r.get("name") == resource.name]
        if len(matches) > 1 or (identity and not matches):
            raise ValueError("CRM identity cannot be resolved uniquely")
        return normalize(matches[0]) if matches else None

    def plan(self, resource: DesiredResource):
        current = self.read(resource)
        desired = resource.desired
        action, reason, risk = "noop", "Managed CRM configuration matches", "low"
        if resource.lifecycle.get("ensure", "present") != "present":
            action, reason, risk = "blocked", "Metadata deletion is disabled; preserve existing configuration", "destructive"
        elif current is None:
            action, reason = "create", "Managed CRM configuration is absent"
            if self.kind == "workflow":
                risk = "low" if desired.get("status") == {"active": False} else "high"
            elif self.kind in {"scoring_rule", "assignment_rule", "validation_rule", "layout"}:
                risk = "high"
            if not self.writable:
                action, reason = "manual", "No reviewed provider create API/rollback contract"
            if self.kind == "webhook" and not self._auth_configured(resource):
                action, reason = "blocked", "Webhook requires configured HTTPS destination and authentication environment references"
        elif subset(current, desired) != desired:
            action, reason, risk = "update", "Managed CRM configuration differs", "high"
            if not self.writable:
                action, reason = "manual", "Provider mutation requires a reviewed UI/API contract"
            # Existing active workflow rules, associated actions, and legacy
            # webhooks cannot be altered by the low-risk additive API.
        if self.kind in {"field_update", "scoring_rule", "webhook"} and action in {"create", "update"}:
            action, reason = "manual", "Provider authentication/action rollback contract requires further proof"
        if self.kind == "layout" and current is not None and action in {"manual", "update"}:
            if self._layout_additions(current, desired):
                action, reason, risk = "update", "Append bounded empty custom-layout sections", "medium"
        return DesiredChange(resource_id=resource.id, provider=resource.provider, kind=resource.kind,
                             name=resource.name, action=action, reason=reason, current=current,
                             desired=desired, risk=risk, requires_confirmation=risk in {"high", "destructive"})

    @staticmethod
    def _layout_additions(current, desired):
        before, after = current.get("sections", []), desired.get("sections", [])
        if current.get("generated_type") != "custom" or not isinstance(after, list) or not 1 <= len(after) - len(before) <= 5:
            return []
        if subset(before, after[:len(before)]) != after[:len(before)]:
            return []
        additions = after[len(before):]
        existing_labels = {s.get("display_label") for s in before}
        labels = [s.get("display_label") for s in additions]
        if len(set(labels)) != len(labels) or any(x in existing_labels for x in labels):
            return []
        if any(set(s) != {"display_label", "fields"} or s["fields"] != [] or not isinstance(s["display_label"], str)
               or not re.fullmatch(r"[A-Za-z0-9 ]{1,50}", s["display_label"]) for s in additions):
            return []
        return additions

    @staticmethod
    def _auth_configured(resource):
        refs = resource.metadata.get("authentication", {})
        if not isinstance(refs, dict) or set(refs) != {"destination_env", "credential_env"}:
            return False
        if any(not isinstance(x, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", x) for x in refs.values()):
            return False
        dest, credential = (os.environ.get(refs[k], "") for k in ("destination_env", "credential_env"))
        parts = urlsplit(dest)
        return bool(parts.scheme == "https" and parts.hostname and not parts.username and not parts.password
                    and not parts.query and not parts.fragment and len(credential.encode()) >= 32)

    def apply(self, resource, change):
        if (not self.writable and self.kind != "layout") or change.action not in {"create", "update"}:
            raise ValueError("CRM adapter mutation unsupported")
        fresh = self.plan(resource)
        if (fresh.action, fresh.current, fresh.desired, fresh.risk) != (change.action, change.current, change.desired, change.risk):
            raise ValueError("CRM metadata drift before write")
        body = dict(resource.desired)
        if self.kind == "webhook":
            # Native workflow webhooks are not the authenticated CRM notification
            # adapter. Do not invent a header/payload authentication contract.
            raise ValueError("Webhook mutation awaits verified native authentication contract; use notifications")
        if self.kind in {"field_update", "scoring_rule"}:
            raise ValueError("Rule mutation awaits isolated action/rollback proof")
        identity = str((change.current or {}).get("id", ""))
        method = "POST" if change.action == "create" else "PUT"
        query = {}
        if self.kind == "layout":
            additions = self._layout_additions(change.current or {}, resource.desired)
            if not additions:
                raise ValueError("Only bounded empty-section additions are supported")
            body, method = {"sections": additions}, "PATCH"
            query = {"module": resource.identity["module"]}
        response = self.client.request("zohoapis", method, self.path + ("/" + identity if identity else ""),
            query=query, body={self.collection: [body]}, reason=f"Desired state {change.action} {resource.id}", confirm=True)
        rows = (response.get("data") or {}).get(self.collection)
        accepted = response.get("ok") is True and response.get("status") in {200, 201, 202} and isinstance(rows, list) and len(rows) == 1 and rows[0].get("status") == "success"
        verified = self.plan(resource).action == "noop" if accepted else False
        return DesiredApplyResult(resource_id=resource.id, action=change.action, status="completed" if verified else "manual",
            changed=accepted, result={"provider_status": response.get("status"), "request_id": response.get("request_id"),
                "verification": verified, "operation_id": (rows[0].get("details") or {}).get("id") if accepted else None})


def register_crm_metadata(registry, client):
    for kind in KINDS:
        registry.register("zoho_crm", kind, ZohoCrmMetadataReconciler(client, kind))
