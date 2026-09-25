from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    api_version: str = "opticable.io/v1alpha1"
    kind: str = "DesiredState"
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    description: str | None = None
    resources: list[DesiredResource] = Field(default_factory=list)

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
    def __init__(self, registry: DesiredStateRegistry) -> None:
        self.registry = registry

    @staticmethod
    def load(path: Path) -> DesiredStateDocument:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return DesiredStateDocument.model_validate(raw)

    def plan(self, document: DesiredStateDocument) -> DesiredPlan:
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

            change = adapter.plan(resource)
            change.adapter = getattr(adapter, "name", adapter.__class__.__name__)
            change.dependencies = resource.depends_on
            changes.append(change)

        ordered = self._dependency_order(document, changes)
        counts: dict[str, int] = {}
        for change in ordered:
            counts[change.action] = counts.get(change.action, 0) + 1

        return DesiredPlan(
            document_name=document.name,
            document_version=document.version,
            changes=ordered,
            summary=counts,
        )

    def apply(
        self,
        document: DesiredStateDocument,
        plan: DesiredPlan,
        *,
        allow_destructive: bool = False,
        allow_high_risk: bool = False,
    ) -> list[DesiredApplyResult]:
        resources = {resource.id: resource for resource in document.resources}
        results: list[DesiredApplyResult] = []
        failed: set[str] = set()

        for change in plan.changes:
            resource = resources.get(change.resource_id)
            if resource is None:
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action=change.action,
                        status="failed",
                        changed=False,
                        error="Resource is absent from the desired-state document.",
                    )
                )
                failed.add(change.resource_id)
                continue

            if any(dep in failed for dep in change.dependencies):
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action=change.action,
                        status="blocked",
                        changed=False,
                        error="A dependency failed earlier in the apply.",
                    )
                )
                failed.add(change.resource_id)
                continue

            if change.action == "noop":
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action="noop",
                        status="completed",
                        changed=False,
                    )
                )
                continue

            if change.action in {"manual", "blocked"}:
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action=change.action,
                        status=change.action,
                        changed=False,
                        error=change.reason if change.action == "blocked" else None,
                    )
                )
                if change.action == "blocked":
                    failed.add(change.resource_id)
                continue

            if change.risk == "destructive" and not allow_destructive:
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action=change.action,
                        status="blocked",
                        changed=False,
                        error="Destructive change requires allow_destructive=true.",
                    )
                )
                failed.add(change.resource_id)
                continue

            if change.risk == "high" and not allow_high_risk:
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action=change.action,
                        status="blocked",
                        changed=False,
                        error="High-risk change requires allow_high_risk=true.",
                    )
                )
                failed.add(change.resource_id)
                continue

            adapter = self.registry.resolve(resource)
            if adapter is None:
                results.append(
                    DesiredApplyResult(
                        resource_id=change.resource_id,
                        action=change.action,
                        status="manual",
                        changed=False,
                    )
                )
                continue

            try:
                result = adapter.apply(resource, change)
            except Exception as exc:
                result = DesiredApplyResult(
                    resource_id=change.resource_id,
                    action=change.action,
                    status="failed",
                    changed=False,
                    error=str(exc),
                )
            results.append(result)
            if result.status != "completed":
                failed.add(change.resource_id)

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
