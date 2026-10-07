from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from workflow.automation.engine import AutomationEngine
from workflow.automation.models import AutomationEvent
from workflow.automation.providers.windsor import register_windsor_actions
from workflow.automation.store import AutomationStore
from workflow.config import WindsorSettings
from workflow.windsor_api import WindsorApiClient, WindsorApiError


class FakeWindsor:
    def read(self, connector, *, fields, params=None):
        return {"ok": True, "status": 200, "data": {"connector": connector, "fields": fields}}

    def list_actions(self, connector):
        return {"ok": True, "status": 200, "data": [{"id": "pause_campaign"}]}

    def execute_action(self, connector, *, account, action, params=None):
        return {"ok": True, "status": 200, "data": {"action": action, "account": account}}


class WindsorProviderTests(unittest.TestCase):
    def _audit_fixture(self,store,account='acct'):
        from datetime import datetime,timezone
        from workflow.automation.action_evidence import ActionEvidence,envelope
        now=datetime.now(timezone.utc);j=ActionEvidence(store.db_path);aid='windsor-audit-fixture-001'
        plan=envelope(aid,'WINDSOR_PAUSE',{'type':'AD_ACCOUNT','identity':account},now,
            provider='WINDSOR',mutation=True,before_state={'campaign_id':'1','status':'ENABLED'},
            proposed_state={'connector':'google_ads','account':account,'action':'pause_campaign','params':{'campaign_id':'1'}},
            rollback_capability='REVERSIBLE_WITH_LIMITATIONS',rollback_target={'campaign_id':'1','status':'ENABLED'},
            rollback_procedure='Owner restores exact previous campaign state after native provider review',
            authority_class='EXPLICIT_TEST_FIXTURE',readback_supported=False,
            unknowns=['Generic Windsor documented action result has no independent native configuration readback in this adapter; reconcile natively'])
        j.plan(plan,now);j.start(aid,now,authority_check=lambda:None)

    def _real_write(self, *, response: httpx.Response | None = None,
                    error: Exception | None = None) -> tuple[dict, list[dict], int]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = AutomationStore(root / "automation.db")
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "write.yaml").write_text("""
id: test.windsor.write
name: Windsor write confirmation
trigger:
  event_types: [test.windsor.write]
steps:
  - id: pause
    action: windsor.execute_action
    with:
      connector: google_ads
      account: acct
      action_id: pause_campaign
      audit_action_id: windsor-audit-fixture-001
      reason: fixture
      params: {campaign_id: '1'}
    on_error: continue
    retry:
      max_attempts: 5
""".strip() + "\n", encoding="utf-8")
            self._audit_fixture(store)
            engine = AutomationEngine(store, workflows)
            client = WindsorApiClient(WindsorSettings(
                base_url="https://example.invalid", api_key="fixture", timeout_seconds=30))
            register_windsor_actions(engine, client, store)
            engine.sync_definitions()
            with patch("workflow.windsor_api.httpx.post", return_value=response,
                       side_effect=error) as post:
                outcome = engine.ingest(AutomationEvent(event_type="test.windsor.write", source="unit-test"))
            run_id = outcome.run_ids[0]
            return store.get_run(run_id), store.failure_history(run_id), post.call_count

    def test_real_write_requires_documented_json_result(self):
        request = httpx.Request("POST", "https://example.invalid/google_ads/actions")
        run, failures, calls = self._real_write(response=httpx.Response(
            200, json={"result": "Campaign paused successfully."}, request=request))
        self.assertEqual((run["status"], calls, failures), ("completed", 1, []))

    def test_unconfirmable_write_responses_never_complete_or_retry(self):
        request = httpx.Request("POST", "https://example.invalid/google_ads/actions")
        cases = {
            "html": httpx.Response(200, text="<html>upstream error</html>",
                                   headers={"Content-Type": "text/html"}, request=request),
            "wrong_media_type": httpx.Response(
                200, text='{"result":"paused"}',
                headers={"Content-Type": "text/html"}, request=request),
            "malformed_json": httpx.Response(200, text='{"result":',
                                             headers={"Content-Type": "application/json"}, request=request),
            "empty": httpx.Response(200, content=b"", request=request),
            "wrong_structure": httpx.Response(200, json=["unexpected"], request=request),
            "unsupported_result_shape": httpx.Response(200, json={"result": {"id": "1"}}, request=request),
            "error_envelope": httpx.Response(200, json={"error": "provider denied action"}, request=request),
            "error_envelope_with_result": httpx.Response(
                200, json={"result": "Campaign paused", "error": {"code": "incomplete"}}, request=request),
            "errors_envelope_with_result": httpx.Response(
                200, json={"result": "Campaign paused", "errors": []}, request=request),
            "failed_envelope": httpx.Response(
                200, json={"result": "paused", "success": False}, request=request),
            "partial_result": httpx.Response(200, json={"result": "PARTIAL_SUCCESS"}, request=request),
            "partial_flag": httpx.Response(
                200, json={"result": "Campaign created", "partial": True}, request=request),
            "partial_status": httpx.Response(
                200, json={"result": "Campaign created", "status": "partial"}, request=request),
            "partial_success_status": httpx.Response(
                200, json={"result": "Campaign created", "status": "partial_success"}, request=request),
            "partial_success_status_upper": httpx.Response(
                200, json={"result": "Campaign created", "status": "PARTIAL_SUCCESS"}, request=request),
            "partial_status_mixed_case": httpx.Response(
                200, json={"result": "Campaign created", "status": "PaRtIaL"}, request=request),
            "partially_completed_status": httpx.Response(
                200, json={"result": "Campaign created", "status": "partially_completed"}, request=request),
            "incomplete_status": httpx.Response(
                200, json={"result": "Campaign created", "status": "incomplete"}, request=request),
            "explicit_failure_status": httpx.Response(
                200, json={"result": "Campaign created", "status": "FAILURE"}, request=request),
            "warning_envelope": httpx.Response(
                200, json={"result": "Campaign created", "warnings": ["one campaign was skipped"]},
                request=request),
            "blank_result": httpx.Response(200, json={"result": " "}, request=request),
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                run, failures, calls = self._real_write(response=response)
                self.assertEqual((run["status"], calls), ("human_action_required", 1))
                self.assertEqual(failures[0]["category"], "ambiguous_external")
                self.assertEqual(failures[0]["reason_code"], "external_result_ambiguous")
                self.assertTrue(failures[0]["human_required"])
                self.assertNotIn("upstream error", str(failures))
                self.assertNotIn("provider denied action", str(failures))
                self.assertNotIn("Campaign created", str(failures))

    def test_explicit_partial_indicators_are_rejected_before_write_completion(self):
        variants = (
            {"result": "Campaign created", "partial": True},
            {"result": "Campaign created", "status": "partial"},
            {"result": "Campaign created", "status": "partial_success"},
            {"result": "Campaign created", "status": "PARTIAL-SUCCESS"},
            {"result": "Campaign created", "status": "PARTIAL_SUCCESS"},
            {"result": "Campaign created", "status": "PaRtIaL"},
            {"result": "Campaign created", "status": "partially_completed"},
            {"result": "Campaign created", "status": "incomplete"},
        )
        for body in variants:
            with self.subTest(body=body):
                response = httpx.Response(
                    200, json=body,
                    request=httpx.Request("POST", "https://example.invalid/google_ads/actions"))
                run, failures, calls = self._real_write(response=response)
                self.assertEqual(calls, 1)
                self.assertEqual(run["status"], "human_action_required")
                self.assertEqual(failures[0]["category"], "ambiguous_external")
                self.assertNotIn("Campaign created", str(failures))

    def test_direct_write_confirmation_partial_boundary(self):
        for body in (
            {"result": "Campaign created", "partial": True},
            {"result": "Campaign created", "status": "partial"},
            {"result": "Campaign created", "status": "partial_success"},
            {"result": "Campaign created", "status": "PARTIAL-SUCCESS"},
            {"result": "Campaign created", "status": "PaRtIaL"},
        ):
            with self.subTest(body=body):
                self.assertFalse(WindsorApiClient._confirmed_write(body))
        self.assertTrue(WindsorApiClient._confirmed_write(
            {"result": "Campaign created successfully."}))

    def test_documented_success_shape_remains_confirmed(self):
        request = httpx.Request("POST", "https://example.invalid/google_ads/actions")
        run, failures, calls = self._real_write(response=httpx.Response(
            200, json={"result": "Campaign paused successfully."}, request=request))
        self.assertEqual((run["status"], calls, failures), ("completed", 1, []))

    def test_write_transport_uncertainty_stays_single_attempt(self):
        request = httpx.Request("POST", "https://example.invalid/google_ads/actions")
        for error in (httpx.ReadTimeout("after possible send", request=request),
                      httpx.ConnectError("send uncertain", request=request)):
            with self.subTest(error=type(error).__name__):
                run, failures, calls = self._real_write(error=error)
                self.assertEqual((run["status"], calls), ("human_action_required", 1))
                self.assertTrue(failures[0]["human_required"])

    def test_read_retries_rate_limit_but_write_remains_untrusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = AutomationStore(root / "automation.db")
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "w.yaml").write_text("""
id: test.windsor.read
name: Windsor read retry
version: 1
enabled: true
trigger:
  event_types: [test.windsor.read]
steps:
  - id: read
    action: windsor.read
    with:
      connector: google_ads
      fields: [campaign]
    retry:
      max_attempts: 2
      backoff_seconds: 2
""".strip() + "\n", encoding="utf-8")

            class LimitedWindsor(FakeWindsor):
                calls = 0

                def read(self, connector, *, fields, params=None):
                    self.calls += 1
                    if self.calls == 1:
                        response = httpx.Response(429, headers={"Retry-After": "5"},
                                                  request=httpx.Request("GET", "https://example.invalid/read"))
                        raise WindsorApiError("rate limited", response=response)
                    return super().read(connector, fields=fields, params=params)

            client = LimitedWindsor()
            engine = AutomationEngine(store, workflows)
            register_windsor_actions(engine, client, store)
            engine.sync_definitions()
            with patch("workflow.automation.engine.time.sleep") as sleeper:
                response = engine.ingest(AutomationEvent(event_type="test.windsor.read", source="unit-test"))
            self.assertEqual(client.calls, 2)
            sleeper.assert_called_once_with(5.0)
            self.assertEqual(store.get_run(response.run_ids[0])["status"], "completed")
            self.assertEqual(store.failure_history(response.run_ids[0])[0]["category"], "rate_limited")

    def test_blocks_cost_increasing_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=AutomationStore(root/"automation.db"); workflows=root/"workflows"; workflows.mkdir()
            (workflows/"w.yaml").write_text("""
id: test.windsor
name: Windsor test
version: 1
enabled: true
trigger:
  event_types: [test.windsor]
steps:
  - id: spend
    action: windsor.execute_action
    with:
      connector: google_ads
      account: "123"
      action_id: set_campaign_budget
      reason: test
      params: {budget: 100}
""".strip()+"\n", encoding="utf-8")
            engine=AutomationEngine(store, workflows); register_windsor_actions(engine, FakeWindsor(), store); engine.sync_definitions()
            response=engine.ingest(AutomationEvent(event_type="test.windsor", source="unit-test"))
            run=store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "failed")

    def test_allows_non_cost_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=AutomationStore(root/"automation.db"); workflows=root/"workflows"; workflows.mkdir()
            (workflows/"w.yaml").write_text("""
id: test.windsor
name: Windsor test
version: 1
enabled: true
trigger:
  event_types: [test.windsor]
steps:
  - id: pause
    action: windsor.execute_action
    with:
      connector: google_ads
      account: "123"
      action_id: pause_campaign
      audit_action_id: windsor-audit-fixture-001
      reason: policy test
      params: {campaign_id: "1"}
""".strip()+"\n", encoding="utf-8")
            self._audit_fixture(store,account='123')
            engine=AutomationEngine(store, workflows); register_windsor_actions(engine, FakeWindsor(), store); engine.sync_definitions()
            response=engine.ingest(AutomationEvent(event_type="test.windsor", source="unit-test"))
            run=store.get_run(response.run_ids[0])
            self.assertEqual(run["status"], "completed")


if __name__ == "__main__":
    unittest.main()
