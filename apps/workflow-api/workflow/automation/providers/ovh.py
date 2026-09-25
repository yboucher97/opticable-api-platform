from __future__ import annotations

from typing import Any

from ...ovh_api import OvhApiClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


def register_ovh_actions(engine: AutomationEngine, client: OvhApiClient, store: AutomationStore) -> None:
    def request(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        method = str(step.inputs.get("method", "GET")).upper().strip()
        path = str(step.inputs.get("path", "")).strip()
        query = step.inputs.get("query") or {}
        body = step.inputs.get("body")
        reason = str(step.inputs.get("reason", "")).strip()

        if not path:
            raise ValueError("ovh.request requires with.path.")
        if not isinstance(query, dict):
            raise ValueError("ovh.request query must be an object.")
        if method != "GET" and not reason:
            raise ValueError("OVH mutations require with.reason.")

        result = client.request(path, method, query=query, body=body)
        if method != "GET":
            event = context.get("event") or {}
            store.audit(
                category="provider_mutation",
                action=f"ovh.{method.lower()}",
                actor="automation-engine",
                success=True,
                correlation_id=event.get("correlation_id") or event.get("event_id"),
                target=path,
                metadata={
                    "reason": reason,
                    "workflow_id": (context.get("workflow") or {}).get("id"),
                    "step_id": step.id,
                    "body_keys": sorted(body.keys()) if isinstance(body, dict) else [],
                },
            )
        return result

    engine.register_action("ovh.request", request)
