from __future__ import annotations

import re
from typing import Any


_SAFE_PROVIDER_OPERATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


def provider_operation_id(result: Any) -> str | None:
    """Extract bounded provider evidence without treating it as idempotency.

    A request/operation identifier is useful for reconciliation and audit, but
    callers must never infer that its presence makes a write safe to replay.
    """
    if not isinstance(result, dict):
        return None
    for key in ("provider_operation_id", "request_id", "operation_id"):
        value = result.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if _SAFE_PROVIDER_OPERATION_ID.fullmatch(normalized):
                return normalized
    return None


def attach_provider_operation_id(result: Any) -> Any:
    """Copy a safe provider identifier to the engine's canonical result field."""
    if not isinstance(result, dict):
        return result
    operation_id = provider_operation_id(result)
    if operation_id is None or result.get("provider_operation_id") == operation_id:
        return result
    return {**result, "provider_operation_id": operation_id}
