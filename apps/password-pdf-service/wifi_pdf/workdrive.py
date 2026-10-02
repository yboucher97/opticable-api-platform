from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .config import WorkDriveSettings
from .exceptions import ConfigurationError, WorkDriveError
from .zoho_credentials import load_zoho_credentials


class ZohoWorkDriveClient:
    def __init__(self, settings: WorkDriveSettings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self._access_token: str | None = None
        self._prepared_upload_folders: dict[str, str] = {}

    def resolve_folder_id(self, request_folder_id: str | None) -> str:
        folder_id = (
            request_folder_id
            or os.getenv("ZOHO_WORKDRIVE_PARENT_FOLDER_ID")
            or self.settings.parent_folder_id
        )
        if not folder_id:
            raise ConfigurationError(
                "WorkDrive upload is enabled but no folder id was provided. "
                "Send workdrive_folder_id in JSON or set ZOHO_WORKDRIVE_PARENT_FOLDER_ID."
            )
        return folder_id

    def resolve_upload_folder_id(self, request_folder_id: str | None) -> str:
        raise RuntimeError('Legacy WorkDrive writer retired; provider mutations are forbidden')

    def _get_auth_headers(self, client: httpx.Client) -> dict[str, str]:
        access_token = self._get_access_token(client)
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Accept": "application/vnd.api+json",
        }

    def _get_access_token(self, client: httpx.Client) -> str:
        if self._access_token:
            return self._access_token

        credentials = load_zoho_credentials()
        refresh_token = credentials.get("refresh_token")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        if refresh_token and client_id and client_secret:
            response = client.post(
                self.settings.accounts_base_url,
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

    def upload_file(self, path: Path, folder_id: str) -> dict[str, Any]:
        raise RuntimeError('Legacy WorkDrive upload retired; provider mutations are forbidden')

    def _find_or_create_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str:
        child_folder_id = self._find_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=parent_folder_id,
            target_folder_name=target_folder_name,
        )
        if child_folder_id:
            return child_folder_id

        self.logger.info(
            "WorkDrive child folder '%s' was missing inside parent %s. Creating it now.",
            target_folder_name,
            parent_folder_id,
        )
        return self._create_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=parent_folder_id,
            target_folder_name=target_folder_name,
        )

    def _archive_existing_target_folder(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_id: str,
        target_folder_name: str,
    ) -> str:
        if not self.settings.archive_existing_files:
            return target_folder_id
        if not self._folder_has_contents(client, headers, target_folder_id):
            return target_folder_id

        archive_root_id = self._find_or_create_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=parent_folder_id,
            target_folder_name=self.settings.archive_folder_name,
        )
        archive_folder_name = self._next_archive_folder_name(client, headers, archive_root_id)
        self._move_folder(
            client=client,
            headers=headers,
            folder_id=target_folder_id,
            new_parent_id=archive_root_id,
            new_name=archive_folder_name,
        )
        new_target_folder_id = self._create_child_folder_id(
            client=client,
            headers=headers,
            parent_folder_id=parent_folder_id,
            target_folder_name=target_folder_name,
        )
        self.logger.info(
            "Archived existing WorkDrive folder '%s' into '%s/%s'. New upload folder id: %s",
            target_folder_name,
            self.settings.archive_folder_name,
            archive_folder_name,
            new_target_folder_id,
        )
        return new_target_folder_id

    def _folder_has_contents(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        folder_id: str,
    ) -> bool:
        response = client.get(
            f"{self.settings.api_base_url}/files/{folder_id}/files",
            headers=headers,
            params={"page[limit]": 1},
        )
        if response.status_code >= 400:
            raise WorkDriveError(
                f"WorkDrive folder listing failed for '{folder_id}' with status {response.status_code}"
            )

        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise WorkDriveError(f"Unexpected WorkDrive folder listing response for '{folder_id}'")
        return len(data) > 0

    def _find_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str | None:
        offset = 0
        limit = 50
        target_name = target_folder_name.strip().casefold()

        while True:
            response = client.get(
                f"{self.settings.api_base_url}/files/{parent_folder_id}/files",
                headers=headers,
                params={"page[limit]": limit, "page[offset]": offset},
            )
            if response.status_code >= 400:
                raise WorkDriveError(
                    f"WorkDrive folder lookup failed for parent '{parent_folder_id}' with status "
                    f"{response.status_code}"
                )

            payload = response.json()
            data = payload.get("data")
            if not isinstance(data, list):
                raise WorkDriveError(
                    f"Unexpected WorkDrive folder lookup response for parent '{parent_folder_id}'"
                )

            for entry in data:
                if not isinstance(entry, dict):
                    continue
                attributes = entry.get("attributes")
                if not isinstance(attributes, dict):
                    continue
                if str(attributes.get("type", "")).lower() != "folder":
                    continue
                name = str(attributes.get("name", "")).strip()
                if name.casefold() == target_name:
                    folder_id = entry.get("id")
                    if not folder_id:
                        raise WorkDriveError(
                            f"WorkDrive folder '{target_folder_name}' was found inside '{parent_folder_id}' but had no id."
                        )
                    return str(folder_id)

            if len(data) < limit:
                break
            offset += limit

        return None

    def _next_archive_folder_name(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        archive_root_id: str,
    ) -> str:
        base_name = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        candidate = base_name
        suffix = 1
        while self._find_child_folder_id(client, headers, archive_root_id, candidate):
            suffix += 1
            candidate = f"{base_name}-{suffix:02d}"
        return candidate

    def _move_folder(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        folder_id: str,
        new_parent_id: str,
        new_name: str,
    ) -> None:
        raise RuntimeError('Legacy WorkDrive provider writer retired')

    def _create_child_folder_id(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        parent_folder_id: str,
        target_folder_name: str,
    ) -> str:
        raise RuntimeError('Legacy WorkDrive provider writer retired')
