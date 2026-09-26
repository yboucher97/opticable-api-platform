from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import httpx

from .config import ZohoGatewaySettings
from .zoho_oauth import ZohoOAuthManager


class ZohoGatewayError(RuntimeError):
    pass


def is_books_api_path(service: str, path: str) -> bool:
    return service == "zohoapis" and str(path or "").lower().startswith("/books/")


_BOOKS_SYNCED_CRM_MODULES = {"custommodule5001", "custommodule5002", "custommodule5003", "custommodule5004"}


def is_books_synced_crm_path(service: str, path: str) -> bool:
    if service != "zohoapis":
        return False
    parts = [part.casefold() for part in str(path or "").strip("/").split("/")]
    return len(parts) >= 3 and parts[0] == "crm" and parts[1].startswith("v") and parts[2] in _BOOKS_SYNCED_CRM_MODULES


ZOHO_API_SERVICES = {
    "zohoapis": ("https://www.zohoapis.com/", "", "Zoho-oauthtoken"),
    "mail": ("https://mail.zoho.com/", "", "Zoho-oauthtoken"),
    "forms": ("https://forms.zoho.com/", "", "Bearer"),
    "writer": ("https://www.zohoapis.com/", "writer/", "Zoho-oauthtoken"),
    "sign": ("https://sign.zoho.com/", "api/v1/", "Zoho-oauthtoken"),
    "projects": ("https://projects.zoho.com/", "", "Bearer"),
    "desk": ("https://desk.zoho.com/", "", "Zoho-oauthtoken"),
    "creator": ("https://www.zohoapis.com/", "creator/v2.1/", "Zoho-oauthtoken"),
    "calendar": ("https://calendar.zoho.com/", "api/v1/", "Zoho-oauthtoken"),
    "cliq": ("https://cliq.zoho.com/", "api/v2/", "Zoho-oauthtoken"),
    "meeting": ("https://meeting.zoho.com/", "api/v2/", "Zoho-oauthtoken"),
    "people": ("https://people.zoho.com/", "people/api/", "Zoho-oauthtoken"),
    "recruit": ("https://recruit.zoho.com/", "recruit/v2/", "Zoho-oauthtoken"),
    "fsm": ("https://fsm.zoho.com/", "fsm/v1/", "Zoho-oauthtoken"),
    "contracts": ("https://contracts.zoho.com/", "api/v1/", "Zoho-oauthtoken"),
    "analytics": ("https://analyticsapi.zoho.com/", "restapi/v2/", "Zoho-oauthtoken"),
    "salesiq": ("https://salesiq.zoho.com/", "api/v2/", "Zoho-oauthtoken"),
    "campaigns": ("https://campaigns.zoho.com/", "api/v1.1/", "Zoho-oauthtoken"),
    "marketingautomation": ("https://marketingautomation.zoho.com/", "api/v1/", "Zoho-oauthtoken"),
    "commerce": ("https://commerce.zoho.com/", "", "Zoho-oauthtoken"),
    "tables": ("https://tables.zoho.com/", "api/v1/", "Zoho-oauthtoken"),
    "vault": ("https://vault.zoho.com/", "api/rest/json/v1/", "Zoho-oauthtoken"),
    "connect": ("https://connect.zoho.com/", "pulse/api/", "Zoho-oauthtoken"),
    "dataprep": ("https://www.zohoapis.com/", "dataprep/v1/", "Zoho-oauthtoken"),
}


class ZohoGatewayClient:
    """Canonical Zoho provider client for OptiBrain.

    Local OAuth on optibrain.opticable.ca is primary. connect.opticable.ca is
    retained only as an explicitly enabled standby for manual disaster recovery.
    """

    def __init__(self, settings: ZohoGatewaySettings, oauth: ZohoOAuthManager) -> None:
        self.settings = settings
        self.oauth = oauth

    @property
    def configured(self) -> bool:
        status = self.oauth.status()
        return bool(status.configured and status.connected)

    def _validate(
        self,
        service: str,
        method: str,
        path: str,
        headers: dict[str, Any] | None,
        reason: str | None,
        confirm: bool | None,
        books_human_approved: bool | None = None,
    ) -> tuple[str, dict[str, str]]:
        normalized_method = str(method or "GET").upper().strip()
        if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported Zoho method: {normalized_method}")
        if service not in ZOHO_API_SERVICES:
            raise ValueError(f"Unsupported Zoho API service: {service}")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Zoho path must be a relative API path beginning with '/'.")
        if "\\" in path or "\r" in path or "\n" in path:
            raise ValueError("Zoho path contains unsafe characters.")

        mutation = normalized_method != "GET"
        books_protected = is_books_api_path(service, path) or is_books_synced_crm_path(service, path)
        if mutation and books_protected and books_human_approved is not True:
            raise ZohoGatewayError(
                "Zoho Books is read-only by default. This mutation requires explicit human approval "
                "for the specific action (books_human_approved=True)."
            )
        if mutation and not (reason or "").strip():
            raise ValueError("Zoho mutations require a human-readable reason.")
        if mutation and confirm is not True:
            raise ValueError("Zoho mutations require confirm=True.")

        blocked = {
            "authorization", "cookie", "host", "content-length",
            "connection", "proxy-authorization", "x-api-key",
        }
        safe_headers = {
            str(key): str(value)
            for key, value in (headers or {}).items()
            if str(key).lower().strip() not in blocked
        }
        return normalized_method, safe_headers

    def _local_request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        query: dict[str, Any],
        headers: dict[str, str],
        body: Any,
        content_type: str,
    ) -> dict[str, Any]:
        origin, prefix, auth_scheme = ZOHO_API_SERVICES[service]
        clean_path = path.lstrip("/")
        url = urljoin(origin, f"{prefix}{clean_path}")
        if httpx.URL(url).host != httpx.URL(origin).host:
            raise ValueError("Zoho API request escaped the approved service host.")

        request_headers = {
            "Authorization": f"{auth_scheme} {self.oauth.access_token()}",
            "Accept": "application/json",
            **headers,
        }
        kwargs: dict[str, Any] = {
            "params": query,
            "headers": request_headers,
            "timeout": httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        }
        if body is not None and method not in {"GET", "DELETE"}:
            if content_type == "application/x-www-form-urlencoded" and isinstance(body, dict):
                kwargs["data"] = {str(k): str(v) for k, v in body.items()}
            elif content_type == "text/plain":
                kwargs["content"] = body if isinstance(body, str) else json.dumps(body)
            else:
                kwargs["json"] = body
            request_headers["Content-Type"] = content_type

        response = httpx.request(method, url, **kwargs)
        content_type_response = response.headers.get("content-type", "")
        try:
            data: Any = response.json()
        except json.JSONDecodeError:
            data = response.text
        result = {
            "ok": response.is_success,
            "status": response.status_code,
            "content_type": content_type_response or None,
            "request_id": response.headers.get("x-request-id")
            or response.headers.get("x-com-zoho-requestid"),
            "data": data,
            "provider_path": "local",
        }
        if not response.is_success:
            raise ZohoGatewayError(
                f"Zoho {service} API returned HTTP {response.status_code}: {json.dumps(data)[:2000]}"
            )
        return result

    def _standby_request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        query: dict[str, Any],
        headers: dict[str, str],
        body: Any,
        content_type: str,
        reason: str | None,
        confirm: bool | None,
        books_human_approved: bool | None,
    ) -> dict[str, Any]:
        if not self.settings.standby_enabled:
            raise ZohoGatewayError("connect.opticable.ca standby is disabled.")
        if not self.settings.base_url or not self.settings.api_key:
            raise ZohoGatewayError("connect.opticable.ca standby credentials are not configured.")

        payload: dict[str, Any] = {
            "service": service,
            "method": method,
            "path": path,
            "query": query,
            "headers": headers,
            "content_type": content_type,
        }
        if body is not None:
            payload["body"] = body
        if method != "GET":
            payload["reason"] = str(reason or "").strip()
            payload["confirm"] = bool(confirm)
            if is_books_api_path(service, path) or is_books_synced_crm_path(service, path):
                payload["books_human_approved"] = books_human_approved is True

        response = httpx.post(
            f"{self.settings.base_url}/internal/v1/zoho/request",
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
                f"Standby Zoho gateway returned HTTP {response.status_code}: {json.dumps(data)[:2000]}"
            )
        if isinstance(data, dict):
            data["provider_path"] = "connect_standby"
        return data

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
        books_human_approved: bool | None = None,
    ) -> dict[str, Any]:
        normalized_method, safe_headers = self._validate(
            service, method, path, headers, reason, confirm, books_human_approved
        )
        try:
            if not self.configured:
                raise ZohoGatewayError("Local Zoho OAuth is not configured and connected.")
            return self._local_request(
                service,
                normalized_method,
                path,
                query=query or {},
                headers=safe_headers,
                body=body,
                content_type=content_type,
            )
        except Exception:
            if not self.settings.standby_enabled:
                raise
            return self._standby_request(
                service,
                normalized_method,
                path,
                query=query or {},
                headers=safe_headers,
                body=body,
                content_type=content_type,
                reason=reason,
                confirm=confirm,
                books_human_approved=books_human_approved,
            )
