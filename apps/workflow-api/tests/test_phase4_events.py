from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from _phase4_fixtures import make_v1
from workflow.automation import event_schema
from workflow.automation.engine import AutomationEngine
from workflow.automation.events import EventConflict, EventLedger, count
from workflow.automation.health_monitor import AutomationHealthMonitor
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore


class WalConnectionTests(unittest.TestCase):
    def test_already_wal_does_not_request_a_journal_mode_change(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = ("wal",)
        AutomationStore._enable_wal(connection)
        connection.execute.assert_called_once_with("PRAGMA journal_mode")

    def test_journal_mode_busy_retry_is_bounded_and_setup_only(self):
        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY | (2 << 8)):
            with self.subTest(code=code):
                error = sqlite3.OperationalError("fixture database is locked")
                error.sqlite_errorcode = code
                connection = Mock()
                connection.execute.side_effect = [Mock(fetchone=Mock(return_value=("delete",))), error,
                                                  Mock(fetchone=Mock(return_value=("wal",)))]
                with patch("workflow.automation.store.time.sleep") as slept:
                    AutomationStore._enable_wal(connection)
                slept.assert_called_once_with(0.05)
                self.assertEqual([call.args[0] for call in connection.execute.call_args_list],
                                 ["PRAGMA journal_mode", "PRAGMA journal_mode=WAL", "PRAGMA journal_mode"])

    def test_journal_mode_lock_timeout_closes_failed_connection(self):
        error = sqlite3.OperationalError("fixture database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        connection = Mock()
        connection.execute.side_effect = [Mock(fetchone=Mock(return_value=(2,))), error]
        store = object.__new__(AutomationStore)
        store.db_path = Path("/fixture-only/never-opened.db")
        with patch("workflow.automation.store.sqlite3.connect", return_value=connection), \
                patch("workflow.automation.store.time.monotonic", side_effect=[0, 30]), \
                self.assertRaises(sqlite3.OperationalError):
            store._connect()
        connection.close.assert_called_once()

    def test_non_lock_database_error_is_never_retried(self):
        error = sqlite3.OperationalError("fixture IO failure")
        error.sqlite_errorcode = sqlite3.SQLITE_IOERR
        connection = Mock()
        connection.execute.side_effect = error
        with patch("workflow.automation.store.time.sleep") as slept, self.assertRaises(sqlite3.OperationalError):
            AutomationStore._enable_wal(connection)
        slept.assert_not_called()

    def test_database_refusing_wal_fails_closed(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = ("delete",)
        with self.assertRaisesRegex(RuntimeError, "database requires WAL"):
            AutomationStore._enable_wal(connection)


def process_capture(path: str, barrier, output) -> None:
    store = AutomationStore(Path(path))
    barrier.wait(timeout=20)
    output.put(EventLedger(store).capture(AutomationEvent(event_type="fixture.changed", source="fixture",
        source_account="one", provider_event_id="native-1", payload={"id": "one"}))[0])


class EventFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "automation.db"
        self.store = AutomationStore(self.db)
        self.ledger = EventLedger(self.store)

    def event(self, **kwargs) -> AutomationEvent:
        return AutomationEvent.model_validate({"event_type": "fixture.changed", "source": "fixture", **kwargs})

    def workflow(self, workflow_id="fixture.workflow", action="core.noop") -> AutomationEngine:
        self.store.upsert_workflow(WorkflowDefinition.model_validate({"id": workflow_id, "name": "Fixture",
            "trigger": {"event_types": ["fixture.changed"]}, "steps": [{"id": "step", "action": action}]}))
        return AutomationEngine(self.store, self.root / "workflows")


class EventMigrationTests(EventFixture):
    def test_fresh_database_integrity_version_and_wal(self) -> None:
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchall()[0][0], "ok")
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_exact_v1_migration_preserves_events_runs_and_snapshots(self) -> None:
        path = self.root / "v1.db"
        make_v1(path)
        definition = WorkflowDefinition.model_validate({"id": "old", "name": "Old", "trigger": {"event_types": ["old"]},
                                                       "steps": [{"id": "one", "action": "core.noop"}]})
        snapshot = json.dumps({"queued_definition": definition.model_dump(by_alias=True)})
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO automation_events VALUES('old','old','old','2026-01-01T00:00:00Z','old',NULL,'old-key',0,'{}','2026-01-01T02:00:00+02:00')")
            conn.execute("INSERT INTO automation_workflows VALUES('old','Old',1,1,?,NULL,'2026-01-01T00:00:00Z')", (json.dumps(definition.model_dump()),))
            conn.execute("INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at,context_json) VALUES('old-run','old','old','old','queued','2026-01-01T00:00:00Z',?)", (snapshot,))
            before = conn.execute("SELECT * FROM automation_events").fetchall()
        migrated = AutomationStore(path)
        with migrated._connect() as conn:
            self.assertEqual(conn.execute("SELECT * FROM automation_events").fetchall()[0][:], before[0])
            self.assertEqual(conn.execute("SELECT context_json FROM automation_runs").fetchone()[0], snapshot)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(EventLedger(migrated).process_pending(), 0)
        self.assertEqual(EventLedger(migrated).inspect('old')["received_at"], "2026-01-01T00:00:00.000000Z")
        self.assertEqual([row["event_id"] for row in EventLedger(migrated).list_events(
            start="2026-01-01T00:00:00Z", end="2026-01-01T00:00:00Z")], ['old'])
        self.assertEqual(len(migrated.queued_envelopes()), 1)
        self.assertFalse(migrated.ingest_event(self.event(idempotency_key="old-key"))[0])

    def test_migration_idempotence_and_restart(self) -> None:
        path = self.root / "v1.db"
        make_v1(path)
        AutomationStore(path)
        with sqlite3.connect(path) as conn:
            before = conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
        AutomationStore(path)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall(), before)

    def test_migration_rolls_back_every_event_object(self) -> None:
        path = self.root / "v1.db"
        make_v1(path)
        with patch.object(event_schema, "DDL", (*event_schema.DDL, "CREATE TABLE automation_event_history(blocker TEXT)")):
            with self.assertRaises(sqlite3.OperationalError):
                AutomationStore(path)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='automation_event_ledger'").fetchone()[0], 0)
        AutomationStore(path)

    def test_partial_v1_refused_without_event_schema_mutation(self) -> None:
        path = self.root / "partial.db"
        make_v1(path)
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TABLE automation_events")
        with self.assertRaisesRegex(RuntimeError, "legacy schema mismatch"):
            AutomationStore(path)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='automation_event_ledger'").fetchone()[0], 0)

    def test_v1_foreign_key_corruption_aborts_migration(self) -> None:
        path = self.root / "broken.db"
        make_v1(path)
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) VALUES('r','missing','missing','c','queued','now')")
        with self.assertRaises((RuntimeError, sqlite3.IntegrityError)):
            AutomationStore(path)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_v2_missing_unique_constraint_is_refused(self) -> None:
        with self.store._connect() as conn:
            conn.execute("DROP TRIGGER event_dedupe_immutable")
            conn.execute("DROP TRIGGER event_dedupe_retained")
            conn.execute("DROP TABLE automation_event_dedupe")
            conn.execute("CREATE TABLE automation_event_dedupe(source TEXT,source_account TEXT,identity TEXT,event_id TEXT)")
        with self.assertRaisesRegex(RuntimeError, "incomplete event schema"):
            AutomationStore(self.db)

    def test_legacy_secret_is_preserved_only_in_original_history(self) -> None:
        path = self.root / "legacy-secret.db"; make_v1(path)
        payload = json.dumps({"access_token": "legacy-fixture-secret"})
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO automation_events VALUES('legacy','fixture','fixture','2026-01-01T00:00:00Z','legacy',NULL,NULL,0,?,'2026-01-01T00:00:00Z')", (payload,))
        migrated = AutomationStore(path)
        self.assertEqual(EventLedger(migrated).inspect("legacy")["envelope"]["payload"]["access_token"], "[REDACTED]")
        with migrated._connect() as conn:
            self.assertEqual(conn.execute("SELECT payload_json FROM automation_events").fetchone()[0], payload)

    def test_legacy_sensitive_unresolved_work_refuses_migration(self) -> None:
        path = self.root / "legacy-active-secret.db"; make_v1(path)
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO automation_events VALUES('legacy','fixture','fixture','2026-01-01T00:00:00Z','legacy',NULL,NULL,0,?, '2026-01-01T00:00:00Z')", (json.dumps({"password": "legacy-fixture"}),))
            conn.execute("INSERT INTO automation_workflows VALUES('old','Old',1,1,'{}',NULL,'2026-01-01T00:00:00Z')")
            conn.execute("INSERT INTO automation_runs(run_id,workflow_id,event_id,correlation_id,status,created_at) VALUES('old','old','legacy','legacy','queued','2026-01-01T00:00:00Z')")
        with self.assertRaisesRegex(RuntimeError, "sensitive unresolved"):
            AutomationStore(path)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='automation_event_ledger'").fetchone()[0], 0)

    def test_backup_restore_migrated_database(self) -> None:
        accepted, event_id, _ = self.ledger.capture(self.event(provider_event_id="one"))
        self.assertTrue(accepted)
        copy = self.root / "restore.db"
        with self.store._connect() as source, sqlite3.connect(copy) as destination:
            source.backup(destination)
        restored = EventLedger(AutomationStore(copy))
        self.assertIsNotNone(restored.inspect(event_id))
        self.assertFalse(restored.capture(self.event(provider_event_id="one"))[0])
        with sqlite3.connect(copy) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_concurrent_fresh_startup_and_migration(self) -> None:
        for legacy in (False, True):
            path = self.root / f"startup-{legacy}.db"
            if legacy:
                make_v1(path)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                stores = list(pool.map(lambda _: AutomationStore(path), range(8)))
            self.assertEqual(len(stores), 8)
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_wal_reader_survives_concurrent_v1_migration(self) -> None:
        path = self.root / "reader-v1.db"
        make_v1(path)
        with sqlite3.connect(path) as reader:
            reader.execute("PRAGMA journal_mode=WAL")
            reader.execute("BEGIN")
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM automation_events").fetchone()[0], 0)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                migrated = pool.submit(AutomationStore, path).result(timeout=30)
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM automation_events").fetchone()[0], 0)
            reader.commit()
            self.assertEqual(reader.execute("PRAGMA user_version").fetchone()[0], 2)


class EventLedgerTests(EventFixture):
    def test_native_dedupe_and_account_scope(self) -> None:
        a = self.ledger.capture(self.event(provider_event_id="same", source_account="a"))
        b = self.ledger.capture(self.event(provider_event_id="same", source_account="a"))
        c = self.ledger.capture(self.event(provider_event_id="same", source_account="b"))
        self.assertTrue(a[0]); self.assertFalse(b[0]); self.assertTrue(c[0])
        self.assertEqual(a[1], b[1]); self.assertNotEqual(a[1], c[1])

    def test_provider_scope_is_separate(self) -> None:
        self.assertTrue(self.ledger.capture(self.event(provider_event_id="same"))[0])
        self.assertTrue(self.ledger.capture(self.event(provider_event_id="same", source="other"))[0])

    def test_fallback_dedupe_is_canonical(self) -> None:
        one = self.ledger.capture(self.event(payload={"b": 2, "a": 1}))
        two = self.ledger.capture(self.event(payload={"a": 1, "b": 2}))
        self.assertTrue(one[0]); self.assertFalse(two[0])

    def test_internal_phase3_identity_does_not_collapse_distinct_events(self) -> None:
        self.assertTrue(self.store.ingest_event(self.event())[0])
        self.assertTrue(self.store.ingest_event(self.event())[0])

    def test_restart_preserves_dedupe(self) -> None:
        one = self.ledger.capture(self.event(provider_event_id="same"))
        restarted = EventLedger(AutomationStore(self.db))
        self.assertEqual(restarted.capture(self.event(provider_event_id="same"))[1], one[1])
        self.assertEqual(restarted.inspect(one[1])["duplicate_count"], 1)

    def test_thread_concurrency_has_one_logical_event(self) -> None:
        def ingest(_):
            return EventLedger(AutomationStore(self.db)).capture(self.event(provider_event_id="race"))[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(ingest, range(24))), 1)
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_events").fetchone()[0], 1)

    def test_process_concurrency_has_one_logical_event(self) -> None:
        ctx = multiprocessing.get_context("fork")
        barrier, output = ctx.Barrier(6), ctx.Queue()
        processes = [ctx.Process(target=process_capture, args=(str(self.db), barrier, output)) for _ in range(6)]
        for process in processes:
            process.start()
        results = [output.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(results), 1)

    def test_conflicting_provider_identity_refused(self) -> None:
        event_id = self.ledger.capture(self.event(provider_event_id="one", payload={"value": 1}))[1]
        with self.assertRaises(EventConflict):
            self.ledger.capture(self.event(provider_event_id="one", payload={"value": 2}))
        self.assertEqual(self.ledger.inspect(event_id)["envelope"]["payload"], {"value": 1})

    def test_immutable_database_guards(self) -> None:
        event_id = self.ledger.capture(self.event())[1]
        for statement in ("UPDATE automation_events SET source='changed' WHERE event_id=?",
                          "UPDATE automation_event_ledger SET content_hash='x' WHERE event_id=?",
                          "DELETE FROM automation_events WHERE event_id=?",
                          "DELETE FROM automation_event_ledger WHERE event_id=?",
                          "DELETE FROM automation_event_dedupe WHERE event_id=?"):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError), self.store._connect() as conn:
                conn.execute(statement, (event_id,))

    def test_secret_payload_and_evidence_redaction(self) -> None:
        event_id = self.ledger.capture(self.event(payload={"access_token": "neverpersist", "nested": {"Password": "hide"},
            "note": "Bearer abcxyz"}, provider_evidence={"Authorization": "private", "resource_id": "ok"}))[1]
        with self.store._connect() as conn:
            persisted = conn.execute("SELECT envelope_json FROM automation_event_ledger WHERE event_id=?", (event_id,)).fetchone()[0]
        for secret in ("neverpersist", "hide", "abcxyz", "private"):
            self.assertNotIn(secret, persisted)
        self.assertEqual(self.ledger.inspect(event_id)["envelope"]["provider_evidence"], {"resource_id": "ok"})

    def test_redacted_payload_never_becomes_provider_action_input(self) -> None:
        engine = self.workflow(action="fixture.external")
        calls = []
        engine.register_action("fixture.external", lambda context, step: calls.append(1))
        response = engine.ingest(self.event(payload={"password": "fixture-sensitive-value"}))
        self.assertEqual(response.run_ids, [])
        self.assertEqual(calls, [])
        self.assertEqual(self.ledger.inspect(response.event_id)["last_error"], "sensitive_payload_requires_review")

    def test_normalized_provider_identity_conflicts_remain_fail_closed(self) -> None:
        engine = self.workflow()
        engine.ingest(self.event(provider_event_id="native", payload={"value": 1}))
        with self.assertRaises(EventConflict):
            engine.ingest(self.event(provider_event_id="native", payload={"value": 2}))
        self.assertEqual(len(self.store.recent_runs()), 1)

    def test_timestamps_utc_and_invalid_naive_rejected(self) -> None:
        event = self.event(provider_timestamp="2026-09-28T12:00:00+02:00", occurred_at="2026-09-28T12:00:00+02:00")
        self.assertEqual(event.provider_timestamp, "2026-09-28T10:00:00.000000Z")
        for stamp in ("invalid", "2026-09-28T12:00:00"):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                self.event(provider_timestamp=stamp)

    def test_time_window_preserves_microsecond_precision_and_timezone(self) -> None:
        with patch("workflow.automation.events.utc_now_iso", return_value="2026-09-28T00:00:00.000100Z"):
            first = self.ledger.capture(self.event(provider_event_id="precision-one"))[1]
        with patch("workflow.automation.events.utc_now_iso", return_value="2026-09-28T00:00:00.000200Z"):
            second = self.ledger.capture(self.event(provider_event_id="precision-two"))[1]
        rows = self.ledger.list_events(start="2026-09-28T01:00:00.000100+01:00",
                                      end="2026-09-28T00:00:00.000100Z")
        self.assertEqual([row["event_id"] for row in rows], [first])
        self.assertEqual([row["event_id"] for row in self.ledger.list_events(
            start="2026-09-28T00:00:00.000200Z")], [second])

    def test_receipt_clock_constraint_rejects_noncanonical_storage(self) -> None:
        self.ledger.capture(self.event(provider_event_id="clock-fixture"))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CHECK constraint"), self.store._connect() as conn:
            conn.execute("INSERT INTO automation_events SELECT 'bad-clock',event_type,source,occurred_at,"
                         "correlation_id,causation_id,NULL,depth,payload_json,created_at FROM automation_events LIMIT 1")
            conn.execute("INSERT INTO automation_event_ledger SELECT 'bad-clock',source_account,NULL,'bad-clock',"
                         "content_hash,envelope_json,'2026-09-28T00:00:00Z',NULL,'bad-clock' "
                         "FROM automation_event_ledger LIMIT 1")
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_events").fetchone()[0], 1)

    def test_bounds_and_self_causation(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.capture(self.event(payload={"large": "x" * 1048576}))
        with self.assertRaises(ValueError):
            self.event(event_id="same", causation_id="same")
        for limit in (0, 101, True):
            with self.assertRaises(ValueError):
                self.ledger.list_events(limit=limit)

    def test_indirect_causation_cycle_rejected(self) -> None:
        self.ledger.capture(self.event(event_id="a", causation_id="b", dedupe_identity="a"))
        self.ledger.capture(self.event(event_id="b", causation_id="c", dedupe_identity="b"))
        with self.assertRaisesRegex(ValueError, "circular"):
            self.ledger.capture(self.event(event_id="c", causation_id="a", dedupe_identity="c"))

    def test_durable_capture_is_decoupled_and_routes_after_restart(self) -> None:
        engine = self.workflow()
        event_id = self.ledger.capture(self.event())[1]
        self.assertEqual(self.store.recent_runs(), [])
        restarted = AutomationEngine(AutomationStore(self.db), self.root / "workflows")
        self.assertEqual(restarted.recover_pending()["executed"], 1)
        self.assertEqual(self.store.recent_runs()[0]["status"], "completed")
        self.assertEqual(self.ledger.inspect(event_id)["status"], "routed")

    def test_restart_preserves_entire_provider_event_envelope_for_execution(self) -> None:
        engine = self.workflow(action="fixture.inspect")
        seen = []
        engine.register_action("fixture.inspect", lambda context, step: seen.append(context["event"]) or {})
        event = self.event(source_account="provider-account", provider_event_id="native", subject_id="subject", provider_timestamp="2026-01-01T00:00:00Z")
        event_id = self.ledger.capture(event)[1]
        self.ledger.process(event_id)
        engine.recover_pending()
        self.assertEqual(seen[0], self.ledger.inspect(event_id)["envelope"])

    def test_routing_race_has_one_workflow_run(self) -> None:
        self.workflow()
        event_id = self.ledger.capture(self.event())[1]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: EventLedger(AutomationStore(self.db)).process(event_id), range(16)))
        self.assertEqual(len(self.store.recent_runs()), 1)

    def test_low_level_legacy_run_also_fences_new_routing(self) -> None:
        self.workflow()
        event_id = self.store.ingest_event(self.event())[1]
        run_id = self.store.create_run("fixture.workflow", event_id, event_id)
        self.ledger.process_pending()
        self.assertEqual(len(self.store.recent_runs()), 1)
        self.assertEqual(self.ledger.inspect(event_id)["routes"][0]["run_id"], run_id)

    def test_processor_transaction_interruption_leaves_event_pending(self) -> None:
        self.workflow()
        event_id = self.ledger.capture(self.event())[1]
        with patch("workflow.automation.events.uuid4", side_effect=RuntimeError("interruption")):
            with self.assertRaises(RuntimeError):
                self.ledger.process(event_id)
        self.assertEqual(self.ledger.inspect(event_id)["status"], "accepted")
        self.assertEqual(self.store.recent_runs(), [])
        self.ledger.process(event_id)
        self.assertEqual(len(self.store.recent_runs()), 1)

    def test_child_event_propagates_correlation_causation_and_dedupe(self) -> None:
        self.store.upsert_workflow(WorkflowDefinition.model_validate({"id": "parent", "name": "Parent",
            "trigger": {"event_types": ["fixture.changed"]}, "steps": [{"id": "child", "action": "event.emit",
            "with": {"event_type": "child.event", "payload": {"ok": True}}}]}))
        engine = AutomationEngine(self.store, self.root / "workflows")
        parent = self.event(correlation_id="correlation")
        engine.ingest(parent)
        with self.store._connect() as conn:
            child = conn.execute("SELECT * FROM automation_events WHERE event_type='child.event'").fetchone()
        self.assertEqual(child["correlation_id"], "correlation")
        self.assertEqual(child["causation_id"], parent.event_id)
        self.assertTrue(child["idempotency_key"].startswith("action:"))

    def test_unsupported_schema_quarantines_before_execution(self) -> None:
        self.workflow()
        event_id = self.ledger.capture(self.event(event_version=2))[1]
        self.ledger.process(event_id)
        self.assertEqual(self.ledger.inspect(event_id)["status"], "quarantined")
        self.assertEqual(self.store.recent_runs(), [])

    def test_poison_event_has_three_bounded_attempts(self) -> None:
        self.workflow()
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_workflows SET definition_json='{}'")
        event_id = self.ledger.capture(self.event())[1]
        for _ in range(10):
            self.ledger.process_pending()
        result = self.ledger.inspect(event_id)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(self.store.recent_runs(), [])

    def test_usage_is_durable_and_duplicates_are_counted(self) -> None:
        event = self.event(provider_event_id="counter")
        self.ledger.capture(event); self.ledger.capture(event)
        result = {(r["provider"], r["metric"]): r["value"] for r in EventLedger(AutomationStore(self.db)).usage()}
        self.assertEqual(result[("fixture", "events_received")], 2)
        self.assertEqual(result[("fixture", "events_accepted")], 1)
        self.assertEqual(result[("fixture", "duplicates_suppressed")], 1)

    def test_accounting_retention_preserves_event_and_dedupe(self) -> None:
        event_id = self.ledger.capture(self.event(provider_event_id="retain"))[1]
        with self.store._connect() as conn:
            count(conn, "fixture", "events_received", day="2000-01-01")
        self.assertGreater(self.ledger.cleanup(), 0)
        self.assertIsNotNone(self.ledger.inspect(event_id))
        self.assertFalse(self.ledger.capture(self.event(provider_event_id="retain"))[0])
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_usage_daily WHERE day='2000-01-01'").fetchone()[0], 0)

    def test_accounting_provider_dimensions_are_bounded(self) -> None:
        for i in range(100):
            self.ledger.record_usage(f"provider-{i}", "events_received")
        with self.store._connect() as conn:
            self.assertLessEqual(conn.execute("SELECT COUNT(DISTINCT provider) FROM automation_usage_daily").fetchone()[0], 65)
        self.assertTrue(any(row["provider"] == "other" for row in self.ledger.usage()))

    def test_health_exposes_backlog_and_quarantine_alert(self) -> None:
        self.ledger.capture(self.event(event_version=2)); self.ledger.process_pending()
        snapshot = AutomationHealthMonitor(self.store).evaluate({"enabled": False})
        self.assertIn("event_quarantine", {a["code"] for a in snapshot["alerts"]})


class EventReplayTests(EventFixture):
    def replay(self, event_id, key="replay-request-one"):
        return self.ledger.replay(event_id, request_key=key, actor="operator", reason="Controlled review replay")

    def test_replay_lineage_original_immutability_audit_and_request_dedupe(self) -> None:
        engine = self.workflow()
        event = self.event(correlation_id="correlation")
        engine.ingest(event)
        before = self.ledger.inspect(event.event_id)["envelope"]
        replay = self.replay(event.event_id)
        self.assertFalse(replay["duplicate"])
        self.assertTrue(self.replay(event.event_id)["duplicate"])
        self.ledger.process(replay["event_id"])
        result = self.ledger.inspect(replay["event_id"])
        self.assertEqual(result["replay_of"], event.event_id)
        self.assertEqual(result["envelope"]["causation_id"], event.event_id)
        self.assertEqual(result["envelope"]["correlation_id"], "correlation")
        self.assertEqual(before, self.ledger.inspect(event.event_id)["envelope"])
        self.assertEqual(len(self.store.recent_runs()), 1)
        audit = {row["action"] for row in self.store.recent_audit()}
        self.assertTrue({"replay_initiated", "replay_outcome"} <= audit)

    def test_replay_race_has_one_identity(self) -> None:
        event_id = self.ledger.capture(self.event())[1]
        self.ledger.process(event_id)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(lambda _: self.replay(event_id), range(16)))
        self.assertEqual(sum(not r["duplicate"] for r in result), 1)
        self.assertEqual(len({r["event_id"] for r in result}), 1)

    def test_replay_of_replay_is_prohibited(self) -> None:
        event_id = self.ledger.capture(self.event())[1]; self.ledger.process(event_id)
        replay = self.replay(event_id); self.ledger.process(replay["event_id"])
        with self.assertRaises(ValueError):
            self.replay(replay["event_id"], "second-replay-request")

    def test_ambiguous_workflow_is_never_repeated_by_replay(self) -> None:
        engine = self.workflow(action="fixture.external")
        calls = []
        def external(context, step):
            calls.append(1)
            raise TimeoutError("ambiguous transport")
        engine.register_action("fixture.external", external)
        event = self.event(); response = engine.ingest(event)
        self.assertEqual(self.store.get_run(response.run_ids[0])["status"], "human_action_required")
        with self.assertRaises(ValueError):
            self.replay(event.event_id)
        engine.recover_pending()
        self.assertEqual(calls, [1])

    def test_successful_external_workflow_route_is_not_repeated(self) -> None:
        engine = self.workflow(action="fixture.external")
        calls = []
        engine.register_action("fixture.external", lambda c, s: calls.append(1) or {"ok": True})
        event = self.event(); engine.ingest(event)
        self.replay(event.event_id); engine.recover_pending()
        self.assertEqual(calls, [1])

    def test_new_external_route_on_replay_quarantines_all_routes_atomically(self) -> None:
        event_id = self.ledger.capture(self.event())[1]; self.ledger.process(event_id)
        self.workflow("a.internal")
        self.workflow("z.external", action="fixture.external")
        replay = self.replay(event_id); self.ledger.process(replay["event_id"])
        self.assertEqual(self.ledger.inspect(replay["event_id"])["status"], "quarantined")
        self.assertEqual(self.store.recent_runs(), [])

    def test_quarantine_release_after_processor_correction_creates_new_event(self) -> None:
        engine = self.workflow()
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_workflows SET definition_json='{}'")
        event_id = self.ledger.capture(self.event())[1]
        for _ in range(3): self.ledger.process(event_id)
        self.workflow()
        replay = self.replay(event_id); engine.recover_pending()
        self.assertEqual(self.ledger.inspect(event_id)["status"], "quarantined")
        self.assertEqual(self.ledger.inspect(replay["event_id"])["status"], "routed")
        self.assertEqual(self.store.recent_runs()[0]["status"], "completed")

    def test_pending_or_active_execution_cannot_be_replayed(self) -> None:
        self.workflow()
        event_id = self.ledger.capture(self.event())[1]
        with self.assertRaises(ValueError): self.replay(event_id)
        self.ledger.process(event_id)
        with self.assertRaises(ValueError): self.replay(event_id)

    def test_replay_key_cannot_be_rebound_to_other_event(self) -> None:
        first = self.ledger.capture(self.event(dedupe_identity="a"))[1]
        second = self.ledger.capture(self.event(dedupe_identity="b"))[1]
        self.ledger.process_pending(); self.replay(first)
        with self.assertRaises(ValueError): self.replay(second)
