from __future__ import annotations

import time
from typing import Any

import httpx

from .config import DownstreamOmadaSettings, DownstreamPdfSettings


class PdfGeneratorClient:
    def __init__(self, settings: DownstreamPdfSettings) -> None:
        self.settings = settings

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.settings.api_key:
            headers["X-API-Key"] = self.settings.api_key

        response = httpx.post(
            f"{self.settings.base_url}/webhooks/zoho/wifi-pdfs",
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id: str) -> dict[str, Any]:
        response = httpx.get(f"{self.settings.base_url}/jobs/{job_id}", timeout=30)
        response.raise_for_status()
        return response.json()

    def wait_for_completion(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.timeout_seconds
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            status = str(job.get("status", "")).lower()
            if status in {"completed", "failed"}:
                return job
            time.sleep(self.settings.poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Password_PDF_Generator job {job_id}.")


class OmadaClient:
    def __init__(self, settings: DownstreamOmadaSettings) -> None:
        if not settings.webhook_token:
            raise ValueError("OMADA_SITE_CREATOR_WEBHOOK_TOKEN is required.")
        self.settings = settings

    def create_job(self, plan: dict[str, Any], file_name: str) -> dict[str, Any]:
        response = httpx.post(
            f"{self.settings.base_url}/api/webhooks/run",
            json={
                "fileName": file_name,
                "plan": plan,
            },
            headers={
                "Authorization": f"Bearer {self.settings.webhook_token}",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def create_job_from_raw(self, content: bytes, content_type: str | None = None, file_name: str | None = None) -> dict[str, Any]:
        raise RuntimeError('Legacy Omada executor retired')
        headers = self._auth_headers()
        if content_type:
            headers["Content-Type"] = content_type
        if file_name:
            headers["X-Plan-File-Name"] = file_name

        response = httpx.post(
            f"{self.settings.base_url}/api/webhooks/run",
            content=content,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id: str) -> dict[str, Any]:
        response = httpx.get(f"{self.settings.base_url}/api/jobs/{job_id}", timeout=30)
        response.raise_for_status()
        body = response.json()
        return body["job"]

    def wait_for_completion(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.timeout_seconds
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            status = str(job.get("status", "")).lower()
            if status in {"success", "failed"}:
                return job
            time.sleep(self.settings.poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Omada Site Creator job {job_id}.")

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.webhook_token}",
        }

    def _discovery_params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "organizationName": self.settings.organization_name,
            "baseUrl": self.settings.cloud_base_url,
            "browserChannel": self.settings.browser_channel,
            "headless": str(self.settings.headless).lower(),
        }
        if extra:
            params.update(extra)
        return params

    def list_sites(self, search: str | None = None) -> dict[str, Any]:
        params = self._discovery_params({"search": search} if search else None)
        response = httpx.get(
            f"{self.settings.base_url}/api/discovery/sites",
            params=params,
            headers=self._auth_headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def get_site(self, site_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.settings.base_url}/api/discovery/sites/{site_id}",
            params=self._discovery_params(),
            headers=self._auth_headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def list_lans(self, site_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.settings.base_url}/api/discovery/sites/{site_id}/lans",
            params=self._discovery_params(),
            headers=self._auth_headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def list_wlan_groups(self, site_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.settings.base_url}/api/discovery/sites/{site_id}/wlan-groups",
            params=self._discovery_params(),
            headers=self._auth_headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def list_ssids(self, site_id: str, wlan_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.settings.base_url}/api/discovery/sites/{site_id}/wlan-groups/{wlan_id}/ssids",
            params=self._discovery_params(),
            headers=self._auth_headers(),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
