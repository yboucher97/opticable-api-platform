from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from .models import AutomationEvent, EventIngestResponse, WorkflowDefinition, WorkflowStep, utc_now_iso
from .store import AutomationStore

ActionHandler = Callable[[dict[str, Any], WorkflowStep], Any]

_TEMPLATE_RE = re.compile(r"{{[ \t\r\n]*([A-Za-z0-9_.-]+)[ \t\r\n]*}}")


def _lookup_context(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        raise KeyError(f"Workflow template reference not found: {path}")
    return current


def _resolve_templates(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_templates(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_templates(item, context) for item in value]
    if not isinstance(value, str):
        return value

    full = _TEMPLATE_RE.fullmatch(value)
    if full:
        return _lookup_context(context, full.group(1))

    def replace(match: re.Match[str]) -> str:
        resolved = _lookup_context(context, match.group(1))
        return str(resolved)

    return _TEMPLATE_RE.sub(replace, value)


class AutomationEngine:
    """Small provider-neutral workflow engine.

    Provider-specific actions are registered as handlers so integrations can be
    added without changing scheduling, auditing, idempotency, or event logic.
    """

    def __init__(self, store: AutomationStore, definitions_dir: Path, *, max_event_depth: int = 8) -> None:
        self.store = store
        self.definitions_dir = definitions_dir
        self.max_event_depth = max_event_depth
        self._actions: dict[str, ActionHandler] = {}
        self.register_action("core.noop", self._action_noop)
        self.register_action("core.set", self._action_set)
        self.register_action("event.emit", self._action_emit)

    def register_action(self, name: str, handler: ActionHandler) -> None:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Action name cannot be blank.")
        self._actions[normalized] = handler

    def action_names(self) -> list[str]:
        return sorted(self._actions)

    def sync_definitions(self) -> list[str]:
        self.definitions_dir.mkdir(parents=True, exist_ok=True)
        loaded: list[str] = []
        for path in sorted(self.definitions_dir.glob("*.y*ml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"Workflow file must contain a mapping: {path}")
            definition = WorkflowDefinition.model_validate(raw)
            self.store.upsert_workflow(definition, str(path))
            loaded.append(definition.id)
        return loaded

    def ingest(self, event: AutomationEvent) -> EventIngestResponse:
        if event.depth > self.max_event_depth:
            raise ValueError(f"Event depth {event.depth} exceeds max depth {self.max_event_depth}.")
        accepted, event_id, correlation_id = self.store.ingest_event(event)
        if not accepted:
            return EventIngestResponse(
                accepted=False,
                duplicate=True,
                event_id=event_id,
                correlation_id=correlation_id,
                run_ids=[],
            )

        effective_event = event.model_copy(update={"correlation_id": correlation_id})
        run_ids: list[str] = []
        for definition in self.store.matching_workflows(effective_event):
            run_id = self.store.create_run(definition.id, effective_event.event_id, correlation_id)
            run_ids.append(run_id)
            self.execute_run(run_id, definition, effective_event)

        return EventIngestResponse(
            accepted=True,
            duplicate=False,
            event_id=effective_event.event_id,
            correlation_id=correlation_id,
            run_ids=run_ids,
        )

    def execute_run(self, run_id: str, definition: WorkflowDefinition, event: AutomationEvent) -> None:
        context: dict[str, Any] = {
            "event": event.model_dump(),
            "workflow": {"id": definition.id, "version": definition.version, "name": definition.name},
            "steps": {},
        }
        self.store.set_run_status(run_id, "running")
        self.store.audit(
            category="workflow", action="run_started", actor="automation-engine", success=True,
            correlation_id=event.correlation_id, target=definition.id, metadata={"run_id": run_id},
        )

        run_failed = False
        failure_message: str | None = None
        continued_error = False

        for step in definition.steps:
            handler = self._actions.get(step.action)
            if handler is None:
                error = f"Unknown automation action: {step.action}"
                self.store.append_step(
                    run_id=run_id, step_id=step.id, action=step.action, attempt=1,
                    status="failed", started_at=utc_now_iso(), error=error,
                )
                if step.on_error == "continue":
                    continued_error = True
                    continue
                run_failed = True
                failure_message = error
                break

            step_succeeded = False
            last_error: str | None = None
            for attempt in range(1, step.retry.max_attempts + 1):
                started_at = utc_now_iso()
                try:
                    resolved_inputs = _resolve_templates(step.inputs, context)
                    effective_step = step.model_copy(update={"inputs": resolved_inputs})
                    result = handler(context, effective_step)
                except Exception as exc:  # provider/template runtime errors are captured durably
                    last_error = str(exc)
                    self.store.append_step(
                        run_id=run_id, step_id=step.id, action=step.action, attempt=attempt,
                        status="failed", started_at=started_at, error=last_error,
                    )
                    if attempt < step.retry.max_attempts and step.retry.backoff_seconds:
                        time.sleep(step.retry.backoff_seconds)
                    continue
                self.store.append_step(
                    run_id=run_id, step_id=step.id, action=step.action, attempt=attempt,
                    status="completed", started_at=started_at, result=result,
                )
                context["steps"][step.id] = result
                step_succeeded = True
                break

            if not step_succeeded:
                if step.on_error == "continue":
                    continued_error = True
                    continue
                run_failed = True
                failure_message = last_error or f"Step {step.id} failed."
                break

        if run_failed:
            self.store.set_run_status(run_id, "failed", error=failure_message, context=context)
            self.store.audit(
                category="workflow", action="run_failed", actor="automation-engine", success=False,
                correlation_id=event.correlation_id, target=definition.id,
                metadata={"run_id": run_id, "error": failure_message},
            )
            return

        final_status = "partial" if continued_error else "completed"
        self.store.set_run_status(run_id, final_status, context=context)
        self.store.audit(
            category="workflow", action=f"run_{final_status}", actor="automation-engine", success=not continued_error,
            correlation_id=event.correlation_id, target=definition.id, metadata={"run_id": run_id},
        )

    def _action_noop(self, context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        return {"ok": True, "inputs": step.inputs}

    def _action_set(self, context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        values = step.inputs.get("values", {})
        if not isinstance(values, dict):
            raise ValueError("core.set requires with.values to be an object.")
        context.setdefault("vars", {}).update(values)
        return {"updated": sorted(values)}

    def _action_emit(self, context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        parent = AutomationEvent.model_validate(context["event"])
        event_type = str(step.inputs.get("event_type", "")).strip()
        if not event_type:
            raise ValueError("event.emit requires with.event_type.")
        source = str(step.inputs.get("source", "automation-engine")).strip() or "automation-engine"
        payload = step.inputs.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("event.emit with.payload must be an object.")
        child = AutomationEvent(
            event_type=event_type,
            source=source,
            correlation_id=parent.correlation_id or parent.event_id,
            causation_id=parent.event_id,
            idempotency_key=step.inputs.get("idempotency_key"),
            depth=parent.depth + 1,
            payload=payload,
        )
        response = self.ingest(child)
        return response.model_dump()
