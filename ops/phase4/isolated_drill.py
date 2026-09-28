#!/usr/bin/env python3
"""Migration, restart, backup and recovery drills; never opens a live DB writable."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "apps/workflow-api"
sys.path.insert(0, str(APP))

import httpx
from workflow.automation.engine import AutomationEngine
from workflow.automation.events import EventLedger
from workflow.automation.models import AutomationEvent, WorkflowDefinition
from workflow.automation.store import AutomationStore


def check(condition: bool, category: str) -> None:
    if not condition:
        raise RuntimeError(category)


def snapshot(source: Path, destination: Path) -> None:
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    destination.chmod(0o600)


def inventory(path: Path) -> dict:
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        check(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "sqlite_integrity")
        check(not conn.execute("PRAGMA foreign_key_check").fetchall(), "sqlite_foreign_keys")
        counts = {}
        hashes = {}
        for name in ("automation_events", "automation_workflows", "automation_runs", "automation_run_steps",
                     "automation_run_claims", "automation_run_failures", "automation_audit"):
            value = hashlib.sha256()
            counts[name] = 0
            for row in conn.execute(f"SELECT * FROM {name} ORDER BY rowid"):
                value.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
                counts[name] += 1
            hashes[name] = value.hexdigest()
        return {"version": conn.execute("PRAGMA user_version").fetchone()[0], "counts": counts, "hashes": hashes}


def smoke_policy(conn: sqlite3.Connection) -> dict:
    root_type, child_type = "system.automation.smoke_test", "system.automation.smoke_test.completed"
    found, unsafe = False, False
    for (raw,) in conn.execute("SELECT definition_json FROM automation_workflows WHERE enabled=1"):
        definition = WorkflowDefinition.model_validate(json.loads(raw))
        matches = [kind for kind, source in ((root_type, "internal"), (child_type, "automation-engine"))
                   if (kind in definition.trigger.event_types or "*" in definition.trigger.event_types)
                   and (not definition.trigger.sources or source in definition.trigger.sources)]
        if not matches:
            continue
        expected = (definition.id == "platform.smoke-test" and matches == [root_type]
                    and [step.action for step in definition.steps] == ["core.set", "event.emit"]
                    and definition.steps[1].inputs.get("event_type") == child_type
                    and definition.steps[1].inputs.get("source") == "automation-engine")
        found |= expected
        unsafe |= not expected
    return {"safe": found and not unsafe, "reason": "safe_internal_smoke" if found and not unsafe else "unsafe_smoke_routing"}


def wait_ready(url: str, process: subprocess.Popen) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("isolated_api_exited_before_ready")
        try:
            response = httpx.get(url + "/health", timeout=2)
            if response.status_code == 200:
                check(response.json()["version"] == "1.9.0", "unexpected_api_version")
                return response.json()
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError("isolated_api_readiness_timeout")


def prepare_smoke(workspace: Path, database: Path) -> Path:
    check(database.resolve().parent == workspace.resolve() and database.name == "candidate-v2.db"
          and not database.is_symlink(), "isolated_smoke_database_scope")
    definitions = workspace / "safe-workflows"
    definitions.mkdir(mode=0o700)
    shutil.copyfile(APP / "config/automation/workflows/platform-smoke-test.yaml",
                    definitions / "platform-smoke-test.yaml")
    # Only the disposable migrated copy is changed, AFTER legacy-row validation.
    # Restored custom workflows must never dispatch a real provider action.
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE automation_workflows SET enabled=0")
    return definitions


def health_alerts_safe(payload: dict, allowed_alert_codes=()) -> bool:
    """Accept only explicitly reviewed warning codes in isolated drills.

    Production/default behavior remains strict because the default allowlist
    is empty. Critical alerts are never accepted.
    """
    if not isinstance(payload, dict):
        return False
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return False

    allowed = set(allowed_alert_codes)

    for alert in alerts:
        if (
            not isinstance(alert, dict)
            or not isinstance(alert.get("code"), str)
            or alert.get("code") not in allowed
            or alert.get("severity") != "warning"
        ):
            return False

    expected_status = "warning" if alerts else "ok"
    return payload.get("status") == expected_status


def api_drill(
    workspace: Path,
    database: Path,
    *,
    allowed_alert_codes=(),
) -> dict:
    definitions = prepare_smoke(workspace, database)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    key = "isolated-drill-" + uuid4().hex
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "SITE_WORKFLOW_OUTPUT_ROOT": str(workspace / "api-output"), "OPTICABLE_AUTOMATION_DB_PATH": str(database),
           "SITE_WORKFLOW_API_KEY": key, "OPTICABLE_AUTOMATION_ENABLED": "true",
           "OPTICABLE_AUTOMATION_WORKFLOWS_DIR": str(definitions),
           "OPTIBRAIN_WEBHOOK_CONFIG": str(workspace / "no-webhooks.yaml"),
           "OPTIBRAIN_SYNC_CONFIG": str(workspace / "no-sync-jobs.yaml")}
    event = {"event_type": "system.automation.smoke_test", "source": "internal",
             "idempotency_key": "phase4-isolated-smoke-" + uuid4().hex, "payload": {"drill": True}}
    headers = {"X-API-Key": key}
    first = None
    for iteration in range(2):
        with (workspace / f"api-{iteration}.log").open("wb") as output:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "workflow.api:app", "--host", "127.0.0.1",
                                        "--port", str(port)], cwd=APP, env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                wait_ready(url, process)
                check(httpx.get(url + "/v1/automation/event-health", timeout=5).status_code == 401, "missing_auth_accepted")
                response = httpx.post(url + "/v1/automation/events", json=event, headers=headers, timeout=10)
                check(response.status_code == 200, "smoke_http_status")
                payload = response.json()
                if iteration == 0:
                    check(payload["accepted"] and len(payload["run_ids"]) == 1, "smoke_acceptance")
                    first = payload
                    run = httpx.get(url + "/v1/automation/runs/" + payload["run_ids"][0], headers=headers, timeout=5).json()
                    check(run["status"] == "completed", "smoke_not_completed")
                    check([s["action"] for s in run["steps"]] == ["core.set", "event.emit"], "unsafe_smoke_actions")
                else:
                    check(payload["duplicate"] and payload["event_id"] == first["event_id"], "restart_dedupe")
                health = httpx.get(url + "/v1/automation/execution-health", headers=headers, timeout=5).json()
                check(health["recovery_worker"]["healthy"], "worker_unhealthy")
                check(health["queued"] == 0 and health["expired_leases"] == 0, "queue_not_clear")
                event_health = httpx.get(url + "/v1/automation/event-health", headers=headers, timeout=5).json()
                check(event_health["backlog"] == 0, "event_backlog")
                alerts = httpx.get(
                    url + "/v1/automation/health-alerts",
                    headers=headers,
                    timeout=5,
                ).json()
                check(
                    health_alerts_safe(
                        alerts,
                        allowed_alert_codes,
                    ),
                    "health_alerts",
                )
            finally:
                # First shutdown is a crash drill, second is graceful. Both are
                # disposable processes listening only on a temporary local port.
                if iteration == 0: process.kill()
                else: process.terminate()
                process.wait(timeout=15)
    return {"api_startup": "PASS", "api_restart": "PASS", "worker_restart": "PASS", "safe_smoke": "PASS",
            "dedupe_after_restart": "PASS", "event_id": first["event_id"], "run_id": first["run_ids"][0], "temporary_port": port}


def ambiguity_drill(workspace: Path) -> dict:
    store = AutomationStore(workspace / "ambiguous.db")
    engine = AutomationEngine(store, workspace / "definitions")
    store.upsert_workflow(WorkflowDefinition.model_validate({"id": "ambiguous.fixture", "name": "Ambiguity fixture",
        "trigger": {"event_types": ["ambiguous.fixture"]}, "steps": [{"id": "external", "action": "fixture.external"}]}))
    calls = []
    def external(context, step):
        calls.append(1)
        raise TimeoutError("fixture ambiguous external result")
    engine.register_action("fixture.external", external)
    event = AutomationEvent(event_type="ambiguous.fixture", source="fixture")
    response = engine.ingest(event)
    check(store.get_run(response.run_ids[0])["status"] == "human_action_required", "ambiguity_not_fenced")
    engine.recover_pending()
    try:
        EventLedger(store).replay(event.event_id, request_key="ambiguous-drill-replay", actor="drill", reason="Verify replay protection")
    except ValueError:
        pass
    else:
        raise RuntimeError("ambiguous_replay_allowed")
    check(len(calls) == 1, "duplicate_external_dispatch")
    return {"ambiguous_external_attempts": 1, "ambiguous_replay_denied": "PASS"}


def run(source: Path, workspace: Path) -> dict:
    source = source.resolve()
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    check(not str(source).startswith(str(workspace) + "/"), "source_inside_output")
    check(source.is_file(), "source_database_missing")
    original = inventory(source)
    check(original["version"] == 1, "drill_requires_v1_source")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as conn:
        check(not conn.execute("SELECT 1 FROM automation_runs WHERE status<>'completed' LIMIT 1").fetchone(),
              "restored_unresolved_work_refuses_api_launch")
    pristine = workspace / "pristine-v1.db"
    migrated = workspace / "candidate-v2.db"
    snapshot(source, pristine); snapshot(pristine, migrated)
    store = AutomationStore(migrated)
    with store._connect() as conn:
        check(conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal", "wal_not_enabled")
    after = inventory(migrated)
    check(after["version"] == 2, "wrong_migrated_version")
    check(original["counts"] == after["counts"] and original["hashes"] == after["hashes"], "migration_changed_legacy_rows")
    check(store.list_workflows() is not None and store.recent_runs(100) is not None, "legacy_inspection_failed")
    check(EventLedger(store).health()["backlog"] == 0, "legacy_events_rerouted")
    rollback = workspace / "rollback-v1.db"
    snapshot(pristine, rollback)
    check(inventory(rollback) == original, "rollback_snapshot_mismatch")
    api_result = api_drill(workspace, migrated)
    post_backup = workspace / "post-api-v2-backup.db"
    snapshot(migrated, post_backup)
    restored = workspace / "restored-v2.db"
    snapshot(post_backup, restored)
    check(inventory(restored) == inventory(migrated), "v2_backup_restore_mismatch")
    AutomationStore(restored)
    check(inventory(source) == original, "source_database_changed")
    result = {"result": "PASS", "source_version": 1, "migrated_version": 2, "legacy_row_counts": after["counts"],
              "migration": "PASS", "migration_legacy_row_hashes": "PASS", "integrity": "PASS", "wal": "PASS",
              "rollback_snapshot": "PASS", "post_migration_backup_restore": "PASS", "source_unchanged": "PASS",
              "isolated_smoke_policy": "only safe internal definition; restored workflows disabled in disposable copy",
              **api_result, **ambiguity_drill(workspace)}
    (workspace / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.source_db, args.workspace), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"result": "FAIL", "category": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
