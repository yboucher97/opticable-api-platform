from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import GoogleOAuthSettings
from .utils import ensure_directory, utc_iso


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class GoogleConnectionStatus:
    configured: bool
    connected: bool
    redirect_uri: str | None
    scopes: tuple[str, ...]
    credentials_path: Path
    connected_at: str | None
    granted_scope: str | None
    has_refresh_token: bool
    client_id_suffix: str | None


class GoogleOAuthManager:
    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, settings: GoogleOAuthSettings) -> None:
        self.settings = settings
        self._token_lock = threading.Lock()
        self._cached_access_token: str | None = None
        self._cached_access_token_expires_at = 0.0

    def build_state(self) -> str:
        payload = {
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "nonce": secrets.token_urlsafe(16),
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_token = _b64url_encode(payload_bytes)
        signature = hmac.new(
            self.settings.state_secret.encode("utf-8"),
            payload_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return f"{payload_token}.{_b64url_encode(signature)}"

    def validate_state(self, state: str) -> None:
        if "." not in state:
            raise ValueError("Missing Google OAuth state signature.")
        payload_token, signature_token = state.split(".", 1)
        expected = hmac.new(
            self.settings.state_secret.encode("utf-8"),
            payload_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        provided = _b64url_decode(signature_token)
        if not hmac.compare_digest(expected, provided):
            raise ValueError("Invalid Google OAuth state signature.")
        payload = json.loads(_b64url_decode(payload_token).decode("utf-8"))
        issued_at = int(payload.get("iat", 0))
        age_seconds = int(datetime.now(timezone.utc).timestamp()) - issued_at
        if issued_at <= 0 or age_seconds > self.settings.state_ttl_seconds:
            raise ValueError("Google OAuth state has expired. Start the connection again.")

    def build_authorization_redirect(self) -> str:
        if not self.settings.enabled or not self.settings.redirect_uri or not self.settings.client_id:
            raise ValueError("Google OAuth is not configured. Set client id, client secret, and redirect URI first.")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri,
                "scope": " ".join(self.settings.scopes),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": self.build_state(),
            }
        )
        return f"{self.AUTHORIZATION_URL}?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        if not self.settings.enabled or not self.settings.redirect_uri:
            raise ValueError("Google OAuth is not configured.")
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0)) as client:
            response = client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "redirect_uri": self.settings.redirect_uri,
                },
            )
        if response.status_code >= 400:
            raise ValueError(f"Google token exchange failed with status {response.status_code}: {response.text}")
        payload = response.json()
        if not payload.get("access_token"):
            raise ValueError(f"Google token exchange did not return an access token: {payload}")
        return payload

    def load_saved_credentials(self) -> dict[str, Any] | None:
        path = self.settings.credentials_path
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Google credential file format: {path}")
        return payload

    def save_credentials(self, payload: dict[str, Any]) -> Path:
        target = self.settings.credentials_path
        ensure_directory(target.parent)
        existing = self.load_saved_credentials() or {}
        refresh_token = payload.get("refresh_token") or existing.get("refresh_token")
        expires_in = int(payload.get("expires_in") or 3600)
        persisted = {
            "provider": "google",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "connected_at": utc_iso(),
            "scope": payload.get("scope") or existing.get("scope") or " ".join(self.settings.scopes),
            "refresh_token": refresh_token,
            "access_token": payload.get("access_token"),
            "access_token_expires_at": int(time.time()) + expires_in,
            "token_type": payload.get("token_type", "Bearer"),
            "expires_in": expires_in,
        }
        target.write_text(json.dumps(persisted, indent=2) + "\n", encoding="utf-8")
        target.chmod(0o640)
        self._cached_access_token = str(payload["access_token"])
        self._cached_access_token_expires_at = time.time() + max(60, expires_in - 60)
        return target

    def access_token(self) -> str:
        now = time.time()
        if self._cached_access_token and self._cached_access_token_expires_at > now:
            return self._cached_access_token
        with self._token_lock:
            now = time.time()
            if self._cached_access_token and self._cached_access_token_expires_at > now:
                return self._cached_access_token
            saved = self.load_saved_credentials()
            if not saved:
                raise ValueError("Google is not connected yet.")

            saved_token = str(saved.get("access_token") or "")
            saved_expiry = float(saved.get("access_token_expires_at") or 0)
            if saved_token and saved_expiry > now + 60:
                self._cached_access_token = saved_token
                self._cached_access_token_expires_at = saved_expiry
                return saved_token

            refresh_token = str(saved.get("refresh_token") or "")
            if not refresh_token:
                raise ValueError("Google OAuth refresh token is missing. Reauthorize with offline access.")

            with httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0)) as client:
                response = client.post(
                    self.TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": self.settings.client_id,
                        "client_secret": self.settings.client_secret,
                    },
                )
            if response.status_code >= 400:
                raise ValueError(f"Google token refresh failed with status {response.status_code}: {response.text}")
            payload = response.json()
            access_token = str(payload.get("access_token") or "")
            if not access_token:
                raise ValueError(f"Google token refresh did not return an access token: {payload}")

            expires_in = int(payload.get("expires_in") or 3600)
            saved["access_token"] = access_token
            saved["access_token_expires_at"] = int(time.time()) + expires_in
            saved["expires_in"] = expires_in
            self.settings.credentials_path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
            self.settings.credentials_path.chmod(0o640)
            self._cached_access_token = access_token
            self._cached_access_token_expires_at = time.time() + max(60, expires_in - 60)
            return access_token

    def status(self) -> GoogleConnectionStatus:
        saved = self.load_saved_credentials()
        client_id = (self.settings.client_id or "").strip()
        return GoogleConnectionStatus(
            configured=self.settings.enabled,
            connected=bool(saved and saved.get("refresh_token")),
            redirect_uri=self.settings.redirect_uri,
            scopes=self.settings.scopes,
            credentials_path=self.settings.credentials_path,
            connected_at=str(saved.get("connected_at")) if saved else None,
            granted_scope=str(saved.get("scope")) if saved and saved.get("scope") else None,
            has_refresh_token=bool(saved and saved.get("refresh_token")),
            client_id_suffix=client_id[-12:] if client_id else None,
        )
