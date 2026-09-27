from __future__ import annotations

import re
import time
import hashlib
import json
import os
import socket
from pathlib import Path
from typing import Any, Callable

import yaml
import httpx

from .models import AutomationEvent, EventIngestResponse, WorkflowDefinition, WorkflowStep
from .store import AutomationStore
from .retry_control import decide_retry

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
        self._retry_safe_actions: set[str] = set()
        self.register_action("core.noop", self._action_noop, retry_safe=True)
        self.register_action("core.set", self._action_set, retry_safe=True)
        self.register_action("event.emit", self._action_emit)

    def register_action(self, name: str, handler: ActionHandler, *, retry_safe: bool = False) -> None:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Action name cannot be blank.")
        self._actions[normalized] = handler
        if retry_safe:
            self._retry_safe_actions.add(normalized)
        else:
            self._retry_safe_actions.discard(normalized)

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
        accepted, event_id, correlation_id, queued_runs = self.store.ingest_event_and_runs(event)
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
        for run_id, definition in queued_runs:
            run_ids.append(run_id)
            self.execute_run(run_id, definition, effective_event)

        return EventIngestResponse(
            accepted=True,
            duplicate=False,
            event_id=effective_event.event_id,
            correlation_id=correlation_id,
            run_ids=run_ids,
        )

    @staticmethod
    def action_identity(run_id: str, definition: WorkflowDefinition, step: WorkflowStep,
                        resolved_inputs: dict[str, Any]) -> str:
        """One stable logical key across worker attempts; only its digest is stored."""
        inputs_digest = hashlib.sha256(json.dumps(resolved_inputs, sort_keys=True, separators=(",", ":"),
                                                  ensure_ascii=False).encode()).hexdigest()
        target = resolved_inputs.get("target_id")
        if not isinstance(target, str) or not target:
            target = inputs_digest
        logical = [run_id, definition.id, definition.version, step.id, step.action, target, inputs_digest]
        return hashlib.sha256(json.dumps(logical, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _error_signal(exc: Exception) -> tuple[int | None, bool, str | None]:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(exc, "status_code", None)
        if not isinstance(status, int) or not 100 <= status <= 599:
            status = 422 if isinstance(exc, ValueError) else None
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
        return status, status is None and isinstance(
            exc, (TimeoutError, ConnectionError, httpx.TimeoutException,
                  httpx.ConnectError, httpx.ReadError)), retry_after

    @staticmethod
    def _failure_reason(action: str, category: str, retry_safe: bool) -> str:
        if action == "retry":
            return "transient_retry_scheduled"
        if category == "authentication_expired":
            return "authentication_expired"
        if category == "permanent":
            return "permanent_provider_error"
        if not retry_safe:
            return "external_result_ambiguous"
        if action == "human_action_required":
            return "provider_retry_after_unusable"
        if category == "unknown":
            return "unclassified_error"
        return "attempts_exhausted"

    def execute_run(self, run_id: str, definition: WorkflowDefinition, event: AutomationEvent,
                    *, worker_id: str | None = None) -> bool:
        worker = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        attempt_id = self.store.claim_run(run_id, worker, lease_seconds=300)
        if attempt_id is None:
            return False
        context: dict[str, Any] = {
            "event": event.model_dump(),
            "workflow": {"id": definition.id, "version": definition.version, "name": definition.name},
            "steps": {},
        }
        continued_error = False

        for step in definition.steps:
            handler = self._actions.get(step.action)
            preflight_reason = "unknown_action" if handler is None else None
            retry_safe = step.action in self._retry_safe_actions
            step_succeeded = False
            try:
                resolved_inputs = _resolve_templates(step.inputs, context)
            except Exception:
                resolved_inputs = step.inputs
                handler = None
                preflight_reason = "template_reference_missing"
            identity = self.action_identity(run_id, definition, step, resolved_inputs)
            for attempt in range(1, step.retry.max_attempts + 1):
                marker = self.store.begin_claimed_action(
                    run_id, attempt_id, step_id=step.id, action=step.action,
                    action_identity=identity, attempt=attempt)
                if marker is None:
                    return False
                try:
                    if handler is None:
                        raise ValueError("unknown action or unresolved workflow input")
                    effective_step = step.model_copy(update={"inputs": resolved_inputs})
                    context["execution"] = {"action_identity": identity}
                    result = handler(context, effective_step)
                except Exception as exc:  # provider/template runtime errors are captured durably
                    status_code, timeout, retry_after = self._error_signal(exc)
                    decision = decide_retry(
                        attempt=attempt, max_attempts=step.retry.max_attempts,
                        safe_to_retry=retry_safe, http_status=status_code, network_timeout=timeout,
                        retry_after=retry_after,
                        base_delay_seconds=step.retry.backoff_seconds or 2.0,
                    )
                    reason = self._failure_reason(decision.action, decision.category, retry_safe)
                    if preflight_reason is not None:
                        reason = preflight_reason
                    diagnostic = {"http_status": status_code} if status_code is not None else {}
                    if decision.action == "retry":
                        diagnostic["retry_delay_seconds"] = decision.delay_seconds
                    if not self.store.complete_claimed_action(
                            run_id, attempt_id, marker, succeeded=False,
                            error=type(exc).__name__, failure_category=decision.category,
                            reason_code=reason, diagnostic=diagnostic):
                        return False
                    if decision.action == "retry":
                        remaining = decision.delay_seconds
                        while remaining > 0:
                            interval = min(30.0, remaining)
                            time.sleep(interval)
                            remaining -= interval
                            if not self.store.renew_claim(run_id, attempt_id, lease_seconds=300):
                                return False
                        continue
                    if decision.action == "dead_letter" and step.on_error == "continue":
                        continued_error = True
                        break
                    terminal = ("failed" if decision.action == "dead_letter"
                                and (decision.category == "permanent" or preflight_reason is not None)
                                else decision.action)
                    return self.store.finish_claim(
                        run_id, attempt_id, status=terminal,
                        error=reason, failure_category=decision.category,
                        reason_code=reason, redrive_permitted=retry_safe and terminal == "dead_letter"
                        and decision.category in {"rate_limited", "network_timeout", "provider_unavailable"},
                        human_required=terminal == "human_action_required", context=context,
                    )
                provider_operation_id = (result.get("provider_operation_id")
                                         if isinstance(result, dict) else None)
                if not self.store.complete_claimed_action(
                        run_id, attempt_id, marker, succeeded=True, result=result,
                        provider_operation_id=provider_operation_id):
                    return False
                context["steps"][step.id] = result
                step_succeeded = True
                break

            if not step_succeeded:
                if step.on_error == "continue":
                    continue
                return False

        final_status = "partial" if continued_error else "completed"
        return self.store.finish_claim(run_id, attempt_id, status=final_status, context=context)

    def recover_pending(self, *, limit: int = 10) -> dict[str, int]:
        recovered = self.store.recover_expired_claims(limit=min(limit, 100))
        attempted = 0
        for run_id, definition, event in self.store.queued_envelopes(limit):
            attempted += int(self.execute_run(run_id, definition, event))
        return {**recovered, "executed": attempted}

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
            idempotency_key=(step.inputs.get("idempotency_key")
                             or "action:" + context["execution"]["action_identity"]),
            depth=parent.depth + 1,
            payload=payload,
        )
        response = self.ingest(child)
        return response.model_dump()
