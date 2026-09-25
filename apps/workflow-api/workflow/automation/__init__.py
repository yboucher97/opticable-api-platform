"""Provider-neutral automation kernel for Opticable."""

from .desired_state import (
    DesiredApplyResult,
    DesiredChange,
    DesiredPlan,
    DesiredResource,
    DesiredStateController,
    DesiredStateDocument,
    DesiredStateRegistry,
)
from .engine import AutomationEngine
from .models import AutomationEvent, WorkflowDefinition
from .store import AutomationStore

__all__ = [
    "AutomationEngine",
    "AutomationEvent",
    "WorkflowDefinition",
    "AutomationStore",
    "DesiredApplyResult",
    "DesiredChange",
    "DesiredPlan",
    "DesiredResource",
    "DesiredStateController",
    "DesiredStateDocument",
    "DesiredStateRegistry",
]
