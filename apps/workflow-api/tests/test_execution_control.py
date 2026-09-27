from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.store import AutomationStore


class ProviderError(Exception):
    def __init__(self, status: int, retry_after: str | None = None) -> None:
        super().__init__("provider response")
        self.response = SimpleNamespace(status_code=status, headers={
            "Retry-After": retry_after} if retry_after is not None else {})


class ExecutionControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "automation.db"
        self.workflows = self.root / "workflows"
        self.workflows.mkdir()
        self.store = AutomationStore(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def database_snapshot(db: Path) -> tuple:
        with sqlite3.connect(db) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            schema = conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
            ).fetchall()
            tables = [row[1] for row in schema if row[0] == "table"]
            data = {table: conn.execute(f'SELECT * FROM "{table}"').fetchall()
                    for table in tables if table != "sqlite_sequence"}
        return version, schema, data, hashlib.sha256(db.read_bytes()).hexdigest()

    def test_unknown_schema_version_causes_zero_mutation(self) -> None:
        for future_objects in (False, True):
            with self.subTest(future_objects=future_objects):
                db = self.root / f"future-{future_objects}.db"
                with sqlite3.connect(db) as conn:
                    conn.execute("PRAGMA user_version=2")
                    if future_objects:
                        conn.execute("CREATE TABLE future_actions(id INTEGER PRIMARY KEY,payload TEXT)")
                        conn.execute("CREATE INDEX future_actions_payload ON future_actions(payload)")
                        conn.execute("CREATE TRIGGER future_actions_guard AFTER UPDATE ON future_actions "
                                     "BEGIN SELECT RAISE(ABORT,'future guard'); END")
                        conn.execute("INSERT INTO future_actions(payload) VALUES('preserve me')")
                before = self.database_snapshot(db)
                with self.assertRaisesRegex(RuntimeError, "unknown automation schema version: 2"):
                    AutomationStore(db)
                self.assertEqual(self.database_snapshot(db), before)

    def test_version_zero_initializes_and_version_one_reopens_without_schema_changes(self) -> None:
        db = self.root / "versioned.db"
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        AutomationStore(db)
        before = self.database_snapshot(db)
        self.assertEqual(before[0], 1)
        self.assertIn("automation_run_claims", before[2])
        self.assertIn("automation_run_failures", before[2])
        AutomationStore(db)
        self.assertEqual(self.database_snapshot(db)[:3], before[:3])

    def engine(self, *, attempts: int = 1, action: str = "fixture.action",
               inputs: str = "target_id: target-7", on_error: str = "stop") -> AutomationEngine:
        (self.workflows / "fixture.yaml").write_text(
            f"""id: fixture.workflow
name: Fixture workflow
version: 3
enabled: true
trigger:
  event_types: [fixture.event]
steps:
  - id: operation
    action: {action}
    with:
      {inputs}
    on_error: {on_error}
    retry:
      max_attempts: {attempts}
      backoff_seconds: 2
""", encoding="utf-8")
        engine = AutomationEngine(self.store, self.workflows)
        engine.sync_definitions()
        return engine

    def queue(self) -> tuple[str, AutomationEvent]:
        event = AutomationEvent(event_type="fixture.event", source="unit",
                                idempotency_key="logical-event")
        accepted, _, _, runs = self.store.ingest_event_and_runs(event)
        self.assertTrue(accepted)
        self.assertEqual(len(runs), 1)
        return runs[0][0], event

    def test_integer_lease_clock_never_recovers_or_steals_early(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        claimed = datetime(2026, 1, 1, 0, 0, 0, 500000, timezone.utc)
        expires = claimed + timedelta(seconds=5)
        token = self.store.claim_run(run_id, "worker-a", lease_seconds=5, now=claimed)
        with self.store._connect() as conn:
            row = conn.execute("SELECT claimed_at,lease_expires_at FROM automation_run_claims "
                               "WHERE run_id=?", (run_id,)).fetchone()
            self.assertEqual((type(row[0]), type(row[1])), (int, int))
            self.assertEqual(row[1] - row[0], 5_000_000)
        for now in (expires - timedelta(microseconds=500000),
                    expires - timedelta(microseconds=1)):
            with self.subTest(now=now):
                self.assertEqual(self.store.execution_health(now=now)["expired_leases"], 0)
                self.assertEqual(self.store.recover_expired_claims(now=now)["requeued"], 0)
                self.assertIsNone(self.store.claim_run(run_id, "worker-b", now=now))
                self.assertEqual(self.store.get_run(run_id)["status"], "claimed")
        at_expiry = self.store.execution_health(now=expires)
        self.assertEqual(at_expiry["expired_leases"], 1)
        self.assertEqual(at_expiry["oldest_claim_age_seconds"], 5)
        self.assertEqual(self.store.recover_expired_claims(now=expires)["requeued"], 1)
        self.assertIsNone(self.store.begin_claimed_action(
            run_id, token, step_id="operation", action="fixture.action",
            action_identity="a" * 64, attempt=1, now=expires))

    def test_integer_lease_clock_rejects_exact_and_late_renewal(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        claimed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expires = claimed + timedelta(seconds=5)
        token = self.store.claim_run(run_id, "worker-a", lease_seconds=5, now=claimed)
        self.assertFalse(self.store.renew_claim(run_id, token, now=expires))
        self.assertFalse(self.store.renew_claim(
            run_id, token, now=expires + timedelta(microseconds=1)))
        self.assertFalse(self.store.renew_claim(
            run_id, token, now=expires + timedelta(microseconds=100000)))
        self.assertTrue(self.store.renew_claim(
            run_id, token, now=expires - timedelta(microseconds=1), lease_seconds=5))
        self.assertEqual(self.store.recover_expired_claims(now=expires)["requeued"], 0)
        self.assertEqual(self.store.recover_expired_claims(
            now=expires + timedelta(seconds=5) - timedelta(microseconds=2))["requeued"], 0)
        self.assertEqual(self.store.recover_expired_claims(
            now=expires + timedelta(seconds=5) - timedelta(microseconds=1))["requeued"], 1)

    def test_completion_fence_uses_exact_microsecond_expiry(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        claimed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expires = claimed + timedelta(seconds=5)
        token = self.store.claim_run(run_id, "worker-a", lease_seconds=5, now=claimed)
        marker = self.store.begin_claimed_action(
            run_id, token, step_id="operation", action="fixture.action",
            action_identity="a" * 64, attempt=1, now=claimed)
        self.assertIsNotNone(marker)
        self.assertFalse(self.store.complete_claimed_action(
            run_id, token, marker, succeeded=True, now=expires))
        self.assertFalse(self.store.complete_claimed_action(
            run_id, token, marker, succeeded=True,
            now=expires + timedelta(microseconds=1)))
        self.assertTrue(self.store.complete_claimed_action(
            run_id, token, marker, succeeded=True, result={"ok": True},
            final_context={"done": True}, now=expires - timedelta(microseconds=1)))
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")
        self.assertEqual(self.store.recover_expired_claims(now=expires + timedelta(days=1)),
                         {"requeued": 0, "human_action_required": 0})

    def test_marked_claim_escalates_only_at_exact_expiry(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        claimed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expires = claimed + timedelta(seconds=5)
        token = self.store.claim_run(run_id, "worker-a", lease_seconds=5, now=claimed)
        self.assertIsNotNone(self.store.begin_claimed_action(
            run_id, token, step_id="operation", action="fixture.action",
            action_identity="a" * 64, attempt=1, now=claimed))
        self.assertEqual(self.store.recover_expired_claims(
            now=expires - timedelta(microseconds=1))["human_action_required"], 0)
        self.assertEqual(self.store.recover_expired_claims(
            now=expires)["human_action_required"], 1)
        self.assertEqual(self.store.get_run(run_id)["status"], "human_action_required")

    def test_two_executors_race_one_handler_execution(self) -> None:
        first = self.engine()
        other_store = AutomationStore(self.db)
        second = AutomationEngine(other_store, self.workflows)
        second.sync_definitions()
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def handler(context, step):
            calls.append(context["execution"]["action_identity"])
            entered.set()
            release.wait(5)
            return {"ok": True}

        first.register_action("fixture.action", handler)
        second.register_action("fixture.action", handler)
        result = []
        thread = threading.Thread(target=lambda: result.append(
            first.execute_run(run_id, definition, event, worker_id="worker-a")))
        thread.start()
        self.assertTrue(entered.wait(5))
        self.assertFalse(second.execute_run(run_id, definition, event, worker_id="worker-b"))
        release.set()
        thread.join(5)
        self.assertEqual(result, [True])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")

    def test_restart_recovers_queued_snapshot_and_duplicate_event(self) -> None:
        self.engine()
        run_id, event = self.queue()
        duplicate = self.store.ingest_event_and_runs(AutomationEvent(
            event_type="fixture.event", source="unit", idempotency_key=event.idempotency_key))
        self.assertFalse(duplicate[0])
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        restarted.sync_definitions()
        calls = []
        restarted.register_action("fixture.action", lambda context, step: calls.append(1) or {"ok": True})
        self.assertEqual(restarted.recover_pending()["executed"], 1)
        self.assertEqual(restarted.recover_pending()["executed"], 0)
        self.assertEqual(calls, [1])
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")

    def test_expired_never_started_claim_requeues_then_executes(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        token = self.store.claim_run(run_id, "dead-worker", lease_seconds=5)
        self.assertIsNotNone(token)
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (0, run_id))
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        restarted.sync_definitions()
        restarted.register_action("fixture.action", lambda context, step: {"ok": True})
        self.assertEqual(restarted.recover_pending(),
                         {"requeued": 1, "human_action_required": 0, "executed": 1})
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")

    def test_crash_before_action_marker_is_recoverable(self) -> None:
        engine = self.engine()
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        with patch.object(self.store, "begin_claimed_action", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                engine.execute_run(run_id, definition, event)
        self.assertEqual(self.store.get_run(run_id)["status"], "claimed")
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (0, run_id))
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        restarted.sync_definitions()
        calls = []
        restarted.register_action("fixture.action", lambda context, step: calls.append(1) or {"ok": True})
        self.assertEqual(restarted.recover_pending()["executed"], 1)
        self.assertEqual(calls, [1])

    def test_crash_after_handler_start_never_replays_write(self) -> None:
        engine = self.engine(attempts=3)
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []

        def crashed_write(context, step):
            calls.append(1)
            raise SystemExit("worker killed after send")

        engine.register_action("fixture.action", crashed_write)
        with self.assertRaises(SystemExit):
            engine.execute_run(run_id, definition, event)
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (0, run_id))
        self.assertEqual(engine.recover_pending()["human_action_required"], 1)
        self.assertEqual(engine.recover_pending()["executed"], 0)
        self.assertEqual(calls, [1])
        self.assertEqual(self.store.failed_work()[0]["reason_code"], "lease_expired_after_action")
        with self.store._connect() as conn:
            marker = conn.execute("SELECT id FROM automation_run_steps WHERE run_id=?", (run_id,)).fetchone()[0]
            token = conn.execute("SELECT attempt_id FROM automation_run_claims WHERE run_id=?",
                                 (run_id,)).fetchone()[0]
        self.assertFalse(self.store.complete_claimed_action(run_id, token, marker, succeeded=True))

    def test_crash_after_action_marker_before_handler_requires_reconciliation(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        token = self.store.claim_run(run_id, "crashed-worker", lease_seconds=5)
        marker = self.store.begin_claimed_action(
            run_id, token, step_id="operation", action="fixture.action",
            action_identity="a" * 64, attempt=1)
        self.assertIsNotNone(marker)
        with self.store._connect() as conn:
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (0, run_id))
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        calls = []
        restarted.register_action("fixture.action", lambda context, step: calls.append(1))
        self.assertEqual(restarted.recover_pending()["human_action_required"], 1)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get_run(run_id)["status"], "human_action_required")

    def test_crash_after_provider_response_before_result_commit_never_replays(self) -> None:
        engine = self.engine(attempts=3)
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []
        engine.register_action("fixture.action", lambda context, step: calls.append(1) or {"ok": True})
        with patch.object(self.store, "complete_claimed_action", side_effect=SystemExit("after response")):
            with self.assertRaises(SystemExit):
                engine.execute_run(run_id, definition, event)
        with self.store._connect() as conn:
            marker = conn.execute(
                "SELECT status,action_identity FROM automation_run_steps WHERE run_id=?", (run_id,)
            ).fetchone()
            self.assertEqual(marker["status"], "started")
            self.assertEqual(len(marker["action_identity"]), 64)
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (0, run_id))
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        restarted.register_action("fixture.action", lambda context, step: calls.append(1))
        self.assertEqual(restarted.recover_pending()["human_action_required"], 1)
        self.assertEqual(calls, [1])
        self.assertEqual(self.store.get_run(run_id)["status"], "human_action_required")
        self.assertEqual(self.store.failure_history(run_id)[0]["reason_code"],
                         "lease_expired_after_action")

    def test_crash_after_successful_result_commit_preserves_completion(self) -> None:
        engine = self.engine()
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []
        engine.register_action("fixture.action", lambda context, step: calls.append(1) or {"ok": True})
        complete = self.store.complete_claimed_action

        def crash_after_commit(*args, **kwargs):
            self.assertTrue(complete(*args, **kwargs))
            raise SystemExit("after durable result commit")

        with patch.object(self.store, "complete_claimed_action", side_effect=crash_after_commit):
            with self.assertRaises(SystemExit):
                engine.execute_run(run_id, definition, event)
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        restarted.register_action("fixture.action", lambda context, step: calls.append(1))
        self.assertEqual(restarted.recover_pending(),
                         {"requeued": 0, "human_action_required": 0, "executed": 0})
        self.assertEqual(calls, [1])
        run = self.store.get_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["steps"][0]["status"], "completed")
        self.assertEqual(run["steps"][0]["result"], {"ok": True})

    def test_restart_during_valid_lease_does_not_steal_claim(self) -> None:
        self.engine()
        run_id, _ = self.queue()
        token = self.store.claim_run(run_id, "first-worker", lease_seconds=300)
        restarted = AutomationEngine(AutomationStore(self.db), self.workflows)
        self.assertEqual(restarted.recover_pending(),
                         {"requeued": 0, "human_action_required": 0, "executed": 0})
        self.assertEqual(self.store.get_run(run_id)["status"], "claimed")
        self.assertIsNone(restarted.store.claim_run(run_id, "other-worker"))
        with self.store._connect() as conn:
            self.assertEqual(conn.execute(
                "SELECT attempt_id FROM automation_run_claims WHERE run_id=?", (run_id,)
            ).fetchone()[0], token)
            conn.execute("UPDATE automation_run_claims SET lease_expires_at=? WHERE run_id=?",
                         (0, run_id))
        self.assertEqual(restarted.store.recover_expired_claims()["requeued"], 1)

    def test_stable_logical_identity_and_duplicate_step_fence(self) -> None:
        engine = self.engine(attempts=2)
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        keys = []

        def transient_read(context, step):
            keys.append(context["execution"]["action_identity"])
            if len(keys) == 1:
                raise TimeoutError("before send")
            return {"ok": True}

        engine.register_action("fixture.action", transient_read, retry_safe=True)
        with patch("workflow.automation.engine.time.sleep"):
            self.assertTrue(engine.execute_run(run_id, definition, event))
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])
        run = self.store.get_run(run_id)
        self.assertEqual([step["action_identity"] for step in run["steps"]], keys)
        self.assertEqual(run["status"], "completed")
        self.assertFalse(engine.execute_run(run_id, definition, event))
        with self.store._connect() as conn:
            token = conn.execute("SELECT attempt_id FROM automation_run_claims WHERE run_id=?",
                                 (run_id,)).fetchone()[0]
        self.assertIsNone(self.store.begin_claimed_action(
            run_id, token, step_id="operation", action="fixture.action",
            action_identity=keys[0], attempt=3))

    def test_logical_identity_changes_with_target_or_operation_version(self) -> None:
        engine = self.engine()
        run_id, _ = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        step = definition.steps[0]
        first = engine.action_identity(run_id, definition, step, {"target_id": "one", "value": 1})
        self.assertEqual(first, engine.action_identity(run_id, definition, step,
                                                       {"value": 1, "target_id": "one"}))
        self.assertNotEqual(first, engine.action_identity(run_id, definition, step,
                                                          {"target_id": "two", "value": 1}))
        newer = definition.model_copy(update={"version": 4})
        self.assertNotEqual(first, engine.action_identity(run_id, newer, step,
                                                          {"target_id": "one", "value": 1}))

    def test_retry_after_and_terminal_poison_work(self) -> None:
        engine = self.engine(attempts=3)
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []

        def limited_read(context, step):
            calls.append(1)
            raise ProviderError(429, "7")

        engine.register_action("fixture.action", limited_read, retry_safe=True)
        sleeps = []
        with patch("workflow.automation.engine.time.sleep", side_effect=sleeps.append):
            self.assertTrue(engine.execute_run(run_id, definition, event))
        self.assertEqual(sleeps, [7.0, 7.0])
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.store.get_run(run_id)["status"], "dead_letter")
        item = self.store.failed_work()[0]
        self.assertEqual((item["failure_category"], item["reason_code"], item["redrive_permitted"]),
                         ("rate_limited", "attempts_exhausted", 1))
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_failures").fetchone()[0], 4)

    def test_proven_read_only_provider_503_retries_once(self) -> None:
        engine = self.engine(attempts=2)
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []

        def read(context, step):
            calls.append(1)
            if len(calls) == 1:
                raise ProviderError(503)
            return {"ok": True}

        engine.register_action("fixture.action", read, retry_safe=True)
        with patch("workflow.automation.engine.time.sleep") as sleeper:
            self.assertTrue(engine.execute_run(run_id, definition, event))
        sleeper.assert_called_once_with(2.0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")
        self.assertEqual(self.store.failure_history(run_id)[0]["category"], "provider_unavailable")

    def test_permanent_auth_and_ambiguous_writes_never_retry(self) -> None:
        for status, expected in ((400, "failed"), (401, "human_action_required"),
                                 (503, "human_action_required")):
            with self.subTest(status=status):
                store = AutomationStore(self.root / f"case-{status}.db")
                engine = AutomationEngine(store, self.workflows)
                if not (self.workflows / "fixture.yaml").exists():
                    self.engine(attempts=3)
                engine.sync_definitions()
                calls = []

                def write(context, step):
                    calls.append(1)
                    raise ProviderError(status)

                engine.register_action("fixture.action", write)
                result = engine.ingest(AutomationEvent(event_type="fixture.event", source="unit"))
                run = store.get_run(result.run_ids[0])
                self.assertEqual(run["status"], expected)
                self.assertEqual(calls, [1])
                item = store.failed_work()[0]
                self.assertEqual(item["human_required"], int(expected == "human_action_required"))

    def test_continue_cannot_downgrade_exhausted_safe_retry(self) -> None:
        engine = self.engine(attempts=2, on_error="continue")
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []

        def unavailable_read(context, step):
            calls.append(1)
            raise ProviderError(503)

        engine.register_action("fixture.action", unavailable_read, retry_safe=True)
        with patch("workflow.automation.engine.time.sleep"):
            self.assertTrue(engine.execute_run(run_id, definition, event))
        self.assertEqual(calls, [1, 1])
        self.assertEqual(self.store.get_run(run_id)["status"], "dead_letter")
        self.assertEqual(self.store.failure_history(run_id)[0]["terminal_state"], "dead_letter")
        self.assertEqual(engine.recover_pending()["executed"], 0)
        self.assertEqual(self.store.get_run(run_id)["status"], "dead_letter")

    def test_continue_cannot_downgrade_permanent_validation_failure(self) -> None:
        engine = self.engine(attempts=3, on_error="continue")
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        calls = []

        def invalid_read(context, step):
            calls.append(1)
            raise ValueError("invalid fixture input")

        engine.register_action("fixture.action", invalid_read, retry_safe=True)
        self.assertTrue(engine.execute_run(run_id, definition, event))
        self.assertEqual(calls, [1])
        self.assertEqual(self.store.get_run(run_id)["status"], "failed")
        self.assertEqual(self.store.failure_history(run_id)[0]["terminal_state"], "failed")

    def test_continue_cannot_downgrade_ambiguous_write_or_auth_failure(self) -> None:
        for status in (401, 503):
            with self.subTest(status=status):
                store = AutomationStore(self.root / f"continue-{status}.db")
                engine = AutomationEngine(store, self.workflows)
                self.engine(attempts=3, on_error="continue")
                engine.sync_definitions()
                calls = []

                def write(context, step):
                    calls.append(1)
                    raise ProviderError(status)

                engine.register_action("fixture.action", write)
                result = engine.ingest(AutomationEvent(event_type="fixture.event", source="unit"))
                self.assertEqual(calls, [1])
                self.assertEqual(store.get_run(result.run_ids[0])["status"], "human_action_required")
                self.assertEqual(store.failure_history(result.run_ids[0])[0]["terminal_state"],
                                 "human_action_required")

    def test_continue_setting_remains_valid_for_successful_multistep_workflow(self) -> None:
        engine = self.engine(on_error="continue")
        path = self.workflows / "fixture.yaml"
        path.write_text(path.read_text() + "  - id: second\n    action: core.noop\n", encoding="utf-8")
        engine.sync_definitions()
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        engine.register_action("fixture.action", lambda context, step: {"ok": True})
        self.assertTrue(engine.execute_run(run_id, definition, event))
        self.assertEqual(self.store.get_run(run_id)["status"], "completed")
        self.assertEqual(len(self.store.get_run(run_id)["steps"]), 2)

    def test_action_marker_precedes_handler_and_provider_id_can_be_recorded(self) -> None:
        engine = self.engine()
        run_id, event = self.queue()
        definition = self.store.queued_envelopes()[0][1]
        observed = []

        def provider(context, step):
            with self.store._connect() as conn:
                row = conn.execute("SELECT status,action_identity FROM automation_run_steps "
                                   "WHERE run_id=?", (run_id,)).fetchone()
            observed.append((row["status"], row["action_identity"],
                             context["execution"]["action_identity"]))
            return {"ok": True, "provider_operation_id": "provider-op-123"}

        engine.register_action("fixture.action", provider)
        self.assertTrue(engine.execute_run(run_id, definition, event))
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], "started")
        self.assertEqual(observed[0][1], observed[0][2])
        self.assertEqual(self.store.get_run(run_id)["steps"][0]["provider_operation_id"],
                         "provider-op-123")

    def test_duplicate_step_ids_are_rejected_before_ingest(self) -> None:
        self.engine()
        path = self.workflows / "fixture.yaml"
        source = path.read_text()
        path.write_text(source + "  - id: operation\n    action: core.noop\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "step IDs must be unique"):
            AutomationEngine(self.store, self.workflows).sync_definitions()

    def test_legacy_schema_migration_is_repeat_safe_and_preserves_rows(self) -> None:
        engine = self.engine()
        run_id, _ = self.queue()
        with self.store._connect() as conn:
            conn.execute("DROP TABLE automation_run_failures")
            conn.execute("CREATE TABLE automation_run_failures(run_id TEXT PRIMARY KEY,category TEXT,"
                         "reason_code TEXT,attempt_id TEXT,recorded_at TEXT)")
            conn.execute("INSERT INTO automation_run_failures VALUES(?,?,?,?,?)",
                         (run_id, "permanent", "old_failure", "old-attempt", "2026-09-27T16:00:00Z"))
            conn.execute("PRAGMA user_version=0")
        migrated = AutomationStore(self.db)
        self.assertEqual(migrated.failed_work(), [])
        with migrated._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_failures_legacy").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_failures").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
        AutomationStore(self.db)
        with migrated._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM automation_run_failures").fetchone()[0], 1)

    def test_schema_transaction_rolls_back_after_mid_migration_conflict(self) -> None:
        db = self.root / "interrupted.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE automation_run_steps(id INTEGER PRIMARY KEY,run_id TEXT,"
                         "step_id TEXT,attempt INTEGER)")
            conn.execute("CREATE TABLE automation_run_failures(run_id TEXT PRIMARY KEY,category TEXT,"
                         "reason_code TEXT,attempt_id TEXT,recorded_at TEXT)")
            conn.execute("CREATE TABLE automation_run_failures_legacy(blocker TEXT)")
        with self.assertRaises(sqlite3.OperationalError):
            AutomationStore(db)
        with sqlite3.connect(db) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(automation_run_steps)")}
            self.assertNotIn("action_identity", columns)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
            conn.execute("DROP TABLE automation_run_failures_legacy")
        self.assertEqual(AutomationStore(db)._connect().execute("PRAGMA user_version").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
