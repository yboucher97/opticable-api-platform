from __future__ import annotations

from typing import Any

from ...ai_router import AiRouter
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


def register_ai_actions(engine: AutomationEngine, router: AiRouter, store: AutomationStore) -> None:
    def generate(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        prompt = str(step.inputs.get("prompt", "")).strip()
        provider = str(step.inputs.get("provider", "auto")).strip().lower()
        system = step.inputs.get("system")
        max_tokens = int(step.inputs.get("max_tokens", 1200))
        result = router.generate(
            prompt,
            provider=provider,
            system=str(system) if system is not None else None,
            max_tokens=max_tokens,
        )
        event = context.get("event") or {}
        store.audit(
            category="ai_inference",
            action="ai.generate",
            actor="automation-engine",
            success=True,
            correlation_id=event.get("correlation_id") or event.get("event_id"),
            target=result.get("provider"),
            metadata={
                "model": result.get("model"),
                "workflow_id": (context.get("workflow") or {}).get("id"),
                "step_id": step.id,
                "prompt_length": len(prompt),
            },
        )
        return result

    engine.register_action("ai.generate", generate)
