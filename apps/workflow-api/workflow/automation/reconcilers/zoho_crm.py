from __future__ import annotations

from contextlib import contextmanager
import threading
import re
import unicodedata
from typing import Any

from ..crm_inventory import normalize
from ..event_schema import digest

from ...zoho_gateway import ZohoGatewayClient
from ..desired_state import DesiredApplyResult, DesiredChange, DesiredResource


class ZohoCrmFieldReconciler:
    """Declarative Zoho CRM custom-field reconciler.

    Identity is resolved by api_name first, then field_label. Standard fields are
    never deleted by this reconciler. Deletions require lifecycle.ensure=absent
    and are still blocked by the controller unless allow_destructive=true.
    """

    name = "zoho_crm.field.v1"

    def __init__(self, client: ZohoGatewayClient) -> None:
        self.client = client
        self._local = threading.local()

    @contextmanager
    def plan_context(self):
        self._local.cache = {}
        try:
            yield
        finally:
            self._local.cache = None

    @staticmethod
    def _module(resource: DesiredResource) -> str:
        module = str(resource.desired.get("module") or resource.identity.get("module") or "").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", module):
            raise ValueError(f"{resource.id}: desired.module or identity.module is required.")
        return module

    @staticmethod
    def _desired_field(resource: DesiredResource) -> dict[str, Any]:
        field = {k: v for k, v in resource.desired.items() if k != "module"}
        allowed = {"api_name", "field_label", "data_type", "length", "decimal_place", "required", "unique", "tooltip", "pick_list_values"}
        if set(field) - allowed:
            raise ValueError("Unsupported managed field properties require human review")
        if not field:
            raise ValueError(f"{resource.id}: desired field definition is empty.")
        if not field.get("field_label") and not field.get("api_name"):
            raise ValueError(f"{resource.id}: field_label or api_name is required.")
        return field

    @staticmethod
    def _identity(resource: DesiredResource, desired: dict[str, Any]) -> tuple[str | None, str | None]:
        if resource.identity.get("api_name") and desired.get("api_name") and resource.identity["api_name"] != desired["api_name"]:
            raise ValueError("Managed field API identity differs from desired API name")
        api_name = str(resource.identity.get("api_name") or desired.get("api_name") or "").strip() or None
        field_label = str(resource.identity.get("field_label") or desired.get("field_label") or "").strip() or None
        return api_name, field_label

    def _list_fields(self, module: str) -> list[dict[str, Any]]:
        cache = getattr(self._local, "cache", None)
        if cache is not None and module in cache:
            return cache[module]
        response = self.client.request(
            "zohoapis",
            "GET",
            "/crm/v8/settings/fields",
            query={"module": module},
        )
        data = response.get("data") or {}
        fields = data.get("fields") if isinstance(data, dict) else None
        if response.get("ok") is not True or response.get("status") != 200 or not isinstance(fields, list):
            raise ValueError("CRM field read failed closed")
        if len(fields) > 500 or (data.get("info") or {}).get("more_records"):
            raise ValueError("CRM field read incomplete or exceeds bound")
        if cache is not None:
            cache[module] = fields
        return fields

    @staticmethod
    def _find_field(
        fields: list[dict[str, Any]],
        api_name: str | None,
        field_label: str | None,
    ) -> dict[str, Any] | None:
        def semantic(value):
            return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(value or "")).casefold())
        by_api = [f for f in fields if api_name and f.get("api_name") == api_name]
        by_label = [f for f in fields if field_label and semantic(f.get("field_label") or f.get("display_label")) == semantic(field_label)]
        if len(by_api) > 1 or len(by_label) > 1:
            raise ValueError("Duplicate semantic CRM field identity")
        if by_api:
            if by_label and by_label[0].get("id") != by_api[0].get("id"):
                raise ValueError("CRM field API/label identity collision")
            return by_api[0]
        if by_label:
            if api_name and by_label[0].get("api_name") != api_name:
                raise ValueError("Existing semantic field uses a different API name; reuse it")
            return by_label[0]
        return None

    @staticmethod
    def _normalize_picklist(values: Any) -> list[str] | None:
        if not isinstance(values, list):
            return None
        normalized: list[str] = []
        for item in values:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                value = item.get("display_value")
                if value is not None:
                    normalized.append(str(value))
        return normalized

    @classmethod
    def _comparable(cls, field: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        keys = {
            "api_name",
            "field_label",
            "data_type",
            "length",
            "decimal_place",
            "required",
            "unique",
            "tooltip",
        }
        for key in keys:
            if key in desired:
                result[key] = field.get(key)

        if "pick_list_values" in desired:
            result["pick_list_values"] = cls._normalize_picklist(field.get("pick_list_values")) or []
        return result

    @classmethod
    def _desired_comparable(cls, desired: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in (
            "api_name",
            "field_label",
            "data_type",
            "length",
            "decimal_place",
            "required",
            "unique",
            "tooltip",
        ):
            if key in desired:
                result[key] = desired.get(key)

        if "pick_list_values" in desired:
            result["pick_list_values"] = cls._normalize_picklist(desired.get("pick_list_values")) or []
        return result

    def plan(self, resource: DesiredResource) -> DesiredChange:
        module = self._module(resource)
        desired = self._desired_field(resource)
        api_name, field_label = self._identity(resource, desired)
        fields = self._list_fields(module)
        current = self._find_field(fields, api_name, field_label)
        ensure = str(resource.lifecycle.get("ensure", "present")).lower().strip()

        if ensure not in {"present", "absent"}:
            return DesiredChange(
                resource_id=resource.id,
                provider=resource.provider,
                kind=resource.kind,
                name=resource.name,
                action="blocked",
                reason=f"Unsupported lifecycle.ensure={ensure!r}; expected present or absent.",
                current=current,
                desired=desired,
                risk="medium",
            )

        if ensure == "absent":
            if current is None:
                return DesiredChange(
                    resource_id=resource.id,
                    provider=resource.provider,
                    kind=resource.kind,
                    name=resource.name,
                    action="noop",
                    reason="Field is already absent.",
                    current=None,
                    desired=None,
                    risk="low",
                )
            if current.get("custom_field") is not True:
                return DesiredChange(
                    resource_id=resource.id,
                    provider=resource.provider,
                    kind=resource.kind,
                    name=resource.name,
                    action="blocked",
                    reason="Refusing to delete a standard/system CRM field.",
                    current=current,
                    desired=None,
                    risk="destructive",
                    requires_confirmation=True,
                )
            return DesiredChange(
                resource_id=resource.id,
                provider=resource.provider,
                kind=resource.kind,
                name=resource.name,
                action="delete",
                reason="Managed custom field exists but desired lifecycle is absent.",
                current=current,
                desired=None,
                risk="destructive",
                requires_confirmation=True,
            )

        if current is None:
            unsafe = (desired.get("required") or desired.get("unique") or
                      desired.get("data_type") not in {"text", "datetime", "integer", "boolean", "textarea", "picklist", "multiselectpicklist"})
            return DesiredChange(
                resource_id=resource.id,
                provider=resource.provider,
                kind=resource.kind,
                name=resource.name,
                action="create",
                reason="Managed CRM field does not exist.",
                current=None,
                desired=desired,
                risk="high" if unsafe else "low",
                requires_confirmation=bool(unsafe),
            )

        current_cmp = self._comparable(current, desired)
        current_cmp["id"] = current.get("id")
        desired_cmp = self._desired_comparable(desired)
        if {k: v for k, v in current_cmp.items() if k != "id"} == desired_cmp:
            return DesiredChange(
                resource_id=resource.id,
                provider=resource.provider,
                kind=resource.kind,
                name=resource.name,
                action="noop",
                reason="CRM field matches desired state.",
                current=current_cmp,
                desired=desired_cmp,
                risk="low",
            )

        data_type_changed = (
            "data_type" in desired_cmp
            and current_cmp.get("data_type") is not None
            and current_cmp.get("data_type") != desired_cmp.get("data_type")
        )
        return DesiredChange(
            resource_id=resource.id,
            provider=resource.provider,
            kind=resource.kind,
            name=resource.name,
            action="update",
            reason="CRM field differs from desired state.",
            current=current_cmp,
            desired=desired_cmp,
            risk="high" if data_type_changed or desired.get("required") or desired.get("unique") or (
                "length" in desired and int(desired["length"]) < int(current.get("length") or 0)) or (
                "pick_list_values" in desired and not set(self._normalize_picklist(current.get("pick_list_values")) or []) <=
                set(self._normalize_picklist(desired["pick_list_values"]) or [])) else "medium",
            requires_confirmation=data_type_changed,
        )

    def apply(self, resource: DesiredResource, change: DesiredChange) -> DesiredApplyResult:
        module = self._module(resource)
        desired = self._desired_field(resource)
        checked = self.plan(resource)
        # Controller adds adapter/dependency annotations; adapter compares its own evidence.
        if (checked.action, checked.current, checked.desired, checked.risk) != (change.action, change.current, change.desired, change.risk):
            raise ValueError("CRM field changed before mutation")
        allowed = {"api_name", "field_label", "data_type", "length", "decimal_place", "required", "unique", "tooltip", "pick_list_values"}
        if set(desired) - allowed:
            raise ValueError("Unsupported field mutation properties")
        if change.action == "create" and (len(self._list_fields(module)) >= 490):
            raise ValueError("CRM field headroom below conservative reserve")
        if "pick_list_values" in desired:
            desired["pick_list_values"] = [{"display_value": v} if isinstance(v, str) else v for v in desired["pick_list_values"]]

        if change.action == "create":
            response = self.client.request(
                "zohoapis",
                "POST",
                "/crm/v8/settings/fields",
                query={"module": module},
                body={"fields": [desired]},
                reason=f"Desired state create CRM field {resource.id}",
                confirm=True,
            )
        elif change.action == "update":
            current = change.current or {}
            field_id = current.get("id")
            if not field_id:
                api_name, field_label = self._identity(resource, desired)
                existing = self._find_field(self._list_fields(module), api_name, field_label)
                field_id = (existing or {}).get("id")
            if not field_id:
                raise RuntimeError(f"{resource.id}: cannot update field because its CRM id could not be resolved.")
            response = self.client.request(
                "zohoapis",
                "PATCH",
                f"/crm/v8/settings/fields/{field_id}",
                query={"module": module},
                body={"fields": [desired]},
                reason=f"Desired state update CRM field {resource.id}",
                confirm=True,
            )
        elif change.action == "delete":
            if (change.current or {}).get("custom_field") is not True:
                raise ValueError("Only explicitly custom fields can be retired")
            current = change.current or {}
            field_id = current.get("id")
            if not field_id:
                api_name, field_label = self._identity(resource, desired)
                existing = self._find_field(self._list_fields(module), api_name, field_label)
                field_id = (existing or {}).get("id")
            if not field_id:
                return DesiredApplyResult(
                    resource_id=resource.id,
                    action="delete",
                    status="completed",
                    changed=False,
                    result={"already_absent": True},
                )
            response = self.client.request(
                "zohoapis",
                "DELETE",
                f"/crm/v8/settings/fields/{field_id}",
                query={"module": module},
                reason=f"Desired state delete CRM field {resource.id}",
                confirm=True,
            )
        else:
            return DesiredApplyResult(
                resource_id=resource.id,
                action=change.action,
                status="completed",
                changed=False,
            )

        data = response.get("data") or {}
        rows = data.get("fields") if isinstance(data, dict) else None
        accepted = response.get("ok") is True and response.get("status") in {200, 201, 202} and isinstance(rows, list) and len(rows) == 1 and rows[0].get("status") == "success"
        verified = self.plan(resource).action == "noop" if accepted else False
        return DesiredApplyResult(
            resource_id=resource.id,
            action=change.action,
            status="completed" if accepted and verified else "manual",
            changed=accepted,
            result={
                "provider_status": response.get("status"),
                "request_id": response.get("request_id"),
                "verification": verified,
                "operation_id": (rows[0].get("details") or {}).get("id") if accepted else None,
            },
        )
