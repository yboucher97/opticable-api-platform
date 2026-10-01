from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import ZohoOAuthSettings
from .utils import ensure_directory, utc_iso


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True)
class ZohoConnectionStatus:
    configured: bool
    connected: bool
    redirect_uri: str | None
    accounts_base_url: str
    scopes: tuple[str, ...]
    credentials_path: Path
    connected_at: str | None
    scope: str | None
    api_domain: str | None
    has_refresh_token: bool
    client_id_suffix: str | None


class ZohoOAuthManager:
    def __init__(self, settings: ZohoOAuthSettings) -> None:
        self.settings = settings
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._token_lock = threading.Lock()

    @property
    def cache_path(self) -> Path:
        return self.settings.access_cache_path or self.settings.credentials_path.with_name("zoho-access-cache.json")

    @property
    def authorization_url(self) -> str:
        return f"{self.settings.accounts_base_url}/oauth/v2/auth"

    @property
    def token_url(self) -> str:
        return f"{self.settings.accounts_base_url}/oauth/v2/token"

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
            raise ValueError("Missing OAuth state signature.")

        payload_token, signature_token = state.split(".", 1)
        expected_signature = hmac.new(
            self.settings.state_secret.encode("utf-8"),
            payload_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        provided_signature = _b64url_decode(signature_token)
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise ValueError("Invalid OAuth state signature.")

        payload = json.loads(_b64url_decode(payload_token).decode("utf-8"))
        issued_at = int(payload.get("iat", 0))
        age_seconds = int(datetime.now(timezone.utc).timestamp()) - issued_at
        if issued_at <= 0 or age_seconds > self.settings.state_ttl_seconds:
            raise ValueError("OAuth state has expired. Start the connection again.")

    def build_authorization_redirect(self) -> str:
        if not self.settings.enabled or not self.settings.redirect_uri or not self.settings.client_id:
            raise ValueError("Zoho OAuth is not configured. Set client id, client secret, and redirect URI first.")

        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri,
                "scope": ",".join(self.settings.scopes),
                "access_type": "offline",
                "prompt": "consent",
                "state": self.build_state(),
            }
        )
        return f"{self.authorization_url}?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        if not self.settings.enabled or not self.settings.redirect_uri:
            raise ValueError("Zoho OAuth is not configured. Set client id, client secret, and redirect URI first.")

        timeout = httpx.Timeout(60.0, connect=20.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                self.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "redirect_uri": self.settings.redirect_uri,
                },
            )

        if response.status_code >= 400:
            raise ValueError(f"Zoho token exchange failed with status {response.status_code}: {response.text}")

        payload = response.json()
        refresh_token = str(payload.get("refresh_token", "")).strip()
        access_token = str(payload.get("access_token", "")).strip()
        if not refresh_token and not access_token:
            raise ValueError(f"Zoho token exchange did not return usable credentials: {payload}")
        return payload

    def access_token(self) -> str:
        now = time.time()
        if self._access_token and self._access_token_expires_at > now + 90:
            return self._access_token

        with self._token_lock:
            now = time.time()
            if self._access_token and self._access_token_expires_at > now + 90:
                return self._access_token
            # A process-local cache makes every five-minute oneshot refresh its
            # own token. Share only an access token in the service-writable
            # automation directory; keep the refresh credential unchanged.
            lock_path = self.cache_path.with_suffix(".lock")
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or stat.S_IMODE(info.st_mode) != 0o600
                        or info.st_uid != self.settings.credentials_path.stat().st_uid):
                    raise ValueError("Zoho OAuth refresh lock is not trusted")
                fcntl.flock(fd, fcntl.LOCK_EX)
                saved = self.load_saved_credentials()
                if not saved:
                    raise ValueError("Zoho OAuth is not connected.")
                refresh_token = str(saved.get("refresh_token") or "").strip()
                token = str(saved.get("access_token") or "").strip()
                if not refresh_token:
                    if token:
                        return token  # Legacy direct-token connection.
                    raise ValueError("Zoho OAuth credentials do not contain a refresh token.")
                binding = hashlib.sha256((str(self.settings.client_id) + "\0" + refresh_token).encode()).hexdigest()
                cache = self._read_cache()
                token = str(cache.get("access_token") or "").strip() if cache.get("binding") == binding else ""
                expiry = float(cache.get("access_token_expires_at") or 0)
                if token and expiry > time.time() + 90:
                    self._access_token = token
                    self._access_token_expires_at = expiry
                    return token
                timeout = httpx.Timeout(60.0, connect=20.0)
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(self.token_url, data={
                        "grant_type": "refresh_token", "refresh_token": refresh_token,
                        "client_id": self.settings.client_id, "client_secret": self.settings.client_secret})
                if response.status_code >= 400:
                    raise ValueError(
                        f"Zoho token refresh failed with status {response.status_code}: {response.text}")
                payload = response.json()
                token = str(payload.get("access_token") or "").strip()
                if not token:
                    raise ValueError(f"Zoho token refresh did not return an access token: {payload}")
                expires_in = int(payload.get("expires_in_sec") or payload.get("expires_in") or 3600)
                if not 180 <= expires_in <= 86400:
                    raise ValueError("Zoho token lifetime is outside safe bounds")
                expiry = time.time() + expires_in
                self._write_cache({"binding": binding, "access_token": token,
                                   "access_token_expires_at": expiry})
                self._access_token = token
                self._access_token_expires_at = expiry
                return token
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read_cache(self) -> dict[str, Any]:
        target = self.cache_path
        if not target.exists() or target.stat().st_size == 0:
            return {}
        info = target.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != self.settings.credentials_path.stat().st_uid):
            raise ValueError("Zoho access cache is not trusted")
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Zoho access cache is malformed")
        return value

    def _write_cache(self, payload: dict[str, Any]) -> None:
        target = self.cache_path
        original = target.stat() if target.exists() else None
        temporary = target.with_name("." + target.name + "." + secrets.token_hex(8) + ".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            if original is not None and os.geteuid() == 0:
                os.fchown(fd, original.st_uid, original.st_gid)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = -1
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)

    def load_saved_credentials(self) -> dict[str, Any] | None:
        path = self.settings.credentials_path
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected Zoho credential file format: {path}")
        return payload

    def save_credentials(self, payload: dict[str, Any]) -> Path:
        target = self.settings.credentials_path
        ensure_directory(target.parent)
        persisted = {
            "provider": "zoho",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "redirect_uri": self.settings.redirect_uri,
            "accounts_base_url": self.settings.accounts_base_url,
            "connected_at": utc_iso(),
            "scope": payload.get("scope") or ",".join(self.settings.scopes),
            "refresh_token": payload.get("refresh_token"),
            "access_token": payload.get("access_token"),
            "api_domain": payload.get("api_domain"),
            "token_type": payload.get("token_type"),
            "expires_in": payload.get("expires_in"),
            "expires_in_sec": payload.get("expires_in_sec"),
        }
        target.write_text(json.dumps(persisted, indent=2) + "\n", encoding="utf-8")
        target.chmod(0o640)
        return target

    def status(self) -> ZohoConnectionStatus:
        saved = self.load_saved_credentials()
        client_id = (self.settings.client_id or "").strip()
        client_id_suffix = client_id[-6:] if client_id else None
        return ZohoConnectionStatus(
            configured=self.settings.enabled,
            connected=bool(saved and saved.get("refresh_token")),
            redirect_uri=self.settings.redirect_uri,
            accounts_base_url=self.settings.accounts_base_url,
            scopes=self.settings.scopes,
            credentials_path=self.settings.credentials_path,
            connected_at=str(saved.get("connected_at")) if saved else None,
            scope=str(saved.get("scope")) if saved and saved.get("scope") else None,
            api_domain=str(saved.get("api_domain")) if saved and saved.get("api_domain") else None,
            has_refresh_token=bool(saved and saved.get("refresh_token")),
            client_id_suffix=client_id_suffix,
        )
