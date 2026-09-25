from __future__ import annotations

import json
from typing import Any

import httpx

from .config import ZohoGatewaySettings


class ZohoGatewayError(RuntimeError):
    pass


class ZohoGatewayClient:
    """Client for the centralized Opticable Zoho provider gateway.

    The gateway owns the Zoho refresh token and scope lifecycle. This service
    only receives a server-to-server API key and never stores Zoho OAuth
    client secrets or refresh tokens.
    """

    def __init__(self, settings: ZohoGatewaySettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.base_url and self.settings.api_key)

    def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        body: Any = None,
        content_type: str = "application/json",
        reason: str | None = None,
        confirm: bool | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise ZohoGatewayError("Central Zoho gateway is not configured.")

        normalized_method = str(method or "GET").upper().strip()
        if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported Zoho method: {normalized_method}")

        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Zoho path must be a relative API path beginning with '/'.")
        if "\\\\" in path or "\\r" in path or "\\n" in path:
            raise ValueError("Zoho path contains unsafe characters.")

        mutation = normalized_method != "GET"
        if mutation and not (reason or "").strip():
            raise ValueError("Zoho mutations require a human-readable reason.")
        if mutation and confirm is not True:
            raise ValueError("Zoho mutations require confirm=True.")

        safe_headers: dict[str, str] = {}
        blocked = {
            "authorization", "cookie", "host", "content-length",
            "connection", "proxy-authorization", "x-api-key",
        }
        for key, value in (headers or {}).items():
            if str(key).lower().strip() in blocked:
                continue
            safe_headers[str(key)] = str(value)

        payload: dict[str, Any] = {
            "service": service,
            "method": normalized_method,
            "path": path,
            "query": query or {},
            "headers": safe_headers,
            "content_type": content_type,
        }
        if body is not None:
            payload["body"] = body
        if mutation:
            payload["reason"] = str(reason).strip()
            payload["confirm"] = True

        url = f"{self.settings.base_url}/internal/v1/zoho/request"
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )

        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"raw": response.text}

        if not response.is_success:
            raise ZohoGatewayError(
                f"Zoho gateway returned HTTP {response.status_code}: {json.dumps(data)[:2000]}"
            )

        if not isinstance(data, dict):
            raise ZohoGatewayError("Zoho gateway returned an unexpected response.")
        if data.get("ok") is False:
            raise ZohoGatewayError(
                f"Zoho provider returned HTTP {data.get('status')}: {json.dumps(data.get('data'))[:2000]}"
            )
        return data
