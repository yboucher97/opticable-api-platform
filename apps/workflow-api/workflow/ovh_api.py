from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import OvhSettings


class OvhApiError(RuntimeError):
    pass


_OVH_BASES = {"ovh-ca": "https://ca.api.ovh.com/1.0"}


class OvhApiClient:
    def __init__(self, settings: OvhSettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.application_key
            and self.settings.application_secret
            and self.settings.consumer_key
            and self.settings.endpoint in _OVH_BASES
        )

    def request(self, path: str, method: str = "GET", *, query: dict[str, Any] | None = None, body: Any = None) -> dict[str, Any]:
        if not self.configured:
            raise OvhApiError("OVH machine credentials are not configured on OptiBrain.")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "\\" in path or "\r" in path or "\n" in path:
            raise ValueError("Invalid OVH API path.")

        method = str(method or "GET").upper().strip()
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise ValueError(f"Unsupported OVH method: {method}")

        base = _OVH_BASES[self.settings.endpoint]
        url = f"{base}{path}"
        if query:
            pairs: list[tuple[str, str]] = []
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    pairs.extend((str(key), str(v)) for v in value)
                else:
                    pairs.append((str(key), str(value)))
            if pairs:
                url += "?" + urlencode(pairs)

        body_text = ""
        if method != "GET" and body is not None:
            body_text = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))

        timestamp = str(int(time.time()))
        signature_input = "+".join([
            str(self.settings.application_secret),
            str(self.settings.consumer_key),
            method,
            url,
            body_text,
            timestamp,
        ])
        digest = hashlib.sha1(signature_input.encode("utf-8")).hexdigest()
        headers = {
            "X-Ovh-Application": str(self.settings.application_key),
            "X-Ovh-Consumer": str(self.settings.consumer_key),
            "X-Ovh-Timestamp": timestamp,
            "X-Ovh-Signature": "$1$" + digest,
            "Accept": "application/json",
        }
        if body_text:
            headers["Content-Type"] = "application/json"

        response = httpx.request(
            method,
            url,
            headers=headers,
            content=body_text or None,
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        text = response.text
        try:
            data: Any = response.json() if text else None
        except json.JSONDecodeError:
            data = text

        result = {"ok": response.is_success, "status": response.status_code, "data": data}
        if not response.is_success:
            raise OvhApiError(f"OVH API returned HTTP {response.status_code}: {str(data)[:2000]}")
        return result
