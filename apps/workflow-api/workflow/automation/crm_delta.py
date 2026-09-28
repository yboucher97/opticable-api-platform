"""Bounded CRM fallback using Phase 4 checkpoints, leases and event intake.

No historical scan or pagination over a changing CRM list. An overflowing window
stops for reviewed recovery; a 120-second overlap covers ordinary indexing lag.
Zoho offers no universal notification or indexing-loss guarantee.
"""
from datetime import datetime, timedelta, timezone

from .delta_sync import SyncFailure, SyncPage, retry_after_seconds
from .event_schema import digest
from .models import AutomationEvent


class CrmLeadDeltaAdapter:
    def __init__(self, client, account):
        self.client, self.account = client, account

    def fetch(self, cursor, page_token, *, mode, limit):
        if mode != "incremental" or page_token or not cursor:
            raise SyncFailure("invalid_cursor")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise SyncFailure("invalid_page_limit")
        try:
            before = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
            if before.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise SyncFailure("invalid_cursor") from None
        started = datetime.now(timezone.utc)
        if before > started:
            raise SyncFailure("invalid_cursor")
        try:
            result = self.client.request("zohoapis", "GET", "/crm/v8/Leads",
                headers={"If-Modified-Since": (before - timedelta(seconds=120)).isoformat()},
                query={"fields": "id,Modified_Time", "per_page": limit, "page": 1,
                       "sort_by": "Modified_Time", "sort_order": "asc"})
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {401, 403}:
                raise SyncFailure("authentication_failed") from None
            if status == 429:
                headers = getattr(exc.response, "headers", {})
                raise SyncFailure("rate_limited", retry_after_seconds(headers.get("Retry-After"))) from None
            raise SyncFailure("provider_unavailable" if status and status >= 500 else "network_timeout") from None
        status, data = result.get("status"), result.get("data") or {}
        if result.get("ok") is not True:
            if status == 429:
                raise SyncFailure("rate_limited")
            raise SyncFailure("authentication_failed" if status in {401, 403} else
                              "provider_unavailable" if status and status >= 500 else "malformed_response")
        if status in {204, 304}:
            return SyncPage((), None, started.isoformat(), 0)
        rows = data.get("data")
        if status != 200 or not isinstance(rows, list) or len(rows) > limit:
            raise SyncFailure("malformed_response")
        if (data.get("info") or {}).get("more_records"):
            raise SyncFailure("cursor_expired")  # Reviewed bounded window recovery, never skip rows.
        events = []
        for row in rows:
            identity, version = row.get("id"), row.get("Modified_Time")
            if not isinstance(identity, str) or not identity.isdigit() or not isinstance(version, str):
                raise SyncFailure("invalid_record")
            events.append(AutomationEvent(event_type="zoho.crm.Leads.update", source="zoho_crm",
                source_account=self.account, provider_event_id=digest(["delta", identity, version]),
                provider_timestamp=version, subject_type="Leads", subject_id=identity,
                payload={"module": "Leads", "operation": "update", "ids": [identity], "version": version}))
        return SyncPage(tuple(events), None, started.isoformat(), len(rows))
