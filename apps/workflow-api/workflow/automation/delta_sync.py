"""Read-only, leased delta synchronization with atomic page intake/checkpoints."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol, TYPE_CHECKING
from uuid import uuid4

import httpx

from .events import EventLedger, count
from .event_schema import canonical
from .models import AutomationEvent, utc_now_iso

if TYPE_CHECKING:
    from .store import AutomationStore


class SyncFailure(ValueError):
    def __init__(self, category: str, retry_after: int | None = None) -> None:
        super().__init__(category)
        if category not in {"cursor_expired", "rate_limited", "provider_unavailable", "network_timeout",
                            "malformed_response", "authentication_failed", "invalid_cursor", "invalid_record"}:
            raise ValueError("invalid sync failure category")
        self.category = category
        self.retry_after = retry_after


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    try:
        if re.fullmatch(r"[0-9]{1,9}", value.strip()):
            result = int(value)
        else:
            checked = now or datetime.now(timezone.utc)
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return None
            result = max(0, int((when - checked).total_seconds()) + 1)
        # Unusable Retry-After is a permanent scheduler stop, never an early retry.
        return result if result <= 604800 else None
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass(frozen=True)
class SyncPage:
    events: tuple[AutomationEvent, ...]
    next_page: str | None
    next_cursor: str | None
    fetched_items: int


class DeltaAdapter(Protocol):
    def fetch(self, cursor: str | None, page_token: str | None, *, mode: str, limit: int) -> SyncPage: ...


class DeltaSync:
    def __init__(self, store: AutomationStore) -> None:
        self.store = store
        self.ledger = EventLedger(store)

    @staticmethod
    def _key(provider: str, account: str, stream: str, mode: str) -> tuple[str, str, str, str]:
        if (not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", provider) or not 1 <= len(account) <= 255
                or not 1 <= len(stream) <= 255 or mode not in {"incremental", "backfill"}):
            raise ValueError("invalid sync identity")
        return provider, account, stream, mode

    @staticmethod
    def _token(value: str | None) -> None:
        if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 4096
                                  or any(ord(c) < 32 for c in value)):
            raise SyncFailure("malformed_response")

    def initialize(self, provider: str, account: str, stream: str, *, cursor: str | None,
                   mode: str = "incremental", actor: str = "sync-config") -> None:
        key = self._key(provider, account, stream, mode)
        self._token(cursor)
        if mode == "incremental" and not cursor:
            raise ValueError("incremental sync requires an explicit initial cursor")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            inserted = conn.execute("INSERT INTO automation_sync_checkpoints(provider,source_account,stream,mode,cursor,status,updated_at) "
                "VALUES(?,?,?,?,?,'idle',?) ON CONFLICT(provider,source_account,stream,mode) DO NOTHING",
                (*key, cursor, utc_now_iso())).rowcount
            if inserted:
                self.ledger._audit(conn, stream, "sync_initialized", actor, {"provider": provider, "mode": mode})

    def snapshot(self, provider: str, account: str, stream: str, mode: str = "incremental") -> dict | None:
        key = self._key(provider, account, stream, mode)
        with self.store._connect() as conn:
            row = conn.execute("SELECT * FROM automation_sync_checkpoints WHERE provider=? AND source_account=? AND stream=? AND mode=?", key).fetchone()
            return dict(row) if row else None

    def promote_backfill(self, provider: str, account: str, stream: str, *, expected_revision: int,
                         actor: str, reason: str) -> dict:
        if provider != "google.calendar" or not 8 <= len(reason.strip()) <= 500:
            raise ValueError("only an explicitly reviewed completed Calendar backfill can be promoted")
        key = self._key(provider, account, stream, "backfill")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            completed = conn.execute("SELECT * FROM automation_sync_checkpoints WHERE provider=? AND source_account=? AND stream=? AND mode=?", key).fetchone()
            if (not completed or completed["revision"] != expected_revision or completed["status"] != "resync_required"
                    or completed["last_error"] is not None or not completed["last_success_at"]
                    or completed["page_token"] or not completed["cursor"] or completed["lease_token"]):
                raise ValueError("backfill has not durably completed at the requested revision")
            incremental = conn.execute("SELECT * FROM automation_sync_checkpoints WHERE provider=? AND source_account=? AND stream=? AND mode='incremental'", key[:3]).fetchone()
            if incremental and (incremental["status"] not in {"resync_required", "failed"} or incremental["lease_token"]):
                raise ValueError("incremental checkpoint is active")
            conn.execute("INSERT INTO automation_sync_checkpoints(provider,source_account,stream,mode,cursor,status,updated_at,last_success_at) "
                "VALUES(?,?,?,'incremental',?,'idle',?,?) ON CONFLICT(provider,source_account,stream,mode) "
                "DO UPDATE SET cursor=excluded.cursor,page_token=NULL,status='idle',revision=revision+1,failures=0,"
                "next_attempt_at=0,last_error=NULL,updated_at=excluded.updated_at,last_success_at=excluded.last_success_at",
                (*key[:3], completed["cursor"], utc_now_iso(), completed["last_success_at"]))
            from .events import redact
            self.ledger._audit(conn, stream, "backfill_promoted", actor, {"provider": provider, "reason": redact(reason.strip()), "revision": expected_revision})
            return {"status": "idle", "provider": provider, "stream": stream}

    def _claim(self, key: tuple[str, str, str, str], now_us: int) -> dict | None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM automation_sync_checkpoints WHERE provider=? AND source_account=? AND stream=? AND mode=?", key).fetchone()
            if row is None:
                raise LookupError("sync checkpoint not initialized")
            if row["status"] in {"resync_required", "failed"} or row["next_attempt_at"] > now_us:
                return None
            if row["lease_token"] and row["lease_expires_at"] > now_us:
                return None
            token = uuid4().hex
            conn.execute("UPDATE automation_sync_checkpoints SET lease_token=?,lease_expires_at=?,status='syncing' "
                "WHERE provider=? AND source_account=? AND stream=? AND mode=?", (token, now_us + 120_000_000, *key))
            count(conn, key[0], "polling_cycles")
            count(conn, key[0], "provider_api_calls")
            if row["failures"]:
                count(conn, key[0], "provider_retries")
            return dict(row, lease_token=token)

    def cycle(self, provider: str, account: str, stream: str, adapter: DeltaAdapter, *,
              mode: str = "incremental", page_limit: int = 100, max_pages: int = 1,
              poll_interval: int = 300) -> dict:
        key = self._key(provider, account, stream, mode)
        if not 1 <= page_limit <= 100 or not 1 <= max_pages <= 10 or not 30 <= poll_interval <= 86400:
            raise ValueError("invalid sync bounds")
        accepted = pages = 0
        for _ in range(max_pages):
            started = time.monotonic_ns()
            claim = self._claim(key, time.time_ns() // 1000)
            if claim is None:
                break
            try:
                page = adapter.fetch(claim["cursor"], claim["page_token"], mode=mode, limit=page_limit)
                if (not isinstance(page, SyncPage) or not isinstance(page.events, tuple)
                        or len(page.events) > page_limit or not isinstance(page.fetched_items, int)
                        or isinstance(page.fetched_items, bool) or not len(page.events) <= page.fetched_items <= page_limit):
                    raise SyncFailure("malformed_response")
                if any(not isinstance(event, AutomationEvent) for event in page.events):
                    raise SyncFailure("malformed_response")
                if sum(len(canonical(event.model_dump()).encode()) for event in page.events) > 4 * 1048576:
                    raise SyncFailure("invalid_record")
                self._token(page.next_page)
                self._token(page.next_cursor)
                if page.next_page and page.next_page == claim["page_token"]:
                    raise SyncFailure("invalid_cursor")
                if not page.next_page and not page.next_cursor:
                    raise SyncFailure("malformed_response")
                if any(e.source != provider or e.source_account != account for e in page.events):
                    raise SyncFailure("invalid_record")
                with self.store._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    live = conn.execute("SELECT revision,lease_token,lease_expires_at,notifications FROM automation_sync_checkpoints "
                        "WHERE provider=? AND source_account=? AND stream=? AND mode=?", key).fetchone()
                    if (live["revision"] != claim["revision"] or live["lease_token"] != claim["lease_token"]
                            or live["lease_expires_at"] <= time.time_ns() // 1000):
                        return {"pages": pages, "accepted": accepted, "fenced": True}
                    page_accepted = 0
                    for event in page.events:
                        page_accepted += int(self.ledger._capture(conn, event)[0])
                    # Keep the original sync cursor during pagination. The final
                    # cursor advances ONLY with the final page's durable events.
                    next_cursor = claim["cursor"] if page.next_page else page.next_cursor
                    next_attempt = 0 if page.next_page else time.time_ns() // 1000 + poll_interval * 1_000_000
                    if live["notifications"] != claim["notifications"]:
                        next_attempt = 0
                    status = "idle"
                    if mode == "backfill" and not page.next_page:
                        # Backfill runs once. Promotion to incremental is explicit.
                        status = "resync_required"
                    conn.execute("UPDATE automation_sync_checkpoints SET cursor=?,page_token=?,revision=revision+1,"
                        "status=?,lease_token=NULL,lease_expires_at=NULL,failures=0,next_attempt_at=?,updated_at=?,"
                        "last_success_at=?,last_error=NULL WHERE provider=? AND source_account=? AND stream=? AND mode=?",
                        (next_cursor, page.next_page, status, next_attempt, utc_now_iso(), utc_now_iso(), *key))
                    count(conn, provider, "items_fetched", page.fetched_items)
                    count(conn, provider, "sync_duration_us", (time.monotonic_ns() - started) // 1000)
                    self.ledger._audit(conn, stream, "sync_page_committed", "delta-sync",
                                       {"provider": provider, "items": page.fetched_items, "mode": mode})
                pages += 1
                accepted += page_accepted
                if not page.next_page:
                    break
            except (SyncFailure, httpx.TimeoutException, httpx.TransportError, ValueError, TypeError, KeyError) as exc:
                failure = exc if isinstance(exc, SyncFailure) else SyncFailure(
                    "network_timeout" if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)) else "invalid_record")
                self._fail(key, claim, failure)
                break
            except Exception:
                # An unforeseen failure never advances the checkpoint. Retain its
                # lease until expiry; expose the exception to the worker watchdog.
                raise
        return {"pages": pages, "accepted": accepted, "fenced": False}

    def _fail(self, key: tuple[str, str, str, str], claim: dict, failure: SyncFailure) -> None:
        failures = claim["failures"] + 1
        delay = min(3600, 30 * 2 ** min(failures - 1, 7))
        category = failure.category
        status = "backoff"
        if category in {"cursor_expired", "invalid_cursor"}:
            status = "resync_required"
        elif category in {"authentication_failed", "malformed_response", "invalid_record"}:
            status = "failed"
        elif category == "rate_limited":
            if failure.retry_after is None:
                status = "failed"
            else:
                delay = max(delay, failure.retry_after)
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("UPDATE automation_sync_checkpoints SET status=?,failures=?,next_attempt_at=?,"
                "lease_token=NULL,lease_expires_at=NULL,last_error=?,updated_at=? "
                "WHERE provider=? AND source_account=? AND stream=? AND mode=? AND lease_token=? AND revision=? AND lease_expires_at>?",
                (status, failures, time.time_ns() // 1000 + delay * 1_000_000, category, utc_now_iso(), *key,
                 claim["lease_token"], claim["revision"], time.time_ns() // 1000))
            if cursor.rowcount:
                count(conn, key[0], "provider_failures")
                if category == "rate_limited":
                    count(conn, key[0], "provider_rate_limits")
                self.ledger._audit(conn, key[2], "sync_failed", "delta-sync", {"provider": key[0], "category": category})
