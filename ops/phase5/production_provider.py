#!/usr/bin/env python3
"""Service-identity, secret-safe provider verification for the pinned campaign."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/workflow-api"))
import httpx
from workflow.config import load_settings
from workflow.zoho_oauth import ZohoOAuthManager
from workflow.zoho_gateway import ZohoGatewayClient
from workflow.automation.desired_state import DesiredStateController, DesiredStateRegistry
from workflow.automation.reconcilers.zoho_crm import ZohoCrmFieldReconciler
from workflow.automation.reconcilers.zoho_metadata import register_crm_metadata
from workflow.automation.reconcilers.zoho_notification import ZohoCrmNotificationReconciler
from workflow.automation.store import AutomationStore
from workflow.automation.events import EventLedger
from workflow.automation.desired_journal import ApplyConflict


def check(value, category):
    if not value: raise RuntimeError(category)


def run(mode):
    settings = load_settings()
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    registry = DesiredStateRegistry()
    registry.register("zoho_crm", "field", ZohoCrmFieldReconciler(client))
    register_crm_metadata(registry, client)
    registry.register("zoho_crm", "notification", ZohoCrmNotificationReconciler(client))
    store = AutomationStore(settings.automation.db_path)
    controller = DesiredStateController(registry, store)
    directory = ROOT / "apps/workflow-api/config/automation/desired-state"
    if mode == "verify":
        results = []
        for name in ("opticable-crm-governance.json", "opticable-lead-additions.json"):
            document = controller.load(directory / name)
            plan = controller.plan(document)
            check(plan.summary == {"noop": len(document.resources)}, "live_governance_drift")
            results.append({"document": document.name, "document_hash": plan.document_hash, "plan_hash": plan.plan_hash, "summary": plan.summary})
        return {"result": "PASS", "plans": results, "books_mutations": 0, "crm_metadata_mutations": 0}
    document = controller.load(directory / "zoho-crm-notification.template.json")
    if mode == "subscribe":
        deadline = time.monotonic() + 45
        while True:
            plan = controller.plan(document)
            check(plan.summary in ({"create": 1}, {"noop": 1}), "native_subscription_collision")
            try:
                results = controller.apply(document, plan, low_risk_additive_only=True, actor="authorized-phase5-production")
                break
            except ApplyConflict:
                # Lock refusal precedes intent/network. Waiting here is not a
                # retry of an ambiguous provider mutation.
                check(time.monotonic() < deadline, "native_subscription_prewrite_lock_timeout")
                time.sleep(.5)
        check(all(r.status == "completed" for r in results), "native_subscription_manual_reconciliation")
        check(controller.plan(document).summary == {"noop": 1}, "native_subscription_verification")
        return {"result": "PASS", "plan_hash": plan.plan_hash, "results": [r.model_dump() for r in results]}
    if mode == "native-origin-proof":
        # The known synthetic drill is excluded. The channel credential is
        # private to this service and Zoho, so another authenticated callback
        # is provider-delivery evidence within the native token trust model.
        excluded = os.environ.get("OPTIBRAIN_PHASE5_DELIVERY_DRILL_EVENT_ID", "")
        check(bool(excluded), "synthetic_drill_identity_required")
        ledger = EventLedger(store)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            with store._connect() as conn:
                rows = conn.execute("SELECT event_id,envelope_json FROM automation_event_ledger WHERE source_account=? ORDER BY received_at DESC LIMIT 200",
                                    ("5062683000000020005",)).fetchall()
            for row in rows:
                event = json.loads(row["envelope_json"])
                if row["event_id"] == excluded or event["source"] != "zoho.crm" or event.get("provider_evidence", {}).get("channel_id") != "5062683202609281":
                    continue
                if event["event_type"] not in {"zoho.crm.Leads.insert", "zoho.crm.Leads.update"}:
                    continue
                evidence = ledger.inspect(row["event_id"])
                if evidence["status"] == "routed" and evidence.get("routes") and all(
                        (store.get_run(route["run_id"]) or {}).get("status") == "completed" for route in evidence["routes"]):
                    return {"result": "PASS", "event_id": row["event_id"], "provider_emitted_event_proven": True,
                            "authentication": "native_token; no independent payload signature claim", "crm_record_writes": 0}
            time.sleep(.5)
        raise RuntimeError("native_lead_callback_not_yet_observed_no_test_record_created")
    if mode == "notification-proof":
        # Read a real lead; submit an authenticated notification hint. This is a
        # delivery-path drill, not proof that Zoho emitted a real customer event.
        response = client.request("zohoapis", "GET", "/crm/v8/Leads", query={"fields": "id,Modified_Time", "per_page": 1})
        rows = (response.get("data") or {}).get("data")
        check(response.get("ok") is True and isinstance(rows, list) and len(rows) == 1, "lead_read_for_delivery_drill")
        identity = str(rows[0]["id"])
        key = os.getenv(settings.api.api_key_env, "")
        check(bool(key.strip()) and os.getenv("OPTIBRAIN_CRM_LEAD_WRITES", "") != "phase5-lead-v1", "proof_requires_observe_policy")
        raw = {"token": os.environ["OPTIBRAIN_PHASE5_CRM_CHANNEL_CREDENTIAL"], "channel_id": "5062683202609281",
               "server_time": int(time.time() * 1000), "module": "Leads", "operation": "update", "ids": [identity]}
        url = "https://optibrain.opticable.ca/v1/automation/webhooks/phase5-crm-leads"
        one = httpx.post(url, json=raw, timeout=20)
        check(one.status_code == 200 and one.json()["accepted"], "authenticated_public_notification_intake")
        two = httpx.post(url, json=raw, timeout=20)
        check(two.status_code == 200 and two.json()["duplicate"], "notification_delivery_dedupe")
        event_id = one.json()["event_id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            evidence = httpx.get("http://127.0.0.1:8100/v1/automation/events/" + event_id,
                headers={"X-API-Key": key}, timeout=10).json()
            if evidence.get("status") == "routed" and evidence.get("routes"):
                run = store.get_run(evidence["routes"][0]["run_id"])
                if run and run["status"] == "completed":
                    return {"result": "PASS", "event_id": event_id, "run_id": run["run_id"], "lead_id": identity,
                            "duplicate": True, "provider_emitted_event_proven": False, "crm_record_writes": 0}
            time.sleep(.5)
        raise RuntimeError("lead_review_delivery_drill_timeout")
    raise RuntimeError("unknown_provider_campaign_mode")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("verify", "subscribe", "notification-proof", "native-origin-proof"), required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.mode), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"result": "BLOCKED", "category": str(exc) if type(exc) is RuntimeError else type(exc).__name__}))
        raise SystemExit(1)
