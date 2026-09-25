"""Provider-neutral automation kernel for Opticable."""

from .engine import AutomationEngine
from .models import AutomationEvent, WorkflowDefinition
from .store import AutomationStore

__all__ = ["AutomationEngine", "AutomationEvent", "WorkflowDefinition", "AutomationStore"]
