#!/usr/bin/env python3
"""Phase 5 V2 restore/startup/crash/dedupe drill. Never migrates a live DB."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/workflow-api"))
from workflow.automation.store import AutomationStore
from workflow.automation.events import EventLedger

spec = importlib.util.spec_from_file_location("phase5_inherited_drill", ROOT / "ops/phase4/isolated_drill.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def ready(url, process):
    import httpx
    end = time.monotonic() + 30
    while time.monotonic() < end:
        base.check(process.poll() is None, "isolated_process_early_exit")
        try:
            response = httpx.get(url + "/health", timeout=2)
            if response.status_code == 200:
                base.check(response.json()["version"] == "1.10.0", "isolated_api_version")
                return response.json()
        except httpx.TransportError:
            pass
        time.sleep(.2)
    raise RuntimeError("isolated_readiness_timeout")


def run(source, workspace):
    metadata = source.lstat()
    base.check(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1, "source_database_type")
    source = source.resolve()
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.check(not source.is_relative_to(workspace.resolve()), "source_inside_drill")
    original = base.inventory(source)
    base.check(original["version"] == 2, "phase5_requires_v2")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as conn:
        base.check(not conn.execute("SELECT 1 FROM automation_runs WHERE status<>'completed' LIMIT 1").fetchone(), "unresolved_restored_work")
    pristine, candidate = workspace / "pristine-v2.db", workspace / "candidate-v2.db"
    base.snapshot(source, pristine); base.snapshot(pristine, candidate)
    store = AutomationStore(candidate)
    base.check(base.inventory(candidate) == original, "schema_or_legacy_evidence_changed")
    base.check(EventLedger(store).health()["backlog"] == 0, "restored_event_backlog")
    base.wait_ready = ready
    api = base.api_drill(workspace, candidate)
    backup, restored = workspace / "post-api-v2-backup.db", workspace / "restored-v2.db"
    base.snapshot(candidate, backup); base.snapshot(backup, restored)
    base.check(base.inventory(restored) == base.inventory(candidate), "post_api_restore_mismatch")
    AutomationStore(restored)
    base.check(base.inventory(source) == original, "source_evidence_changed")
    result = {"result": "PASS", "source_version": 2, "candidate_version": 2, "migration_performed": False,
              "source_unchanged": True, "legacy_evidence_preserved": True, "backup_restore": "PASS",
              **api, **base.ambiguity_drill(workspace)}
    (workspace / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.source_db, args.workspace), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"result": "FAIL", "category": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}))
        raise SystemExit(1)


if __name__ == "__main__": main()
