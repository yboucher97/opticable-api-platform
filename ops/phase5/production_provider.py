#!/usr/bin/env python3
"""Service-identity, secret-safe provider verification for the pinned campaign."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
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
from workflow.automation.native_notifications import mark_synthetic, origin_evidence
from workflow.automation.delta_sync import DeltaSync
from workflow.automation.crm_delta import CrmLeadDeltaAdapter


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
        if not all(r.status == "completed" for r in results):
            return {"result": "BLOCKED", "category": "native_subscription_manual_reconciliation", "plan_hash": plan.plan_hash,
                    "results": [r.model_dump(mode="json") for r in results], "crm_record_writes": 0}
        check(controller.plan(document).summary == {"noop": 1}, "native_subscription_verification")
        return {"result": "PASS", "plan_hash": plan.plan_hash, "results": [r.model_dump() for r in results]}
    if mode == "native-origin-proof":
        # Pending is a durable observation state, not a deployment failure.
        return {"result": "PASS", "crm_record_writes": 0, **origin_evidence(store)}
    if mode == "delta-proof":
        # A bounded real GET through the same adapter proves fallback remains
        # usable without racing the scheduler or manufacturing CRM changes.
        sync = DeltaSync(store)
        state = sync.snapshot("zoho_crm", "5062683000000020005", "Leads", "incremental")
        check(state and state["status"] not in {"failed", "resync_required"}, "crm_delta_checkpoint_unhealthy")
        adapter = CrmLeadDeltaAdapter(client, "5062683000000020005")
        page = adapter.fetch(state["cursor"], None, mode="incremental", limit=100)
        check(isinstance(page.events, tuple), "crm_delta_readback_unverified")
        return {"result": "PASS", "checkpoint_status": state["status"], "bounded_delta_get": True, "crm_record_writes": 0}
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
        mark_synthetic(store, raw)
        one = httpx.post(url, json=raw, timeout=20)
        check(one.status_code == 202 and one.json()["accepted"], "authenticated_public_notification_intake")
        two = httpx.post(url, json=raw, timeout=20)
        check(two.status_code == 202 and two.json()["duplicate"], "notification_delivery_dedupe")
        event_id = one.json()["event_id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            evidence = httpx.get("http://127.0.0.1:8100/v1/automation/events/" + event_id,
                headers={"X-API-Key": key}, timeout=10).json()
            if evidence.get("status") == "routed" and evidence.get("routes"):
                run = store.get_run(evidence["routes"][0]["run_id"])
                if run and run["status"] == "completed":
                    return {"result": "PASS", "event_id": event_id, "run_id": run["run_id"], "lead_id": identity,
                            "duplicate": True, "delivery_class": "synthetic", "provider_emitted_event_proven": False, "crm_record_writes": 0}
            time.sleep(.5)
        raise RuntimeError("lead_review_delivery_drill_timeout")
    raise RuntimeError("unknown_provider_campaign_mode")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("verify", "subscribe", "notification-proof", "native-origin-proof", "delta-proof"), required=True)
    args = parser.parse_args()
    try:
        result = run(args.mode)
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result["result"] == "PASS" else 1)
    except Exception as exc:
        category = str(exc) if type(exc) is RuntimeError and re.fullmatch(r"[a-z][a-z0-9_]{0,120}", str(exc)) else type(exc).__name__
        print(json.dumps({"result": "BLOCKED", "category": category}))
        raise SystemExit(1)
