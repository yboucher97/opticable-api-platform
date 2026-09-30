#!/usr/bin/env python3
"""One controlled Lead GET and a projected, local follow-up decision; no writes."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/workflow-api"))

from workflow.config import load_settings
from workflow.zoho_oauth import ZohoOAuthManager
from workflow.zoho_gateway import ZohoGatewayClient
from workflow.automation.providers.crm_leads import FIELDS, phase6_lead_patch, records
from workflow.automation.sales_decision import build_sales_decision


LEAD_ID = "5062683000007880001"


def main() -> None:
    settings = load_settings()
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    response = client.request(
        "zohoapis", "GET", f"/crm/v8/Leads/{LEAD_ID}", query={"fields": FIELDS}
    )
    rows = records(response)
    if len(rows) != 1 or str(rows[0].get("id")) != LEAD_ID:
        raise ValueError("controlled Lead identity mismatch")
    record = rows[0]
    due = datetime.fromisoformat(str(record.get("Next_Followup_At") or "").replace("Z", "+00:00"))
    if due.tzinfo is None:
        raise ValueError("controlled Lead has no aware follow-up deadline")
    projected_at = due.astimezone(timezone.utc) + timedelta(days=1)
    decision = build_sales_decision(record, now=projected_at)
    if not decision.active or decision.followup_at != due.astimezone(timezone.utc).isoformat():
        raise ValueError("overdue follow-up projection failed")
    patch = phase6_lead_patch(record, decision)
    if "Next_Followup_At" in patch:
        raise ValueError("existing follow-up would be rewritten")
    print(json.dumps({
        "scenario": "one_live_controlled_lead_get_projected_one_day_past_due",
        "lead_id": LEAD_ID,
        "source_version": decision.version,
        "projected_at": projected_at.isoformat(),
        "provider_followup_at": due.astimezone(timezone.utc).isoformat(),
        "decision_followup_at": decision.followup_at,
        "priority": decision.priority,
        "next_action": decision.next_action,
        "deadline_rewritten": False,
        "provider_reads": 1,
        "provider_business_writes": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
