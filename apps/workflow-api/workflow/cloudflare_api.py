from __future__ import annotations

import json
from typing import Any

import httpx

from .config import CloudflareSettings


class CloudflareApiError(RuntimeError):
    pass


_COST_PATH_FRAGMENTS = ("/billing", "/subscriptions", "/payment", "/registrar")


class CloudflareApiClient:
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, settings: CloudflareSettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.api_token and self.settings.account_id)

    def request(self, path: str, method: str = "GET", *, params: dict[str, Any] | None = None, body: Any = None) -> dict[str, Any]:
        if not self.configured:
            raise CloudflareApiError("Cloudflare API token/account ID are not configured.")
        path = str(path or "").strip()
        if not path.startswith("/") or path.startswith("//") or "\\" in path or "\r" in path or "\n" in path:
            raise ValueError("Invalid Cloudflare API path.")
        lower = path.lower()
        if any(fragment in lower for fragment in _COST_PATH_FRAGMENTS):
            raise CloudflareApiError("Cloudflare billing/subscription/registrar operations require an explicit payment approval path.")
        method = str(method or "GET").upper().strip()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported Cloudflare method: {method}")
        response = httpx.request(
            method,
            self.BASE + path,
            params=params or {},
            json=body if body is not None and method not in {"GET", "DELETE"} else None,
            headers={
                "Authorization": f"Bearer {self.settings.api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        try:
            data: Any = response.json()
        except json.JSONDecodeError:
            data = response.text
        result = {"ok": response.is_success, "status": response.status_code, "data": data}
        if not response.is_success:
            raise CloudflareApiError(f"Cloudflare API returned HTTP {response.status_code}: {str(data)[:2000]}")
        return result
