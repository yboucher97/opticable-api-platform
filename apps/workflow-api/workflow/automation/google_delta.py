"""Google Calendar, Drive and Gmail incremental reads. No provider writes."""
from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .delta_sync import SyncFailure, SyncPage, retry_after_seconds
from .event_schema import digest
from .events import MAX_EVENT_BYTES
from .models import AutomationEvent


class GoogleDeltaAdapter:
    def __init__(self, provider: str, account: str, stream: str, access_token: Callable[[], str],
                 *, transport: httpx.BaseTransport | None = None) -> None:
        if provider not in {"google.calendar", "google.drive", "google.gmail"}:
            raise ValueError("unsupported Google delta provider")
        self.provider, self.account, self.stream = provider, account, stream
        self.access_token, self.transport = access_token, transport

    def _read(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            token = self.access_token()
            if not isinstance(token, str) or not token.strip():
                raise ValueError("missing credential")
        except Exception:
            # Token refresh errors can contain provider credential material. Stop
            # durably with a fixed category instead of logging their raw text.
            raise SyncFailure("authentication_failed") from None
        deadline = time.monotonic() + 30
        with httpx.Client(transport=self.transport, timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
            # Stream the response so a provider or intermediary cannot force an
            # unbounded allocation before validation.
            with client.stream("GET", url, params=params, headers={"Authorization": "Bearer " + token,
                                                                  "Accept": "application/json"}) as response:
                status = response.status_code
                if status in {404, 410}:
                    raise SyncFailure("cursor_expired")
                if status == 429:
                    raise SyncFailure("rate_limited", retry_after_seconds(response.headers.get("retry-after")))
                if status in {401, 403}:
                    raise SyncFailure("authentication_failed")
                if status >= 500:
                    raise SyncFailure("provider_unavailable")
                if not response.is_success:
                    raise SyncFailure("invalid_cursor")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise SyncFailure("network_timeout")
                    if len(raw) + len(chunk) > MAX_EVENT_BYTES:
                        raise SyncFailure("malformed_response")
                    raw.extend(chunk)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError, RecursionError):
            raise SyncFailure("malformed_response") from None

    def fetch(self, cursor: str | None, page_token: str | None, *, mode: str, limit: int) -> SyncPage:
        if not 1 <= limit <= 100:
            raise ValueError("invalid page size")
        if mode == "incremental" and not cursor:
            raise SyncFailure("invalid_cursor")
        if self.provider == "google.calendar":
            url = "https://www.googleapis.com/calendar/v3/calendars/" + quote(self.stream, safe="") + "/events"
            params: dict[str, Any] = {"maxResults": limit, "showDeleted": "true"}
            if cursor:
                params["syncToken"] = cursor
            if page_token:
                params["pageToken"] = page_token
            data = self._read(url, params)
            records = data.get("items", [])
            next_page, next_cursor = data.get("nextPageToken"), data.get("nextSyncToken")
        elif self.provider == "google.drive":
            if mode != "incremental":
                raise SyncFailure("invalid_cursor")
            params = {"pageSize": limit, "pageToken": page_token or cursor,
                      "includeRemoved": "true", "fields": "nextPageToken,newStartPageToken,changes(fileId,time,removed,file(id,name,mimeType,modifiedTime,trashed))"}
            data = self._read("https://www.googleapis.com/drive/v3/changes", params)
            records = data.get("changes", [])
            next_page, next_cursor = data.get("nextPageToken"), data.get("newStartPageToken")
        else:
            if mode != "incremental":
                raise SyncFailure("invalid_cursor")
            params = {"maxResults": limit, "startHistoryId": cursor}
            if page_token:
                params["pageToken"] = page_token
            data = self._read("https://gmail.googleapis.com/gmail/v1/users/me/history", params)
            records = data.get("history", [])
            next_page, next_cursor = data.get("nextPageToken"), data.get("historyId")
        if not isinstance(records, list) or len(records) > limit or any(not isinstance(r, dict) for r in records):
            raise SyncFailure("malformed_response")
        events = []
        for record in records:
            try:
                if self.provider == "google.calendar":
                    subject = record["id"]
                    version = record.get("etag") or record.get("updated") or digest(record)
                    timestamp = record.get("updated")
                elif self.provider == "google.drive":
                    subject = record["fileId"]
                    version = record["time"]
                    timestamp = version
                else:
                    subject, version, timestamp = record["id"], record["id"], None
                if not isinstance(subject, str) or not subject or not isinstance(version, str):
                    raise ValueError()
                events.append(AutomationEvent(event_type=self.provider + ".changed", source=self.provider,
                    source_account=self.account, subject_type="history" if self.provider.endswith("gmail") else "resource",
                    subject_id=subject, provider_event_id=digest([self.stream, subject, version]),
                    provider_timestamp=timestamp, payload=record, provider_evidence={"stream": self.stream}))
            except (ValueError, TypeError, KeyError):
                raise SyncFailure("invalid_record") from None
        return SyncPage(tuple(events), next_page, next_cursor, len(records))
