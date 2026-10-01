"""Central follow-up migration and bounded runner safety tests."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import unittest

from workflow.automation.business_autonomy import Action, BusinessJournal, Policy, decide
from workflow.automation.phase12_followup import propose_legacy_followup
from workflow.automation.providers.lifecycle import register_lifecycle_actions
from workflow.automation.models import WorkflowStep

NOW = datetime.fromisoformat("2026-10-01T17:00:00+00:00")


class Client:
    def __init__(self, row): self.row = row; self.calls = []
    def request(self, service, method, path):
        self.calls.append((service, method, path))
        return {"ok": True, "data": {"data": [self.row]}}


def registry(tmp):
    lab, base = tmp / "lab.json", tmp / "base.json"
    lab.write_text(json.dumps({"records": {"Leads": ["501"]}}))
    base.write_text(json.dumps({"modules": {"Leads": {"ids": ["999"]}}}))
    return lab, base


def lead(identity="501", **changes):
    row = {"id": identity, "Description": "OPTIBRAIN TEST — PHASE 12\nSynthetic",
           "OptiBrain_Test": True, "Modified_Time": "2026-10-01T12:00:00-04:00",
           "Lead_Status": "Attempted to Contact", "Next_Followup_At": "2026-10-01T12:30:00-04:00"}
    row.update(changes)
    return row


class ClosureTests(unittest.TestCase):
    def test_legacy_proposal_is_durable_idempotent_and_protected_denied(self):
        with tempfile.TemporaryDirectory() as root:
            tmp = Path(root); lab, base = registry(tmp)
            journal = BusinessJournal(tmp / "actions.db")
            client = Client(lead())
            one = propose_legacy_followup(client, journal, "501", now=NOW,
                                           lab_path=lab, baseline_path=base)
            two = propose_legacy_followup(client, journal, "501", now=NOW,
                                           lab_path=lab, baseline_path=base)
            assert one == two and one["state"] == "pending"
            scheduled = journal.scheduled(one["action_id"])
            action = Action(**json.loads(scheduled["envelope_json"]))
            assert action.payload["Due_Date"] == "2026-10-01"
            assert len(journal.due(now=NOW)) == 1
            assert all(call[1] == "GET" for call in client.calls)
            protected = Client(lead("999"))
            blocked = propose_legacy_followup(protected, journal, "999", now=NOW,
                                               lab_path=lab, baseline_path=base)
            assert blocked["state"] == "denied"
            assert len(journal.due(now=NOW)) == 1
            with self.assertRaisesRegex(ValueError, "batch exceeds"):
                journal.due(now=NOW, limit=5)
            closed = Client(lead(Lead_Status="Disqualified"))
            assert propose_legacy_followup(closed, journal, "501", now=NOW,
                lab_path=lab, baseline_path=base)["state"] == "no_action"


    def test_runner_lock_replay_kill_switch_and_bounded_write(self):
        path = Path(__file__).resolve().parents[3] / "ops/phase12/run_test_lab.py"
        spec = importlib.util.spec_from_file_location("phase12_run_test_lab_test", path)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as root:
            tmp = Path(root); lab_path, base_path = registry(tmp)
            journal = BusinessJournal(tmp / "actions.db")
            client = Client(lead())
            proposal = propose_legacy_followup(client, journal, "501", now=NOW,
                lab_path=lab_path, baseline_path=base_path)
            state = {"operations": {}}
            fake_lab = {"records": {"Leads": ["501"], "Tasks": []}}
            fake_base = {"modules": {"Leads": {"ids": ["999"]}}}
            written = []
            def get(module, ident):
                if module == "Leads": return lead()
                if module == "Tasks" and ident == "700":
                    return {"id": "700", **written[0]}
                raise ValueError("unexpected read")
            def write(*args, **kwargs):
                written.append(args[5])
                state["operations"][args[3]] = {"state": "verified", "id": "700"}
                fake_lab["records"]["Tasks"].append("700")
                return {"id": "700", **written[0]}
            def owned(module, row): return row
            def load(path):
                return {runner.LAB: fake_lab, runner.BASELINE: fake_base,
                        runner.STATE: state}[path]
            real_lock = runner.lock
            with (patch.object(runner, "ROOT", tmp), patch.object(runner, "LOCK", tmp / "lock"),
                  patch.object(runner, "DB", tmp / "actions.db"),
                  patch.object(runner, "provider", return_value=client),
                  patch.object(runner, "read", side_effect=lambda _c, module, ident: get(module, ident)),
                  patch.object(runner, "write", side_effect=write),
                  patch.object(runner, "owned", side_effect=lambda _lab, module, row: owned(module, row)),
                  patch.object(runner, "load", side_effect=load),
                  patch.object(runner, "lock", side_effect=lambda: real_lock(expected_uid=os.getuid())),
                  patch.object(runner.os, "geteuid", return_value=0)):
                with patch.dict(runner.os.environ, {"OPTIBRAIN_BUSINESS_AUTO_WRITES": "0",
                     "OPTIBRAIN_AUTO_TEST_TASK": "1"}):
                    off = runner.run_once(now=NOW)
                    assert off["writes"] == 0 and journal.scheduled(proposal["action_id"])["state"] == "pending"
                with patch.dict(runner.os.environ, {"OPTIBRAIN_BUSINESS_AUTO_WRITES": "1",
                     "OPTIBRAIN_AUTO_TEST_TASK": "1"}):
                    one = runner.run_once(now=NOW)
                    two = runner.run_once(now=NOW+timedelta(minutes=1))
                    assert one["writes"] == 1 and one["auto_executed"] == 1
                    assert two["writes"] == 0 and len(written) == 1
                    assert journal.scheduled(proposal["action_id"])["state"] == "succeeded"
                    fd = runner.lock()
                    assert fd is not None
                    try: assert runner.run_once(now=NOW)["status"] == "locked"
                    finally: runner.os.close(fd)


    def test_bulk_and_books_hard_denial(self):
        for kind in ("email.bulk.send", "books.write"):
            candidate = Action(kind, "Leads", "501", f"phase12:deny:{kind.replace('.','_')}", {})
            assert decide(candidate, "TEST_ONLY", Policy(automatic_mutations=True)).choice == "DENY"


    def test_legacy_workflow_handler_can_only_propose_not_write(self):
        class Engine:
            actions = {}
            def register_action(self, name, handler): self.actions[name] = handler
        with tempfile.TemporaryDirectory() as root:
            engine = Engine(); client = Client(lead())
            register_lifecycle_actions(engine, client, type("Store", (), {"db_path": Path(root)/"automation.db"})())
            handler = engine.actions["lifecycle.crm_create_followup_task"]
            step = WorkflowStep.model_validate({"id": "follow", "action": "lifecycle.crm_create_followup_task",
                                                "with": {"lead_id": "501"}})
            with patch("workflow.automation.providers.lifecycle.propose_legacy_followup",
                       return_value={"state": "pending", "action_id": "fixture"}) as proposer:
                assert handler({}, step)["state"] == "pending"
                assert proposer.call_count == 1
            bad = WorkflowStep.model_validate({"id": "follow", "action": "lifecycle.crm_create_followup_task",
                                               "with": {"lead_id": "501", "subject": "unsafe"}})
            with self.assertRaisesRegex(ValueError, "only exact lead_id"):
                handler({}, bad)
            assert client.calls == []
