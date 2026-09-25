from __future__ import annotations

from typing import Any

from ...apollo_api import ApolloApiClient
from ...cloudflare_api import CloudflareApiClient
from ...github_api import GithubApiClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


def register_core_external_actions(
    engine: AutomationEngine,
    cloudflare: CloudflareApiClient,
    github: GithubApiClient,
    apollo: ApolloApiClient,
    store: AutomationStore,
) -> None:
    def register(name: str, client: Any):
        def run(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
            method = str(step.inputs.get("method", "GET")).upper().strip()
            path = str(step.inputs.get("path", "")).strip()
            params = step.inputs.get("params") or {}
            body = step.inputs.get("body")
            reason = str(step.inputs.get("reason", "")).strip()
            if not path:
                raise ValueError(f"{name}.request requires with.path.")
            if not isinstance(params, dict):
                raise ValueError(f"{name}.request params must be an object.")
            if method != "GET" and not reason:
                raise ValueError(f"{name} mutations require with.reason.")
            result = client.request(path, method, params=params, body=body)
            if method != "GET":
                event = context.get("event") or {}
                store.audit(
                    category="provider_mutation",
                    action=f"{name}.{method.lower()}",
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
        engine.register_action(f"{name}.request", run)

    register("cloudflare", cloudflare)
    register("github", github)
    register("apollo", apollo)
