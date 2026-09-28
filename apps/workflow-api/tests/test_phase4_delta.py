from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from workflow.automation.delta_sync import DeltaSync, SyncFailure, SyncPage, retry_after_seconds
from workflow.automation.crm_delta import CrmLeadDeltaAdapter
from workflow.automation.events import EventLedger
from workflow.automation.google_delta import GoogleDeltaAdapter
from workflow.automation.models import AutomationEvent
from workflow.automation.store import AutomationStore
from workflow.automation.sync_runtime import DeltaWorker, SyncJob
from workflow.automation.health_monitor import AutomationHealthMonitor


class ScriptedAdapter:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []

    def fetch(self, cursor, page_token, *, mode, limit):
        self.calls.append((cursor, page_token, mode, limit))
        page = self.pages.pop(0)
        if isinstance(page, Exception): raise page
        return page


class DeltaSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "automation.db"
        self.store = AutomationStore(self.db); self.sync = DeltaSync(self.store)
        self.sync.initialize("fixture", "account", "stream", cursor="c0")

    def event(self, identity="one", **kwargs):
        return AutomationEvent.model_validate({"event_type": "fixture.changed", "source": "fixture", "source_account": "account",
                                              "provider_event_id": identity, "payload": {"id": identity}, **kwargs})

    def cycle(self, adapter, **kwargs):
        return self.sync.cycle("fixture", "account", "stream", adapter, **kwargs)

    def state(self): return self.sync.snapshot("fixture", "account", "stream")

    def due(self):
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_sync_checkpoints SET next_attempt_at=0,lease_expires_at=0")

    def test_checkpoint_only_advances_with_durable_page(self):
        result = self.cycle(ScriptedAdapter(SyncPage((self.event(),), None, "c1", 1)))
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(self.state()["cursor"], "c1")
        self.assertEqual(len(EventLedger(self.store).list_events()), 1)

    def test_restart_between_pages_preserves_original_cursor_and_next_page(self):
        first = ScriptedAdapter(SyncPage((self.event(),), "page2", None, 1))
        self.cycle(first)
        self.assertEqual(self.state()["cursor"], "c0"); self.assertEqual(self.state()["page_token"], "page2")
        second = ScriptedAdapter(SyncPage((self.event("two"),), None, "c2", 1))
        self.sync = DeltaSync(AutomationStore(self.db)); self.cycle(second)
        self.assertEqual(second.calls, [("c0", "page2", "incremental", 100)])
        self.assertEqual(self.state()["cursor"], "c2")

    def test_duplicate_pages_do_not_duplicate_events(self):
        self.cycle(ScriptedAdapter(SyncPage((self.event(),), "page2", None, 1)))
        result = self.cycle(ScriptedAdapter(SyncPage((self.event(),), None, "c1", 1)))
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(len(EventLedger(self.store).list_events()), 1)

    def test_failed_durable_ingest_rolls_back_entire_page_and_cursor(self):
        adapter = ScriptedAdapter(SyncPage((self.event(), self.event("two", payload={"too_large": "x" * 1048576})), None, "c1", 2))
        self.cycle(adapter)
        self.assertEqual(self.state()["cursor"], "c0")
        self.assertEqual(self.state()["revision"], 0)
        self.assertEqual(EventLedger(self.store).list_events(), [])
        self.assertEqual(self.state()["status"], "failed")

    def test_db_transaction_interruption_does_not_advance_and_recovers_after_lease(self):
        with self.store._connect() as conn:
            conn.execute("CREATE TRIGGER inject_failure BEFORE INSERT ON automation_events BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.cycle(ScriptedAdapter(SyncPage((self.event(),), None, "c1", 1)))
        self.assertEqual(self.state()["cursor"], "c0"); self.assertEqual(self.state()["revision"], 0)
        with self.store._connect() as conn: conn.execute("DROP TRIGGER inject_failure")
        self.due()
        result = self.cycle(ScriptedAdapter(SyncPage((self.event(),), None, "c1", 1)))
        self.assertEqual(result["accepted"], 1)

    def test_timeout_500_429_and_retry_after_persist_backoff(self):
        failures = [SyncFailure("network_timeout"), SyncFailure("provider_unavailable"), SyncFailure("rate_limited", 120)]
        for failure in failures:
            self.due(); before = time.time_ns() // 1000
            self.cycle(ScriptedAdapter(failure))
            with self.subTest(category=failure.category):
                state = self.state()
                self.assertEqual(state["status"], "backoff"); self.assertEqual(state["cursor"], "c0")
                self.assertGreater(state["next_attempt_at"], before)
                if failure.category == "rate_limited": self.assertGreaterEqual(state["next_attempt_at"], before + 120000000)
                blocked = ScriptedAdapter(); self.cycle(blocked); self.assertEqual(blocked.calls, [])

    def test_expired_invalid_cursor_and_unusable_retry_after_stop_safely(self):
        for category, expected in (("cursor_expired", "resync_required"), ("invalid_cursor", "resync_required"),
                                   ("rate_limited", "failed"), ("authentication_failed", "failed"),
                                   ("malformed_response", "failed")):
            self.sync.initialize("fixture", "account", category, cursor="old")
            self.sync.cycle("fixture", "account", category, ScriptedAdapter(SyncFailure(category)))
            state = self.sync.snapshot("fixture", "account", category)
            with self.subTest(category=category):
                self.assertEqual(state["status"], expected); self.assertEqual(state["cursor"], "old")

    def test_bounded_polling_pagination_and_schedule(self):
        adapter = ScriptedAdapter(*(SyncPage((self.event(str(i)),), "page" + str(i), None, 1) for i in range(10)))
        result = self.cycle(adapter, max_pages=2, page_limit=5)
        self.assertEqual(result["pages"], 2); self.assertEqual(len(adapter.calls), 2)
        self.assertTrue(all(c[-1] == 5 for c in adapter.calls))
        self.assertEqual(self.state()["cursor"], "c0")

    def test_concurrent_checkpoint_claim_has_one_provider_call(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking:
            def fetch(inner, *args, **kwargs):
                entered.set(); self.assertTrue(release.wait(10)); return SyncPage((self.event(),), None, "c1", 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.cycle, Blocking()); self.assertTrue(entered.wait(10))
            second = ScriptedAdapter(); result = self.cycle(second)
            self.assertEqual(result["pages"], 0); self.assertEqual(second.calls, [])
            release.set(); self.assertEqual(first.result(timeout=10)["pages"], 1)

    def test_stale_worker_cannot_commit_after_new_claim(self):
        class Stealing:
            def fetch(inner, *args, **kwargs):
                with self.store._connect() as conn:
                    conn.execute("UPDATE automation_sync_checkpoints SET lease_token='new-worker',lease_expires_at=?", (time.time_ns() // 1000 + 100000000,))
                return SyncPage((self.event(),), None, "c1", 1)
        result = self.cycle(Stealing())
        self.assertTrue(result["fenced"]); self.assertEqual(self.state()["cursor"], "c0")
        self.assertEqual(EventLedger(self.store).list_events(), [])

    def test_notification_during_page_read_schedules_followup_without_losing_cursor(self):
        class Notification:
            def fetch(inner, *args, **kwargs):
                with self.store._connect() as conn:
                    conn.execute("UPDATE automation_sync_checkpoints SET notifications=notifications+1")
                return SyncPage((self.event(),), None, "c1", 1)
        self.cycle(Notification())
        self.assertEqual(self.state()["cursor"], "c1")
        self.assertEqual(self.state()["next_attempt_at"], 0)

    def test_expired_failure_report_is_fenced(self):
        claim = self.sync._claim(("fixture", "account", "stream", "incremental"), time.time_ns() // 1000)
        self.due()
        self.sync._fail(("fixture", "account", "stream", "incremental"), claim, SyncFailure("provider_unavailable"))
        self.assertEqual(self.state()["status"], "syncing")
        self.assertEqual(self.state()["failures"], 0)

    def test_backfill_is_separate_bounded_and_never_restarts_automatically(self):
        self.sync.initialize("fixture", "account", "stream", mode="backfill", cursor=None)
        adapter = ScriptedAdapter(SyncPage((self.event(),), None, "backfill-final", 1))
        result = self.sync.cycle("fixture", "account", "stream", adapter, mode="backfill")
        self.assertEqual(result["pages"], 1)
        self.assertEqual(self.sync.snapshot("fixture", "account", "stream", "backfill")["status"], "resync_required")
        self.assertEqual(self.state()["cursor"], "c0")
        self.sync.cycle("fixture", "account", "stream", ScriptedAdapter(), mode="backfill")

    def test_invalid_provider_page_and_scope_stop_without_cursor_advance(self):
        for page in (SyncPage((self.event(source_account="wrong"),), None, "c1", 1),
                     SyncPage((self.event(),), None, None, 1), SyncPage((), "p", None, 101)):
            self.sync.initialize("fixture", "account", str(id(page)), cursor="c0")
            self.sync.cycle("fixture", "account", str(id(page)), ScriptedAdapter(page))
            with self.subTest(page=page):
                state = self.sync.snapshot("fixture", "account", str(id(page)))
                self.assertEqual(state["cursor"], "c0"); self.assertEqual(state["status"], "failed")

    def test_sync_usage_counts_duration_items_calls_and_failures(self):
        self.cycle(ScriptedAdapter(SyncPage((self.event(),), None, "c1", 1)))
        self.due(); self.cycle(ScriptedAdapter(SyncFailure("rate_limited", 60)))
        usage = {r["metric"]: r["value"] for r in EventLedger(self.store).usage() if r["provider"] == "fixture"}
        self.assertEqual(usage["items_fetched"], 1); self.assertEqual(usage["provider_api_calls"], 2)
        self.assertEqual(usage["provider_rate_limits"], 1); self.assertGreater(usage["sync_duration_us"], 0)

    def test_retry_after_numeric_http_date_and_bounds(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(retry_after_seconds("120"), 120)
        self.assertEqual(retry_after_seconds("Thu, 01 Jan 2026 00:02:00 GMT", now=now), 121)
        for value in (None, "wrong", "-1", "999999999"):
            with self.subTest(value=value): self.assertIsNone(retry_after_seconds(value))

    def test_completed_backfill_promotes_only_durably_ingested_cursor(self):
        self.sync.initialize("google.calendar", "account", "calendar", cursor="expired")
        self.sync.cycle("google.calendar", "account", "calendar", ScriptedAdapter(SyncFailure("cursor_expired")))
        self.sync.initialize("google.calendar", "account", "calendar", cursor=None, mode="backfill")
        event = self.event(source="google.calendar")
        self.sync.cycle("google.calendar", "account", "calendar", ScriptedAdapter(SyncPage((event,), None, "verified-final", 1)), mode="backfill")
        with self.assertRaises(ValueError):
            self.sync.promote_backfill("google.calendar", "account", "calendar", expected_revision=2, actor="operator", reason="Reviewed bounded backfill")
        result = self.sync.promote_backfill("google.calendar", "account", "calendar", expected_revision=1, actor="operator", reason="Reviewed bounded backfill")
        self.assertEqual(result["status"], "idle")
        self.assertEqual(self.sync.snapshot("google.calendar", "account", "calendar")["cursor"], "verified-final")

    def test_expired_or_incomplete_backfill_cannot_be_promoted(self):
        self.sync.initialize("google.calendar", "account", "calendar", cursor=None, mode="backfill")
        self.sync.cycle("google.calendar", "account", "calendar", ScriptedAdapter(SyncFailure("cursor_expired")), mode="backfill")
        with self.assertRaises(ValueError):
            self.sync.promote_backfill("google.calendar", "account", "calendar", expected_revision=0, actor="operator", reason="Reviewed bounded backfill")


class GoogleDeltaTests(unittest.TestCase):
    def adapter(self, provider, response, status=200, headers=None, observed=None):
        def handle(request):
            if observed is not None: observed.append(request)
            return httpx.Response(status, json=response, headers=headers)
        return GoogleDeltaAdapter(provider, "account", "resource", lambda: "fixture-access-token", transport=httpx.MockTransport(handle))

    def test_calendar_incremental_query_and_cursor(self):
        observed = []
        adapter = self.adapter("google.calendar", {"items": [{"id": "one", "etag": "version", "updated": "2026-01-01T00:00:00Z"}], "nextSyncToken": "next"}, observed=observed)
        page = adapter.fetch("old", "page", mode="incremental", limit=25)
        self.assertEqual(page.next_cursor, "next"); self.assertEqual(len(page.events), 1)
        self.assertEqual(observed[0].method, "GET")
        self.assertEqual(observed[0].url.params["syncToken"], "old")
        self.assertEqual(observed[0].url.params["pageToken"], "page")
        self.assertNotIn("timeMin", observed[0].url.params)

    def test_drive_changes_and_gmail_history_are_incremental(self):
        for provider, response, expected_key in (
            ("google.drive", {"changes": [{"fileId": "one", "time": "2026-01-01T00:00:00Z", "removed": True}], "newStartPageToken": "next"}, "pageToken"),
            ("google.gmail", {"history": [{"id": "10", "messagesAdded": [{"message": {"id": "one"}}]}], "historyId": "11"}, "startHistoryId")):
            observed = []; page = self.adapter(provider, response, observed=observed).fetch("old", None, mode="incremental", limit=10)
            with self.subTest(provider=provider):
                self.assertEqual(len(page.events), 1); self.assertEqual(observed[0].url.params[expected_key], "old")

    def test_google_failures_are_categorized_without_provider_body_logging(self):
        for status, category in ((429, "rate_limited"), (500, "provider_unavailable"), (410, "cursor_expired"),
                                 (404, "cursor_expired"), (401, "authentication_failed"), (400, "invalid_cursor")):
            adapter = self.adapter("google.calendar", {"secret": "neverlog"}, status, {"Retry-After": "120"})
            with self.subTest(status=status), self.assertRaises(SyncFailure) as captured:
                adapter.fetch("old", None, mode="incremental", limit=10)
            self.assertEqual(captured.exception.category, category)
            self.assertNotIn("neverlog", str(captured.exception))

    def test_google_timeout_and_malformed_response(self):
        def timeout(request): raise httpx.ReadTimeout("fixture", request=request)
        adapter = GoogleDeltaAdapter("google.calendar", "account", "stream", lambda: "fixture", transport=httpx.MockTransport(timeout))
        with self.assertRaises(httpx.ReadTimeout): adapter.fetch("old", None, mode="incremental", limit=10)
        for response in ([], {"items": ["invalid"]}, {"items": [{"missing": "id"}]}):
            with self.subTest(response=response), self.assertRaises(SyncFailure):
                self.adapter("google.calendar", response).fetch("old", None, mode="incremental", limit=10)

    def test_no_implicit_backfill_for_drive_or_gmail(self):
        for provider in ("google.drive", "google.gmail"):
            with self.subTest(provider=provider), self.assertRaises(SyncFailure):
                self.adapter(provider, {}).fetch(None, None, mode="backfill", limit=10)


class CrmDeltaAdapterTests(unittest.TestCase):
    def test_zoho_304_is_empty_successful_delta_window(self):
        calls = []

        class Gateway:
            def request(inner, service, method, path, **kwargs):
                calls.append(
                    (service, method, path, kwargs)
                )
                return {
                    "ok": True,
                    "status": 304,
                    "data": "",
                    "provider_path": "local",
                }

        adapter = CrmLeadDeltaAdapter(
            Gateway(),
            "5062683000000020005",
        )

        cursor = (
            datetime.now(timezone.utc)
            - timedelta(minutes=10)
        ).isoformat()

        page = adapter.fetch(
            cursor,
            None,
            mode="incremental",
            limit=100,
        )

        self.assertEqual(page.events, ())
        self.assertEqual(page.fetched_items, 0)
        self.assertIsNone(page.next_page)
        self.assertIsNotNone(page.next_cursor)

        self.assertEqual(len(calls), 1)
        service, method, path, kwargs = calls[0]

        self.assertEqual(service, "zohoapis")
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/crm/v8/Leads")
        self.assertIn("If-Modified-Since", kwargs["headers"])
        self.assertEqual(kwargs["query"]["sort_by"], "Modified_Time")
        self.assertEqual(kwargs["query"]["sort_order"], "asc")



class DeltaWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = AutomationStore(Path(self.tmp.name) / "automation.db")
        self.worker = DeltaWorker(self.store, lambda: "fixture")
        self.addCleanup(self.worker.stop)
        self.job = SyncJob(provider="google.calendar", source_account="account", stream="calendar", initial_cursor="existing", enabled=True)

    def test_disabled_worker_and_bounded_start_stop(self):
        self.worker.start([])
        self.assertTrue(self.worker.health()["healthy"])
        with patch("workflow.automation.sync_runtime.sync_one_due", return_value=None):
            self.worker.start([self.job])
            self.assertTrue(self.worker.health()["thread_alive"])
            with self.assertRaises(RuntimeError): self.worker.start([self.job])
            self.worker.stop()
        self.assertFalse(self.worker.health()["thread_alive"])

    def test_three_unexpected_faults_stop_without_logging_secret_exception(self):
        with patch("workflow.automation.sync_runtime.sync_one_due", side_effect=RuntimeError("never-log-fixture-secret")), patch.object(self.worker._stop, "wait", return_value=False):
            self.worker.start([self.job]); self.worker._thread.join(timeout=5)
        self.assertFalse(self.worker.health()["healthy"])
        self.assertEqual(self.worker.health()["consecutive_failures"], 3)
        audit = self.store.recent_audit()
        self.assertEqual(len(audit), 3)
        self.assertNotIn("never-log-fixture-secret", json.dumps(audit))

    def test_stalled_sync_worker_is_observed_independently(self):
        class LiveThread:
            def is_alive(self): return True
        self.worker.jobs = [self.job]; self.worker._thread = LiveThread()
        self.worker._last_progress = time.monotonic() - 181
        snapshot = AutomationHealthMonitor(self.store, sync_health=self.worker.health).evaluate({"enabled": False})
        self.assertIn("delta_worker_unhealthy", {row["code"] for row in snapshot["alerts"]})
        self.worker._thread = None
