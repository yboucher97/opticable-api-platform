from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any

import httpx
import jwt

from .config import GithubSettings


class GithubApiError(RuntimeError):
    pass


class GithubApiClient:
    BASE = "https://api.github.com"

    def __init__(self, settings: GithubSettings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._installation_token: str | None = None
        self._installation_token_expires_at = 0.0

    @property
    def app_configured(self) -> bool:
        path = self.settings.private_key_path
        return bool(self.settings.app_id and self.settings.installation_id and path and path.is_file())

    @property
    def configured(self) -> bool:
        return bool(self.settings.owner and (self.app_configured or self.settings.api_token))

    @property
    def auth_mode(self) -> str:
        if self.app_configured:
            return "github_app"
        if self.settings.api_token:
            return "static_token"
        return "unconfigured"

    def _allowed(self, path: str) -> bool:
        owner = self.settings.owner.strip()
        return (
            path == "/user"
            or path == "/rate_limit"
            or path == "/user/repos"
            or path == "/installation/repositories"
            or path.startswith(f"/repos/{owner}/")
        )

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OptiBrain",
        }

    def _app_jwt(self) -> str:
        if not self.app_configured:
            raise GithubApiError("GitHub App credentials are not fully configured.")
        assert self.settings.private_key_path is not None
        now = int(time.time())
        key_text = self.settings.private_key_path.read_text(encoding="utf-8")
        token = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(self.settings.app_id)}, key_text, algorithm="RS256")
        return token if isinstance(token, str) else token.decode("utf-8")

    def _refresh_installation_token(self) -> str:
        response = httpx.post(
            f"{self.BASE}/app/installations/{self.settings.installation_id}/access_tokens",
            headers=self._headers(self._app_jwt()),
            json={},
            timeout=httpx.Timeout(float(self.settings.timeout_seconds), connect=20.0),
        )
        try:
            data: Any = response.json()
        except json.JSONDecodeError:
            data = response.text
        if not response.is_success or not isinstance(data, dict) or not data.get("token"):
            raise GithubApiError(f"GitHub App token request failed HTTP {response.status_code}: {str(data)[:2000]}")
        expires_raw = str(data.get("expires_at") or "")
        try:
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            expires_at = time.time() + 3000
        self._installation_token = str(data["token"])
        self._installation_token_expires_at = expires_at
        return self._installation_token

    def _auth_token(self) -> str:
        if self.app_configured:
            with self._lock:
                if self._installation_token and time.time() < self._installation_token_expires_at - 300:
                    return self._installation_token
                return self._refresh_installation_token()
        if self.settings.api_token:
            return self.settings.api_token
        raise GithubApiError("GitHub API authentication is not configured on OptiBrain.")

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
            headers=self._headers(self._auth_token()),
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
            "auth_mode": self.auth_mode,
            "accepted_permissions": response.headers.get("X-Accepted-GitHub-Permissions"),
        }
        if not response.is_success:
            raise GithubApiError(f"GitHub API returned HTTP {response.status_code}: {str(data)[:2000]}")
        return result
