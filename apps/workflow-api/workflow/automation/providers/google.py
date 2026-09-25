from __future__ import annotations

from typing import Any

from ...google_api import GoogleApiClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


def register_google_actions(
    engine: AutomationEngine,
    client: GoogleApiClient,
    store: AutomationStore,
) -> None:
    def run(service: str, context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        method = str(step.inputs.get("method", "GET")).upper().strip()
        path = str(step.inputs.get("path", "")).strip()
        if not path:
            raise ValueError(f"{step.action} requires with.path.")

        params = step.inputs.get("params") or {}
        body = step.inputs.get("body")
        if not isinstance(params, dict):
            raise ValueError(f"{step.action} with.params must be an object.")

        reason = str(step.inputs.get("reason", "")).strip()
        if method != "GET" and not reason:
            raise ValueError(f"{step.action} mutations require with.reason.")

        result = client.request(service, method, path, params=params, body=body)

        if method != "GET":
            event = context.get("event") or {}
            correlation_id = event.get("correlation_id") or event.get("event_id")
            store.audit(
                category="provider_mutation",
                action=f"google.{service}.{method.lower()}",
                actor="automation-engine",
                success=True,
                correlation_id=correlation_id,
                target=path,
                metadata={
                    "reason": reason,
                    "status": result.get("status"),
                    "workflow_id": (context.get("workflow") or {}).get("id"),
                    "step_id": step.id,
                    "body_keys": sorted(body.keys()) if isinstance(body, dict) else [],
                },
            )
        return result

    engine.register_action(
        "google.gtm.request",
        lambda context, step: run("tagmanager", context, step),
    )

    def generic(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        service = str(step.inputs.get("service", "")).strip()
        if not service:
            raise ValueError("google.request requires with.service.")
        return run(service, context, step)

    engine.register_action("google.request", generic)

    def analytics_admin(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        version = str(step.inputs.get("version", "v1beta")).strip().lower()
        if version not in {"v1beta", "v1alpha"}:
            raise ValueError("google.ga4_admin.request with.version must be v1beta or v1alpha.")
        return run(f"analytics_admin_{version}", context, step)

    engine.register_action("google.ga4_admin.request", analytics_admin)
