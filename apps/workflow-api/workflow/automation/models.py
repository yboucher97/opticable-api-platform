from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=5)
    backoff_seconds: float = Field(default=0.0, ge=0.0, le=30.0)


class WorkflowTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_types: list[str] = Field(min_length=1)
    sources: list[str] | None = None

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("At least one event type is required.")
        return normalized


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    inputs: dict[str, Any] = Field(default_factory=dict, alias="with")
    on_error: Literal["stop", "continue"] = "stop"
    retry: RetryPolicy = Field(default_factory=RetryPolicy)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    enabled: bool = True
    description: str | None = None
    trigger: WorkflowTrigger
    steps: list[WorkflowStep] = Field(min_length=1)


class AutomationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    source: str = Field(min_length=1, max_length=128)
    occurred_at: str = Field(default_factory=utc_now_iso)
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)
    depth: int = Field(default=0, ge=0, le=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventIngestResponse(BaseModel):
    accepted: bool
    duplicate: bool
    event_id: str
    correlation_id: str
    run_ids: list[str] = Field(default_factory=list)


class WorkflowRunSummary(BaseModel):
    run_id: str
    workflow_id: str
    event_id: str
    correlation_id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class CapabilityRecord(BaseModel):
    provider: str
    product: str
    capability: str
    grade: Literal["A", "B", "C", "D", "E", "F"]
    score: int = Field(ge=0, le=100)
    access_mode: str
    status: str
    notes: str | None = None
    next_action: str | None = None
