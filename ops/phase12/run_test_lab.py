#!/usr/bin/env python3
"""Bounded application runner for registered TEST_ONLY follow-up Task proposals.

No model/Codex/shell execution. This fixed root-only service is required by the
existing CRM Test Lab exact-call firewall; it never writes a real record.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
from time import monotonic
from uuid import uuid4

CODE_ROOT = Path(os.environ.get("OPTIBRAIN_PHASE12_CODE_ROOT") or Path(__file__).resolve().parents[2])
if os.environ.get("OPTIBRAIN_PHASE12_CODE_ROOT") and CODE_ROOT != Path("/opt/opticable-api-platform"):
    raise ValueError("Runner code root is not the pinned production path")
APP = CODE_ROOT / "apps/workflow-api"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(CODE_ROOT / "ops/phase11"))
from workflow.automation.business_autonomy import (Action, BusinessJournal, Policy,
    classify_crm_record, decide, dispatch)
from test_lab_operations import (LAB, BASELINE, STATE, load, owned, provider,
    read, write, listing, save_lab)
from workflow.automation.remote_effects import RemoteEffects
from workflow.automation.mutation_control import bind_task_claim

ROOT = Path("/var/lib/optibrain/phase12")
LOCK = ROOT / "runner.lock"
DB = Path("/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db")
MAX_ACTIONS = 4
MAX_WRITES = 2


def lock(*, expected_uid: int = 0):
    ROOT.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or info.st_nlink != 1:
        os.close(fd); raise ValueError("Unsafe Phase 12 runner lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def fresh(client, lab, baseline, action: Action):
    if action.action_type != "crm.task.create" or action.target_module != "Leads":
        raise ValueError("Scheduled runner accepts only legacy follow-up Task creation")
    row = read(client, "Leads", action.target_id)
    row["ownership"] = classify_crm_record("Leads", row,
        registered_test_ids=set(lab["records"].get("Leads", [])),
        protected_ids=set(baseline["modules"]["Leads"]["ids"]))
    return row


def task_row(action: Action) -> dict:
    payload = action.payload
    if (set(payload) != {"Subject", "Due_Date", "Status", "purpose"}
            or not str(payload["Subject"]).startswith("OPTIBRAIN TEST — PHASE 12 — Follow-up review ")
            or payload["Status"] != "Not Started"
            or payload["purpose"] != "Internal follow-up review; no customer send"):
        raise ValueError("Scheduled Task payload exceeds fixed Test Lab shape")
    return {"Subject": payload["Subject"] + ' [OB-ACTION:' + action.action_id + ']', "Description":
            "OPTIBRAIN TEST — PHASE 12\nInternal follow-up review only; no customer email.\nPayload SHA-256: " + action.payload_hash,
            "What_Id": {"id": action.target_id}, "$se_module": "Leads",
            "Status": "Not Started", "Due_Date": payload["Due_Date"]}


def verified_task(client, state, lab, action: Action, effects=None) -> str | None:
    key = "phase12runner:" + action.action_id
    operation = state["operations"].get(key) or {}
    if operation.get('state')=='verified' and operation.get('id'):
        row=owned(lab,'Tasks',read(client,'Tasks',operation['id']))
        # Legacy acknowledged Tasks have no new marker. They are observation-only.
        if (row.get('Subject')==action.payload['Subject'] and row.get('Status')==action.payload['Status']
                and row.get('Due_Date')==action.payload['Due_Date']
                and str((row.get('What_Id') or {}).get('id') or '')==action.target_id):
            return str(row['id'])
    effects=effects or RemoteEffects.root_store()
    if not effects.get(action,'claim'): return None
    result=effects.get(action,'result')
    rows=([read(client,'Tasks',result['provider_id'])] if result else
          listing(client,'Tasks','id,Subject,Description,Status,Due_Date,What_Id,$se_module'))
    expected = task_row(action)
    found=[r for r in rows if r.get('Subject')==expected['Subject']]
    if len(found)>1: raise ValueError('Ambiguous duplicate provider effects')
    if not found: return None
    row=found[0]
    if (any(row.get(k)!=expected[k] for k in ('Subject','Description','Status','Due_Date'))
            or str((row.get('What_Id') or {}).get('id') or '')!=action.target_id
            or row.get('$se_module')!='Leads'):
        raise ValueError('Provider effect differs from immutable claim')
    protected=set(load(BASELINE)['modules']['Tasks']['ids'])
    if str(row['id']) in protected: raise ValueError('Protected Task cannot be adopted')
    if str(row['id']) not in lab['records'].get('Tasks',[]):
        lab['records'].setdefault('Tasks',[]).append(str(row['id']));save_lab(lab)
    effects.complete(action,str(row['id']))
    return str(row["id"])


def execute_task(client, state, lab, action: Action) -> str:
    effects=RemoteEffects.root_store()
    existing = verified_task(client, state, lab, action, effects)
    if existing: return existing  # Read-only recovery after a lost action-journal ack.
    claim=effects.claim(action)
    if not claim.fresh: raise ValueError('Previously claimed execution is reconciliation-only')
    body={'data':[task_row(action)],'trigger':[],'skip_feature_execution':[{'name':'cadences'}]}
    bind_task_claim(action,client,body,claim)
    row = write(client, state, lab, "phase12runner:" + action.action_id,
                "Tasks", task_row(action))
    effects.complete(action,str(row['id']))
    return str(row["id"])


def run_once(*, now: datetime | None = None) -> dict:
    if os.geteuid() != 0: raise PermissionError("Exact Test Lab firewall requires root")
    began = monotonic(); clock = now or datetime.now(timezone.utc)
    fd = lock()
    if fd is None:
        return {"status": "locked", "writes": 0, "evaluated": 0}
    run_id = uuid4().hex
    counts = {key: 0 for key in ("evaluated", "auto_executed", "approvals", "exceptions",
                                "denials", "reconciliations", "provider_failures", "writes")}
    journal = BusinessJournal(DB)
    started_at = clock.isoformat()
    journal.record_run(run_id, started_at=started_at, status="running", counters=counts)
    status = "success"
    try:
        client = provider(); lab, baseline, state = load(LAB), load(BASELINE), load(STATE)
        # Reconcile prior provider attempts before starting new writes. Never retry an
        # attempt whose exact provider result is still unknown.
        for scheduled, action in journal.unreconciled(limit=MAX_ACTIONS):
            counts["reconciliations"] += 1
            result = verified_task(client, state, lab, action)
            if result:
                current = journal.get(action.action_id)
                if current["state"] == "attempted":
                    journal.transition(action.action_id, from_states=("attempted",), to="reconcile",
                                       detail={"reason": "runner_restart_after_attempt"})
                journal.transition(action.action_id, from_states=("reconcile",), to="succeeded",
                                   provider_id=result, detail={"reconciliation": "exact_provider_readback"})
                journal.mark_scheduled(action.action_id, state="succeeded", decision="RECONCILED", run_id=run_id)
        for scheduled, action in journal.due(now=clock, limit=MAX_ACTIONS):
            counts["evaluated"] += 1
            if counts["writes"] >= MAX_WRITES: break
            row = fresh(client, lab, baseline, action)
            decision = decide(action, row["ownership"], Policy.from_environment())
            if decision.choice == "DEFER" and decision.reason in {
                    "business_auto_write_kill_switch_off", "per_action_auto_flag_off"}:
                # Keep the due proposal pending so turning the switch back on can act.
                journal.mark_scheduled(action.action_id, state="pending", decision=decision.reason, run_id=run_id)
                continue
            before_attempts = (journal.get(action.action_id) or {}).get("attempts", 0)
            result = dispatch(action, ownership=row["ownership"], policy=Policy.from_environment(),
                run_id=run_id, source_trigger=scheduled['source_trigger'],
                journal=journal, fresh=lambda: fresh(client, lab, baseline, action),
                execute=lambda: execute_task(client, state, lab, action),
                reconcile=lambda: verified_task(client, state, lab, action))
            journal.annotate(action.action_id, {"run_id": run_id,
                "source_trigger": scheduled["source_trigger"]})
            final = result["state"]
            scheduled_state = ("succeeded" if final == "succeeded" else
                               "approval_required" if final == "approval_required" else
                               "denied" if final == "denied" else "exception")
            journal.mark_scheduled(action.action_id, state=scheduled_state,
                                   decision=result["decision"], run_id=run_id)
            if final == "succeeded":
                counts["auto_executed"] += 1
            elif final == "approval_required": counts["approvals"] += 1
            elif final == "denied": counts["denials"] += 1
            else: counts["exceptions"] += 1
            counts["writes"] += max(0, result["attempts"] - before_attempts)
            if final == "reconcile": counts["provider_failures"] += 1
    except Exception:
        status = "failed"
        counts["provider_failures"] += 1
        raise
    finally:
        journal.record_run(run_id, started_at=started_at, status=status,
                           counters=counts, duration_ms=int((monotonic()-began)*1000))
        os.close(fd)
    return {"run_id": run_id, "status": status, **counts}


if __name__ == "__main__":
    if sys.argv[1:] != ["--once"]: raise SystemExit("Only --once is accepted")
    print(json.dumps(run_once(), sort_keys=True))
