from __future__ import annotations

from typing import Any

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

    @staticmethod
    def _module(resource: DesiredResource) -> str:
        module = str(resource.desired.get("module") or resource.identity.get("module") or "").strip()
        if not module:
            raise ValueError(f"{resource.id}: desired.module or identity.module is required.")
        return module

    @staticmethod
    def _desired_field(resource: DesiredResource) -> dict[str, Any]:
        field = {k: v for k, v in resource.desired.items() if k != "module"}
        if not field:
            raise ValueError(f"{resource.id}: desired field definition is empty.")
        if not field.get("field_label") and not field.get("api_name"):
            raise ValueError(f"{resource.id}: field_label or api_name is required.")
        return field

    @staticmethod
    def _identity(resource: DesiredResource, desired: dict[str, Any]) -> tuple[str | None, str | None]:
        api_name = str(resource.identity.get("api_name") or desired.get("api_name") or "").strip() or None
        field_label = str(resource.identity.get("field_label") or desired.get("field_label") or "").strip() or None
        return api_name, field_label

    def _list_fields(self, module: str) -> list[dict[str, Any]]:
        response = self.client.request(
            "zohoapis",
            "GET",
            "/crm/v8/settings/fields",
            query={"module": module},
        )
        data = response.get("data") or {}
        fields = data.get("fields") if isinstance(data, dict) else None
        return fields if isinstance(fields, list) else []

    @staticmethod
    def _find_field(
        fields: list[dict[str, Any]],
        api_name: str | None,
        field_label: str | None,
    ) -> dict[str, Any] | None:
        if api_name:
            for field in fields:
                if str(field.get("api_name") or "") == api_name:
                    return field
        if field_label:
            for field in fields:
                if str(field.get("field_label") or field.get("display_label") or "") == field_label:
                    return field
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
            if current.get("custom_field") is False:
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
            return DesiredChange(
                resource_id=resource.id,
                provider=resource.provider,
                kind=resource.kind,
                name=resource.name,
                action="create",
                reason="Managed CRM field does not exist.",
                current=None,
                desired=desired,
                risk="low",
            )

        current_cmp = self._comparable(current, desired)
        desired_cmp = self._desired_comparable(desired)
        if current_cmp == desired_cmp:
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
            risk="high" if data_type_changed else "medium",
            requires_confirmation=data_type_changed,
        )

    def apply(self, resource: DesiredResource, change: DesiredChange) -> DesiredApplyResult:
        module = self._module(resource)
        desired = self._desired_field(resource)

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

        return DesiredApplyResult(
            resource_id=resource.id,
            action=change.action,
            status="completed",
            changed=True,
            result={
                "provider_status": response.get("status"),
                "request_id": response.get("request_id"),
            },
        )
