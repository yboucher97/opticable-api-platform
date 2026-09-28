from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .event_schema import digest
from .desired_journal import DesiredJournal, resource_key
from .crm_inventory import normalize


class DesiredResource(BaseModel):
    """Declarative resource managed by the Opticable control plane."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9._:-]*$")
    provider: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    enabled: bool = True
    desired: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("depends_on")
    @classmethod
    def normalize_dependencies(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class DesiredStateDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["opticable.io/v1alpha1"] = "opticable.io/v1alpha1"
    kind: Literal["DesiredState"] = "DesiredState"
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    description: str | None = None
    resources: list[DesiredResource] = Field(default_factory=list, max_length=200)

    @field_validator("resources")
    @classmethod
    def unique_ids(cls, values: list[DesiredResource]) -> list[DesiredResource]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for item in values:
            if item.id in seen:
                duplicates.append(item.id)
            seen.add(item.id)
        if duplicates:
            raise ValueError(f"Duplicate desired-state resource ids: {', '.join(sorted(set(duplicates)))}")
        return values


class DesiredChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    provider: str
    kind: str
    name: str
    action: str = Field(pattern=r"^(create|update|delete|noop|manual|blocked)$")
    reason: str
    current: dict[str, Any] | None = None
    desired: dict[str, Any] | None = None
    risk: str = Field(default="low", pattern=r"^(low|medium|high|destructive)$")
    requires_confirmation: bool = False
    dependencies: list[str] = Field(default_factory=list)
    adapter: str | None = None


class DesiredPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_name: str
    document_version: int
    document_hash: str
    plan_hash: str = ""
    changes: list[DesiredChange]
    summary: dict[str, int]


class DesiredApplyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    action: str
    status: str
    changed: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DesiredStateAdapter(Protocol):
    name: str

    def plan(self, resource: DesiredResource) -> DesiredChange:
        ...

    def apply(self, resource: DesiredResource, change: DesiredChange) -> DesiredApplyResult:
        ...


@dataclass(frozen=True)
class AdapterKey:
    provider: str
    kind: str


class DesiredStateRegistry:
    """Provider/kind adapter registry.

    Exact provider+kind matches win, then provider+* wildcard.
    This lets providers add resources without changing the reconciliation core.
    """

    def __init__(self) -> None:
        self._adapters: dict[AdapterKey, DesiredStateAdapter] = {}

    def register(self, provider: str, kind: str, adapter: DesiredStateAdapter) -> None:
        key = AdapterKey(provider.strip().lower(), kind.strip().lower())
        if key in self._adapters:
            raise ValueError(f"Desired-state adapter already registered for {provider}/{kind}")
        self._adapters[key] = adapter

    def resolve(self, resource: DesiredResource) -> DesiredStateAdapter | None:
        provider = resource.provider.strip().lower()
        kind = resource.kind.strip().lower()
        return self._adapters.get(AdapterKey(provider, kind)) or self._adapters.get(AdapterKey(provider, "*"))

    def list_adapters(self) -> list[dict[str, str]]:
        return [
            {"provider": key.provider, "kind": key.kind, "adapter": getattr(adapter, "name", adapter.__class__.__name__)}
            for key, adapter in sorted(self._adapters.items(), key=lambda item: (item[0].provider, item[0].kind))
        ]


class DesiredStateController:
    def __init__(self, registry: DesiredStateRegistry, store=None) -> None:
        self.registry = registry
        self.journal = DesiredJournal(store)

    @staticmethod
    def load(path: Path) -> DesiredStateDocument:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return DesiredStateDocument.model_validate(raw)

    def plan(self, document: DesiredStateDocument) -> DesiredPlan:
        with ExitStack() as stack:
            adapters = {id(a): a for a in self.registry._adapters.values()}
            for adapter in adapters.values():
                if hasattr(adapter, "plan_context"):
                    stack.enter_context(adapter.plan_context())
            return self._plan(document)

    @classmethod
    def validate_document(cls, document: DesiredStateDocument, *, require_dependencies: bool = True) -> str:
        raw = document.model_dump(mode="json")
        if len(str(raw)) > 1_048_576 or normalize(raw) != raw:
            raise ValueError("Desired-state document contains secret/URL material or exceeds bounds; use environment references")
        keys = [resource_key(r) for r in document.resources if r.enabled]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate provider resource identities")
        enabled = {r.id for r in document.resources if r.enabled}
        if require_dependencies and any(set(r.depends_on) - enabled for r in document.resources if r.enabled):
            raise ValueError("Missing enabled dependency")
        cls._dependency_order(document, [DesiredChange(resource_id=r.id, provider=r.provider,
            kind=r.kind, name=r.name, action="noop", reason="validation") for r in document.resources if r.enabled])
        return digest(raw)

    def _plan(self, document: DesiredStateDocument) -> DesiredPlan:
        self.validate_document(document, require_dependencies=False)
        changes: list[DesiredChange] = []
        enabled_ids = {r.id for r in document.resources if r.enabled}

        for resource in document.resources:
            if not resource.enabled:
                continue

            missing_dependencies = [dep for dep in resource.depends_on if dep not in enabled_ids]
            if missing_dependencies:
                changes.append(
                    DesiredChange(
                        resource_id=resource.id,
                        provider=resource.provider,
                        kind=resource.kind,
                        name=resource.name,
                        action="blocked",
                        reason=f"Missing enabled dependencies: {', '.join(missing_dependencies)}",
                        desired=resource.desired,
                        dependencies=resource.depends_on,
                        risk="medium",
                        requires_confirmation=False,
                    )
                )
                continue

            adapter = self.registry.resolve(resource)
            if adapter is None:
                changes.append(
                    DesiredChange(
                        resource_id=resource.id,
                        provider=resource.provider,
                        kind=resource.kind,
                        name=resource.name,
                        action="manual",
                        reason="No programmable adapter registered for this provider/resource kind.",
                        desired=resource.desired,
                        dependencies=resource.depends_on,
                        risk="medium",
                        requires_confirmation=True,
                    )
                )
                continue

            try:
                if hasattr(adapter, "bind_journal"):
                    adapter.bind_journal(self.journal)
                change = adapter.plan(resource)
            except Exception as exc:
                change = DesiredChange(resource_id=resource.id, provider=resource.provider, kind=resource.kind,
                                       name=resource.name, action="blocked", reason="Provider read failed: " + type(exc).__name__,
                                       risk="high")
            change.current = normalize(change.current)
            change.desired = normalize(change.desired)
            change.adapter = getattr(adapter, "name", adapter.__class__.__name__)
            change.dependencies = resource.depends_on
            changes.append(change)

        ordered = self._dependency_order(document, changes)
        counts: dict[str, int] = {}
        for change in ordered:
            counts[change.action] = counts.get(change.action, 0) + 1

        plan = DesiredPlan(
            document_name=document.name,
            document_version=document.version,
            document_hash=digest(document.model_dump(mode="json")),
            changes=ordered,
            summary=counts,
        )
        plan.plan_hash = digest(plan.model_dump(exclude={"plan_hash"}, mode="json"))
        return plan

    def apply(
        self, document: DesiredStateDocument, plan: DesiredPlan, *,
        allow_destructive: bool = False, allow_high_risk: bool = False,
        low_risk_additive_only: bool = False, actor: str = "controller",
    ) -> list[DesiredApplyResult]:
        if plan.plan_hash != digest(plan.model_dump(exclude={"plan_hash"}, mode="json")):
            raise ValueError("Invalid plan digest")
        if plan.document_hash != digest(document.model_dump(mode="json")):
            raise ValueError("Desired document changed since planning")
        with self.journal.lock():
            fresh = self.plan(document)
            if fresh.plan_hash != plan.plan_hash:
                raise ValueError("Stale plan: provider state changed")
            resources = {r.id: r for r in document.resources if r.enabled}
            results, failed = [], set()
            for change in fresh.changes:
                resource = resources[change.resource_id]
                key = resource_key(resource)
                error = None
                status = "completed"
                if self.journal.unresolved(key):
                    status, error = "manual", "Previous provider operation unresolved; human reconciliation required"
                elif any(dep in failed for dep in change.dependencies):
                    status, error = "blocked", "A dependency did not complete"
                elif change.action in {"manual", "blocked"}:
                    status, error = change.action, change.reason
                elif change.risk == "destructive" and not allow_destructive:
                    status, error = "blocked", "Destructive change requires explicit human approval"
                elif change.risk == "high" and not allow_high_risk:
                    status, error = "blocked", "High-risk change requires explicit human approval"
                elif low_risk_additive_only and change.action != "noop" and (change.action != "create" or change.risk != "low"):
                    status, error = "blocked", "API applies only additive low-risk resources"
                if error or change.action == "noop":
                    result = DesiredApplyResult(resource_id=resource.id, action=change.action,
                                                status=status, changed=False, error=error)
                else:
                    adapter = self.registry.resolve(resource)
                    # Re-read immediately before each mutation, including identity.
                    again = adapter.plan(resource)
                    again.adapter, again.dependencies = change.adapter, change.dependencies
                    if digest(again.model_dump()) != digest(change.model_dump()):
                        raise ValueError("Stale plan: resource drift immediately before write")
                    evidence = {"document_name": document.name, "document_version": document.version,
                                "document_hash": plan.document_hash, "plan_hash": plan.plan_hash,
                                "resource_id": resource.id, "provider": resource.provider, "kind": resource.kind,
                                "before_hash": digest(change.current), "desired_hash": digest(change.desired),
                                "action": change.action, "risk": change.risk}
                    if hasattr(adapter, "intent_evidence"):
                        evidence.update(adapter.intent_evidence(resource, change))
                    # This durable intent is committed BEFORE the network call. A
                    # crash leaves manual evidence even if the provider accepted it.
                    self.journal.record("started", key, evidence, actor)
                    try:
                        result = adapter.apply(resource, change)
                        if result.status == "completed":
                            verified = adapter.plan(resource)
                            if verified.action != "noop":
                                result = DesiredApplyResult(resource_id=resource.id, action=change.action,
                                    status="manual", changed=result.changed, result=result.result,
                                    error="Post-apply verification failed; human reconciliation required")
                    except Exception as exc:
                        result = DesiredApplyResult(resource_id=resource.id, action=change.action,
                            status="manual", changed=False, error="Provider outcome requires reconciliation: " + type(exc).__name__)
                    result.result = normalize(result.result)
                    result.error = normalize(result.error)
                    evidence.update(result=result.model_dump(mode="json"), verification=result.status == "completed")
                    self.journal.record("verified" if result.status == "completed" else "manual", key, evidence, actor)
                results.append(result)
                if result.status != "completed":
                    failed.add(resource.id)
            self.journal.record("apply_result", document.name,
                {"document_hash": plan.document_hash, "plan_hash": plan.plan_hash,
                 "version": document.version, "results": [r.model_dump(mode="json") for r in results]}, actor)
            return results

    @staticmethod
    def _dependency_order(document: DesiredStateDocument, changes: list[DesiredChange]) -> list[DesiredChange]:
        by_id = {change.resource_id: change for change in changes}
        resource_deps = {
            resource.id: [dep for dep in resource.depends_on if dep in by_id]
            for resource in document.resources
            if resource.id in by_id
        }
        ordered: list[DesiredChange] = []
        temporary: set[str] = set()
        permanent: set[str] = set()

        def visit(resource_id: str) -> None:
            if resource_id in permanent:
                return
            if resource_id in temporary:
                raise ValueError(f"Desired-state dependency cycle detected at {resource_id}")
            temporary.add(resource_id)
            for dep in resource_deps.get(resource_id, []):
                visit(dep)
            temporary.remove(resource_id)
            permanent.add(resource_id)
            ordered.append(by_id[resource_id])

        for change in changes:
            visit(change.resource_id)
        return ordered
