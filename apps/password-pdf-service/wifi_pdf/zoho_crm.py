from __future__ import annotations

from typing import Any

import httpx

from .config import CrmSettings, WorkDriveSettings
from .exceptions import ConfigurationError, WorkDriveError
from .zoho_credentials import load_zoho_credentials


class ZohoCrmClient:
    def __init__(self, crm_settings: CrmSettings, auth_settings: WorkDriveSettings, logger) -> None:
        self.crm_settings = crm_settings
        self.auth_settings = auth_settings
        self.logger = logger
        self._access_token: str | None = None

    def update_generated_password_fields(self, record_id: str, passwords: list[str]) -> dict[str, Any]:
        raise RuntimeError('Legacy PDF CRM writer retired; provider mutations are forbidden')

    def _get_access_token(self, client: httpx.Client) -> str:
        if self._access_token:
            return self._access_token

        credentials = load_zoho_credentials()
        refresh_token = credentials.get("refresh_token")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if refresh_token and client_id and client_secret:
            response = client.post(
                self.auth_settings.accounts_base_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            if response.status_code >= 400:
                raise WorkDriveError(
                    f"Zoho OAuth refresh failed with status {response.status_code}"
                )

            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise WorkDriveError(f"Zoho OAuth refresh did not return an access token")

            self._access_token = access_token
            return access_token

        direct_token = credentials.get("access_token")
        if direct_token:
            self._access_token = str(direct_token)
            return str(direct_token)

        raise ConfigurationError(
            "Missing Zoho OAuth credentials. Complete the server-side Zoho OAuth flow and "
            "ensure ZOHO_OAUTH_CREDENTIALS_PATH points at the generated credential file."
        )
