from __future__ import annotations

import json
from typing import Any

import httpx

from .config import ApolloSettings


class ApolloApiError(RuntimeError):
    pass


_CREDIT_RISK = ("enrich", "bulk", "organization_search", "people/match")


class ApolloApiClient:
    BASE = "https://api.apollo.io/api/v1"

    def __init__(self, settings: ApolloSettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.api_key)

    def request(self, path: str, method: str = "GET", *, params: dict[str, Any] | None = None, body: Any = None) -> dict[str, Any]:
        if not self.configured:
            raise ApolloApiError("Apollo API key is not configured on OptiBrain.")
        path = str(path or "").strip()
        if not path.startswith("/") or path.startswith("//") or "\\" in path or "\r" in path or "\n" in path:
            raise ValueError("Invalid Apollo API path.")
        if any(fragment in path.lower() for fragment in _CREDIT_RISK) and not self.settings.allow_credit_consumption:
            raise ApolloApiError(
                "Apollo endpoint may consume enrichment credits; enable OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION only after explicit approval."
            )
        method = str(method or "GET").upper().strip()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported Apollo method: {method}")
        response = httpx.request(
            method,
            self.BASE + path,
            params=params or {},
            json=body if body is not None and method not in {"GET", "DELETE"} else None,
            headers={
                "x-api-key": str(self.settings.api_key),
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        try:
            data: Any = response.json()
        except json.JSONDecodeError:
            data = response.text
        result = {"ok": response.is_success, "status": response.status_code, "data": data}
        if not response.is_success:
            raise ApolloApiError(f"Apollo API returned HTTP {response.status_code}: {str(data)[:2000]}")
        return result
