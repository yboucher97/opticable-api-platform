#!/usr/bin/env python3
"""Bounded controlled Lead qualification probe; CRM GETs only."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/workflow-api"))

from workflow.config import load_settings
from workflow.zoho_oauth import ZohoOAuthManager
from workflow.zoho_gateway import ZohoGatewayClient
from workflow.automation.phase7_canary import build_canary_plan, hydrate_unique_lead


LEAD_ID = "5062683000007880001"


class ReadOnlyControlledClient:
    def __init__(self, client):
        self.client = client
        self.reads = 0

    def request(self, provider, method, path, **kwargs):
        if (provider != "zohoapis" or method != "GET" or path not in {
            f"/crm/v8/Leads/{LEAD_ID}", "/crm/v8/Leads/search"
        } or self.reads >= 2):
            raise ValueError("probe permits only two controlled CRM reads")
        self.reads += 1
        return self.client.request(provider, method, path, **kwargs)


def main():
    settings = load_settings()
    client = ReadOnlyControlledClient(
        ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    )
    lead, proof = hydrate_unique_lead(client, LEAD_ID)
    plan = build_canary_plan(lead, proof, now=datetime.now(timezone.utc))
    if plan.lead_id != LEAD_ID or client.reads != 2:
        raise ValueError("controlled identity or read bound failed")
    if plan.language != "unknown" or "preferred_language" not in plan.missing_information:
        raise ValueError("controlled missing-language scenario is not present")
    if plan.outbound_eligible:
        raise ValueError("unknown-language plan became outbound eligible")
    print(json.dumps({
        "scenario": "controlled_ai_site_lead_missing_language_qualification",
        "lead_id": LEAD_ID,
        "source_version": plan.source_version,
        "identity_hash": plan.identity_hash,
        "plan_hash": plan.plan_hash,
        "dedupe_status": plan.dedupe_status,
        "language": plan.language,
        "missing_information": plan.missing_information,
        "next_action": plan.next_action,
        "outbound_eligible": plan.outbound_eligible,
        "provider_reads": client.reads,
        "provider_business_writes": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
