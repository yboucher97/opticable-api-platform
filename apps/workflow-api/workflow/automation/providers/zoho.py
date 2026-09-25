from __future__ import annotations

from typing import Any

from ...zoho_gateway import ZohoGatewayClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


def register_zoho_actions(
    engine: AutomationEngine,
    client: ZohoGatewayClient,
    store: AutomationStore,
) -> None:
    def request(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        service = str(step.inputs.get("service", "")).strip()
        method = str(step.inputs.get("method", "GET")).upper().strip()
        path = str(step.inputs.get("path", "")).strip()
        query = step.inputs.get("query") or {}
        headers = step.inputs.get("headers") or {}
        body = step.inputs.get("body")
        content_type = str(step.inputs.get("content_type", "application/json")).strip()
        reason = str(step.inputs.get("reason", "")).strip()

        if not service:
            raise ValueError("zoho.request requires with.service.")
        if not path:
            raise ValueError("zoho.request requires with.path.")
        if not isinstance(query, dict) or not isinstance(headers, dict):
            raise ValueError("zoho.request query and headers must be objects.")
        if method != "GET" and not reason:
            raise ValueError("zoho.request mutations require with.reason.")

        result = client.request(
            service,
            method,
            path,
            query=query,
            headers=headers,
            body=body,
            content_type=content_type,
            reason=reason or None,
            confirm=True if method != "GET" else None,
        )

        if method != "GET":
            event = context.get("event") or {}
            correlation_id = event.get("correlation_id") or event.get("event_id")
            store.audit(
                category="provider_mutation",
                action=f"zoho.{service}.{method.lower()}",
                actor="automation-engine",
                success=True,
                correlation_id=correlation_id,
                target=path,
                metadata={
                    "reason": reason,
                    "workflow_id": (context.get("workflow") or {}).get("id"),
                    "step_id": step.id,
                    "body_keys": sorted(body.keys()) if isinstance(body, dict) else [],
                },
            )
        return result

    engine.register_action("zoho.request", request)
