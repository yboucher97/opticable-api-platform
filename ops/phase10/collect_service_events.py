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

DB = Path("/var/lib/opticable-workflow-api/output/automation/phase10-service-events.db")


def main():
    settings = load_settings()
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    view = build_customer_lifecycle(client, scope="lab")
    result = reconcile_service_events(view, DB)
    print(f"Phase 10 service events: {result['added']} added, {result['total']} total, "
          f"{result['service_count']} verified Lab Services")


if __name__ == "__main__":
    main()
