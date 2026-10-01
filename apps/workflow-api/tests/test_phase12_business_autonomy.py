"""Phase 12 policy, journal, exact approval, and operator-boundary tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workflow.automation.business_autonomy import (
    Action, BusinessJournal, Policy, classify_crm_record, decide, dispatch, dispatch_approved,
    local_time, reconcile_ambiguous, render_dashboard,
)
from workflow.operator_phase7_api import install_phase7_canary_routes

NOW = datetime.fromisoformat("2026-10-01T15:00:00+00:00")


def action(kind="crm.task.update", *, target="501", key="phase12:task:one",
           status="In Progress", version="2026-10-01T10:00:00-04:00"):
    return Action(kind, "Tasks", target, key, {"Status": status},
                  expected_version=version, expected_state={"Status": "Not Started"})


class PolicyTests(unittest.TestCase):
    def test_tiers_flags_kill_switch_and_ownership(self):
        p = Policy(automatic_mutations=True, auto_test_task=True, auto_test_project=True,
                   auto_test_internal=True)
        self.assertEqual(decide(action("crm.read"), "PROTECTED", Policy()).choice, "AUTO_EXECUTE")
        self.assertEqual(decide(action(), "TEST_ONLY", p).choice, "AUTO_EXECUTE")
        self.assertEqual(decide(action(), "PROTECTED", p).reason, "protected_baseline_read_only")
        self.assertEqual(decide(action(), "REAL", p).choice, "DENY")
        self.assertEqual(decide(action(), "TEST_ONLY", Policy()).choice, "DEFER")
        self.assertEqual(decide(action(), "TEST_ONLY", Policy(automatic_mutations=True)).reason,
                         "per_action_auto_flag_off")
        uncertain = Action("crm.task.update", "Tasks", "501", "phase12:task:uncertain",
                           {"Status": "In Progress"}, confidence="LOW")
        self.assertEqual(decide(uncertain, "TEST_ONLY", p).choice, "DEFER")
        send = Action("email.send", "Leads", "501", "phase12:send:one",
                      {"recipient": "operator@example.invalid"})
        self.assertEqual(decide(send, "TEST_ONLY", p).choice, "APPROVAL_REQUIRED")
        self.assertEqual(decide(send, "PROTECTED", p).choice, "DENY")
        forbidden = Action("books.write", "Books", "501", "phase12:books:one", {"Amount": 1})
        self.assertEqual(decide(forbidden, "TEST_ONLY", p).choice, "DENY")

    def test_provider_marker_required_and_montreal_dst(self):
        row = {"id": "501", "Subject": "OPTIBRAIN TEST — PHASE 12 task"}
        self.assertEqual(classify_crm_record("Tasks", row, registered_test_ids={"501"}, protected_ids={"999"}), "TEST_ONLY")
        self.assertEqual(classify_crm_record("Tasks", row, registered_test_ids={"501"}, protected_ids={"501"}), "PROTECTED")
        row["Subject"] = "ordinary task"
        self.assertEqual(classify_crm_record("Tasks", row, registered_test_ids={"501"}, protected_ids=set()), "UNKNOWN")
        self.assertIn("EDT", local_time("2026-11-01T05:30:00+00:00"))
        self.assertIn("EST", local_time("2026-11-01T06:30:00+00:00"))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            local_time("2026-11-01T01:30:00")


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = BusinessJournal(Path(self.tmp.name) / "actions.db")
        self.policy = Policy(automatic_mutations=True, auto_test_task=True)

    def test_exact_one_use_approval_payload_target_and_expiry(self):
        proposed = Action("email.send", "Leads", "501", "phase12:send:approval",
                          {"recipient": "controlled@example.invalid", "body": "test only"})
        d = decide(proposed, "TEST_ONLY", self.policy)
        self.journal.prepare(proposed, d)
        with self.assertRaisesRegex(ValueError, "human approval"):
            self.journal.issue(proposed, actor="automation", expires_at=(NOW+timedelta(minutes=30)).isoformat(), now=NOW)
        current = datetime.now(timezone.utc)
        one = self.journal.issue(proposed, actor="human:operator",
                                 expires_at=(current+timedelta(minutes=30)).isoformat(), now=current)
        changed = Action("email.send", "Leads", "501", proposed.request_key,
                         {"recipient": "controlled@example.invalid", "body": "changed"})
        different_target = Action("email.send", "Leads", "502", proposed.request_key, proposed.payload)
        for candidate in (changed, different_target):
            with self.assertRaisesRegex(ValueError, "binding changed"):
                self.journal.claim_approval(one["approval_id"], candidate, actor="human:operator", now=NOW)
        with self.assertRaisesRegex(ValueError, "binding changed"):
            self.journal.claim_approval(one["approval_id"], proposed, actor="human:other", now=NOW)
        approved = dispatch_approved(proposed, approval_id=one["approval_id"], actor="human:operator",
            journal=self.journal, policy=Policy(automatic_mutations=True, approved_test_send=True), fresh=lambda: {"id": "501", "ownership": "TEST_ONLY"},
            execute=lambda: "fixture-only", reconcile=lambda: "fixture-only")
        self.assertEqual(approved["state"], "succeeded")
        with self.assertRaisesRegex(ValueError, "consumed"):
            self.journal.claim_approval(one["approval_id"], proposed, actor="human:operator", now=NOW)
        with self.assertRaisesRegex(ValueError, "consumed"):
            self.journal.claim_approval(one["approval_id"], proposed, actor="human:operator", now=NOW)
        later = Action("email.send", "Leads", "501", "phase12:send:expiry", proposed.payload)
        self.journal.prepare(later, decide(later, "TEST_ONLY", self.policy))
        expiring = self.journal.issue(later, actor="human:operator",
            expires_at=(NOW+timedelta(minutes=5)).isoformat(), now=NOW)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.journal.claim_approval(expiring["approval_id"], later, actor="human:operator",
                                        now=NOW+timedelta(minutes=6))

    def test_approved_action_revalidates_state_and_never_sends_stale(self):
        p = Action("email.send", "Leads", "501", "phase12:approved:stale",
                   {"recipient": "controlled@example.invalid", "body_hash": "abc"},
                   expected_version="2026-10-01T10:00:00-04:00", expected_state={"reply": False})
        self.journal.prepare(p, decide(p, "TEST_ONLY", self.policy))
        issued = self.journal.issue(p, actor="human:operator",
                                    expires_at=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat())
        result = dispatch_approved(p, approval_id=issued["approval_id"], actor="human:operator",
            journal=self.journal, policy=Policy(automatic_mutations=True, approved_test_send=True), fresh=lambda: {"id": "501", "ownership": "TEST_ONLY", "Modified_Time": p.expected_version,
                                                 "reply": True},
            execute=lambda: self.fail("stale customer send"), reconcile=lambda: None)
        self.assertEqual(result["state"], "stale")
        with self.assertRaisesRegex(ValueError, "Exact approved"):
            dispatch_approved(p, approval_id=issued["approval_id"], actor="human:operator",
                journal=self.journal, policy=Policy(automatic_mutations=True, approved_test_send=True), fresh=lambda: {}, execute=lambda: "x", reconcile=lambda: "x")

    def test_dispatch_replay_stale_and_ambiguous_readback(self):
        p = action()
        calls = []
        fresh = lambda: {"id": "501", "ownership": "TEST_ONLY", "Modified_Time": p.expected_version,
                         "Status": "Not Started"}
        def execute(): calls.append("write"); return "501"
        one = dispatch(p, ownership="TEST_ONLY", policy=self.policy, journal=self.journal,
                       fresh=fresh, execute=execute, reconcile=lambda: "501")
        self.assertEqual(one["state"], "succeeded")
        self.assertEqual(dispatch(p, ownership="TEST_ONLY", policy=self.policy, journal=self.journal,
                         fresh=fresh, execute=execute, reconcile=lambda: "501")["state"], "succeeded")
        self.assertEqual(calls, ["write"])
        changed = action(key="phase12:task:changed")
        stale = dispatch(changed, ownership="TEST_ONLY", policy=self.policy, journal=self.journal,
            fresh=lambda: {**fresh(), "Status": "Completed"}, execute=lambda: calls.append("bad"),
            reconcile=lambda: None)
        self.assertEqual(stale["state"], "stale")
        ambiguous = action(key="phase12:task:ambiguous")
        def timed_out():
            calls.append("committed then lost response")
            raise TimeoutError("response lost")
        row = dispatch(ambiguous, ownership="TEST_ONLY", policy=self.policy, journal=self.journal,
                       fresh=fresh, execute=timed_out, reconcile=lambda: None)
        self.assertEqual(row["state"], "reconcile")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(dispatch(ambiguous, ownership="TEST_ONLY", policy=self.policy,
                         journal=self.journal, fresh=fresh, execute=execute,
                         reconcile=lambda: None)["state"], "reconcile")
        self.assertEqual(reconcile_ambiguous(ambiguous, self.journal, lambda: "501")["state"], "succeeded")
        self.assertEqual(calls, ["write", "committed then lost response"])
        with self.assertRaisesRegex(ValueError, "changed action"):
            self.journal.prepare(action(key="phase12:task:one", status="Completed"), decide(p, "TEST_ONLY", self.policy))

    def test_deny_is_journaled_without_transport_and_dashboard_escapes(self):
        p = action(key="phase12:protected:task")
        row = dispatch(p, ownership="PROTECTED", policy=self.policy, journal=self.journal,
                       fresh=lambda: self.fail("provider reached"), execute=lambda: self.fail("provider reached"),
                       reconcile=lambda: self.fail("provider reached"))
        self.assertEqual(row["state"], "denied")
        view = self.journal.view()
        self.assertEqual(view["summary"]["denied"], 1)
        self.assertIn("protected_baseline_read_only", render_dashboard(view, section="exceptions"))


class OperatorRoutes(unittest.TestCase):
    def test_read_views_and_approval_issuance_are_authenticated(self):
        class Verifier:
            def verify(self, token):
                if token != "test-operator": raise ValueError("missing")
                return SimpleNamespace(subject="operator", actor="human:operator")
        app = FastAPI()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "automation.db"
            install_phase7_canary_routes(app, verifier=Verifier(), client=object(),
                store=SimpleNamespace(db_path=path), account_id="1",
                from_address="operator@example.invalid", allowed_origin="https://example.invalid",
                clock=lambda: NOW)
            http = TestClient(app)
            for name in ("autonomy", "approvals", "exceptions"):
                route = f"/v1/operator/phase12/{name}"
                self.assertEqual(http.get(route).status_code, 401)
                answer = http.get(route, headers={"Cf-Access-Jwt-Assertion": "test-operator"})
                self.assertEqual(answer.status_code, 200)
                self.assertEqual(answer.headers["cache-control"], "private, no-store, max-age=0")
            journal = BusinessJournal(path.with_name("phase12-autonomy.db"))
            proposal = Action("email.send", "Leads", "501", "phase12:send:route",
                              {"recipient": "controlled@example.invalid"})
            journal.prepare(proposal, decide(proposal, "TEST_ONLY", Policy()))
            body = {"action_id": proposal.action_id, "payload_hash": proposal.payload_hash,
                    "expires_in_minutes": 15}
            self.assertEqual(http.post("/v1/operator/phase12/approvals", json=body).status_code, 401)
            self.assertEqual(http.post("/v1/operator/phase12/approvals", json=body,
                headers={"Cf-Access-Jwt-Assertion": "test-operator"}).status_code, 403)
            response = http.post("/v1/operator/phase12/approvals", json=body,
                headers={"Cf-Access-Jwt-Assertion": "test-operator",
                         "Content-Type": "application/json", "Origin": "https://example.invalid"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["state"], "issued")


if __name__ == "__main__": unittest.main()
