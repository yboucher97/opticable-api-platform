from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import httpx

from .google_oauth import GoogleOAuthManager


class GoogleApiError(RuntimeError):
    pass


SERVICE_BASES = {
    "tagmanager": "https://tagmanager.googleapis.com/tagmanager/v2/",
    "analytics_admin_v1beta": "https://analyticsadmin.googleapis.com/v1beta/",
    "analytics_admin_v1alpha": "https://analyticsadmin.googleapis.com/v1alpha/",
}


class GoogleApiClient:
    def __init__(self, oauth: GoogleOAuthManager) -> None:
        self.oauth = oauth

    def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        base = SERVICE_BASES.get(service)
        if base is None:
            raise ValueError(f"Unsupported Google API service: {service}")

        normalized_method = method.upper().strip()
        if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported Google API method: {normalized_method}")

        clean_path = path.strip().lstrip("/")
        path_segments = [segment for segment in clean_path.split("/") if segment]
        if (
            not clean_path
            or "\\" in clean_path
            or "\r" in clean_path
            or "\n" in clean_path
            or clean_path.lower().startswith(("http:", "https:"))
            or any(segment in {".", ".."} for segment in path_segments)
        ):
            raise ValueError("Google API path must be a safe relative API resource path.")

        url = urljoin(base, clean_path)
        allowed_origin = httpx.URL(base).host
        if httpx.URL(url).host != allowed_origin:
            raise ValueError("Google API request escaped the approved service host.")

        safe_headers = {"Accept": "application/json"}
        for key, value in (headers or {}).items():
            if key.lower() in {"authorization", "cookie", "host", "content-length", "x-api-key"}:
                continue
            safe_headers[str(key)] = str(value)
        safe_headers["Authorization"] = f"Bearer {self.oauth.access_token()}"

        request_kwargs: dict[str, Any] = {
            "params": params or {},
            "headers": safe_headers,
            "timeout": httpx.Timeout(60.0, connect=20.0),
        }
        if body is not None and normalized_method not in {"GET", "DELETE"}:
            request_kwargs["json"] = body

        response = httpx.request(normalized_method, url, **request_kwargs)
        content_type = response.headers.get("content-type", "")
        data: Any
        if "json" in content_type.lower():
            data = response.json()
        else:
            text = response.text
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = text

        result = {
            "ok": response.is_success,
            "status": response.status_code,
            "content_type": content_type or None,
            "request_id": response.headers.get("x-guploader-uploadid")
            or response.headers.get("x-request-id"),
            "data": data,
        }
        if not response.is_success:
            raise GoogleApiError(
                f"Google {service} API returned HTTP {response.status_code}: {json.dumps(data)[:2000]}"
            )
        return result
