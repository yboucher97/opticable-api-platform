from __future__ import annotations

import json
from typing import Any

import httpx

from .config import GithubSettings


class GithubApiError(RuntimeError):
    pass


class GithubApiClient:
    BASE = "https://api.github.com"

    def __init__(self, settings: GithubSettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.api_token and self.settings.owner)

    def _allowed(self, path: str) -> bool:
        owner = self.settings.owner.strip()
        return (
            path == "/user"
            or path == "/rate_limit"
            or path == "/user/repos"
            or path.startswith(f"/repos/{owner}/")
        )

    def request(self, path: str, method: str = "GET", *, params: dict[str, Any] | None = None, body: Any = None) -> dict[str, Any]:
        if not self.configured:
            raise GithubApiError("GitHub API token is not configured on OptiBrain.")
        path = str(path or "").strip()
        if not path.startswith("/") or path.startswith("//") or "\\" in path or "\r" in path or "\n" in path:
            raise ValueError("Invalid GitHub API path.")
        if not self._allowed(path):
            raise GithubApiError(f"GitHub path is outside configured owner {self.settings.owner}.")
        method = str(method or "GET").upper().strip()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported GitHub method: {method}")
        response = httpx.request(
            method,
            self.BASE + path,
            params=params or {},
            json=body if body is not None and method not in {"GET", "DELETE"} else None,
            headers={
                "Authorization": f"Bearer {self.settings.api_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "OptiBrain",
            },
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        try:
            data: Any = response.json()
        except json.JSONDecodeError:
            data = response.text
        result = {
            "ok": response.is_success,
            "status": response.status_code,
            "data": data,
            "accepted_permissions": response.headers.get("X-Accepted-GitHub-Permissions"),
        }
        if not response.is_success:
            raise GithubApiError(f"GitHub API returned HTTP {response.status_code}: {str(data)[:2000]}")
        return result
