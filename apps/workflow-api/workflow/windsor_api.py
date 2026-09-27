from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import WindsorSettings


class WindsorApiError(RuntimeError):
    def __init__(self, message: str, *, response: httpx.Response | None = None) -> None:
        super().__init__(message)
        self.response = response


class WindsorWriteUnconfirmedError(WindsorApiError):
    """A sent write has no trustworthy success evidence; never retry it blindly."""

    ambiguous_external_write = True


_SAFE_CONNECTOR = re.compile(r"^[a-z0-9_]+$")


class WindsorApiClient:
    def __init__(self, settings: WindsorSettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.api_key)

    def _connector(self, connector: str) -> str:
        value = str(connector or "").strip().lower()
        if not _SAFE_CONNECTOR.fullmatch(value):
            raise ValueError("Invalid Windsor connector id.")
        return value

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.api_key:
            raise WindsorApiError("WINDSOR_API_KEY is not configured.")
        return {"api_key": self.settings.api_key, **(extra or {})}

    def read(self, connector: str, *, fields: list[str], params: dict[str, Any] | None = None) -> dict[str, Any]:
        connector = self._connector(connector)
        if not fields or not all(isinstance(x, str) and x.strip() for x in fields):
            raise ValueError("windsor.read requires a non-empty fields list.")
        query = self._params({**(params or {}), "fields": ",".join(x.strip() for x in fields)})
        response = httpx.get(
            f"{self.settings.base_url}/{connector}",
            params=query,
            headers={"Accept": "application/json", "User-Agent": "OptiBrain/1.0"},
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        return self._parse(response)

    def list_actions(self, connector: str) -> dict[str, Any]:
        connector = self._connector(connector)
        response = httpx.get(
            f"{self.settings.base_url}/{connector}/actions",
            params=self._params(),
            headers={"Accept": "application/json", "User-Agent": "OptiBrain/1.0"},
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        return self._parse(response)

    def execute_action(self, connector: str, *, account: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        connector = self._connector(connector)
        if not account or not action:
            raise ValueError("Windsor actions require account and action.")
        response = httpx.post(
            f"{self.settings.base_url}/{connector}/actions",
            params=self._params(),
            headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "OptiBrain/1.0"},
            json={"account": account, "action": action, "params": params or {}},
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        return self._parse(response, require_write_confirmation=True)

    @staticmethod
    def _confirmed_write(data: Any) -> bool:
        # Windsor documents a nonempty JSON "result" string for a successful
        # action. Other shapes need action-specific proof before confirmation.
        if not isinstance(data, dict) or "result" not in data:
            return False
        result = data["result"]
        if not isinstance(result, str) or not result.strip():
            return False
        lowered = result.strip().lower()
        normalized_status = data.get("status", "")
        if isinstance(normalized_status, str):
            normalized_status = re.sub(r"[\s-]+", "_", normalized_status.strip().casefold())
        else:
            normalized_status = str(normalized_status).strip().casefold()
        if any(marker in lowered for marker in
               ("error", "failed", "failure", "unauthorized", "not authorized",
                "denied", "partial success", "partial_success", "partially completed",
                "incomplete")):
            return False
        if (data.get("partial") is not None and data.get("partial") is not False
                or "error" in data or "errors" in data
                or data.get("failed") is True or data.get("failure")
                or data.get("warning") or data.get("warnings")
                or data.get("success") is False or data.get("ok") is False
                or normalized_status in {
                    "error", "failed", "failure", "unauthorized", "denied",
                    "partial", "partial_success", "partially_completed", "incomplete",
                }):
            return False
        return True

    def _parse(self, response: httpx.Response, *, require_write_confirmation: bool = False) -> dict[str, Any]:
        try:
            data: Any = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = response.text
        if not response.is_success:
            raise WindsorApiError(f"Windsor API returned HTTP {response.status_code}: {str(data)[:2000]}",
                                  response=response)
        if require_write_confirmation:
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if not ((media_type == "application/json" or media_type.endswith("+json"))
                    and self._confirmed_write(data)):
                raise WindsorWriteUnconfirmedError("Windsor write result is unconfirmed", response=response)
        return {"ok": True, "status": response.status_code, "data": data}
