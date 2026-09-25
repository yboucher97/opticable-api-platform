from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import WindsorSettings


class WindsorApiError(RuntimeError):
    pass


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
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data: Any = response.json()
        except json.JSONDecodeError:
            data = response.text
        result = {"ok": response.is_success, "status": response.status_code, "data": data}
        if not response.is_success:
            raise WindsorApiError(f"Windsor API returned HTTP {response.status_code}: {str(data)[:2000]}")
        return result
