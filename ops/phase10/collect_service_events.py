#!/usr/bin/env python3
"""Scheduled read-only Zoho Lab projection → local idempotent lifecycle events."""
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))

from workflow.config import load_settings
from workflow.zoho_oauth import ZohoOAuthManager
from workflow.zoho_gateway import ZohoGatewayClient
from workflow.automation.customer_lifecycle import build_customer_lifecycle
from workflow.automation.service_events import reconcile_service_events
from workflow.automation.read_inventory_cache import ChangedInventory
from workflow.automation.job_runtime import job_lock
from workflow.automation.provider_usage import ProviderUsage
import json

DB = Path("/var/lib/opticable-workflow-api/output/automation/phase10-service-events.db")


def main():
    with job_lock(DB.with_suffix('.lock')) as held:
        if not held:
            print(json.dumps({'status':'locked'}));return
        with ProviderUsage(DB,'phase10-service-events',runs_per_day=24,soft_budget=6) as usage:
            settings = load_settings()
            client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
            snapshots=ChangedInventory(client,DB)
            view = build_customer_lifecycle(snapshots, scope="lab")
            result = reconcile_service_events(view, DB)
            snapshots.commit()
        print(json.dumps({'service_events':result,'display_inventory':snapshots.stats,'provider_usage':usage.summary},sort_keys=True))



if __name__ == "__main__":
    main()
