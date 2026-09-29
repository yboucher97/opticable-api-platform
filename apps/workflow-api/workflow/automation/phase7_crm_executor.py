"""Unregistered one-record CRM canary executor with no automatic retry."""
from __future__ import annotations

from datetime import datetime, timezone
import os

from .crm_write_boundary import CANARY_POLICY, reviewed_canary_call
from .event_schema import digest
from .phase7_canary import build_canary_plan, hydrate_unique_lead
from .phase7_crm_approval import CrmCanaryApprovalLedger
from .providers.crm_leads import FIELDS, _field_subset, records


def execute_approved_canary(client, store, approval_id: str, *, now: datetime | None = None) -> dict:
    """Attempt one exact approved Lead update after fresh read-only revalidation.

    This is deliberately not registered in startup, workflows or an HTTP route.
    A future authenticated operator route must control invocation and the exact
    canary flag. Unknown provider results are terminal manual, not retried.
    """
    if (os.environ.get("OPTIBRAIN_CRM_CANARY") != CANARY_POLICY
            or os.environ.get("OPTIBRAIN_CRM_CANARY_APPROVAL_ID") != approval_id):
        raise ValueError("CRM canary policy is disabled")
    ledger = CrmCanaryApprovalLedger(store)
    state = ledger.inspect(approval_id)
    if state is None or state["state"] != "issued":
        raise ValueError("CRM canary approval unavailable")
    approval = state["approval"]
    clock = now or datetime.now(timezone.utc)
    lead, evidence = hydrate_unique_lead(client, approval.lead_id)
    plan = build_canary_plan(lead, evidence, now=clock)
    if (plan.plan_hash != approval.plan_hash or plan.crm_patch_hash != approval.patch_hash
            or plan.source_version != approval.source_version or not plan.crm_patch):
        raise ValueError("CRM canary source or patch changed before consumption")
    # The journal marker precedes OAuth and any provider write. There is no
    # automatic retry after this point, even if the request never left the VPS.
    claimed = ledger.claim(approval_id, lead_id=plan.lead_id,
                          source_version=plan.source_version,
                          plan_hash=plan.plan_hash, patch_hash=plan.crm_patch_hash,
                          now=clock)
    path = f"/crm/v8/Leads/{plan.lead_id}"
    headers = {"If-Unmodified-Since": lead["Modified_Time"]}
    body = {"data": [{"id": plan.lead_id, **plan.crm_patch}], "trigger": [],
            "skip_feature_execution": [{"name": "cadences"}]}
    try:
        with reviewed_canary_call(client, "PUT", path, body, headers, claimed, ledger, now=clock):
            response = client.request("zohoapis", "PUT", path, body=body, headers=headers,
                                      reason="Phase 7 single approved CRM canary", confirm=True)
        rows = (response.get("data") or {}).get("data")
        if (response.get("ok") is not True or response.get("status") not in {200, 201, 202}
                or not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "success"):
            raise ValueError("CRM canary acknowledgement unconfirmed")
        operation_id = str((rows[0].get("details") or {}).get("id") or "")
        if operation_id != plan.lead_id:
            raise ValueError("CRM canary operation identity unconfirmed")
        readback = client.request("zohoapis", "GET", path, query={"fields": FIELDS})
        current = records(readback)
        verified = _field_subset(current[0], plan.crm_patch) if len(current) == 1 else {}
        if (len(current) != 1 or str(current[0].get("id") or "") != plan.lead_id
                or verified != plan.crm_patch):
            raise ValueError("CRM canary exact readback mismatch")
        ledger.finish(claimed, operation_id=operation_id,
                      verified_patch_hash=digest(verified))
        return {"state": "consumed", "approval_id": approval_id,
                "operation_id": operation_id, "patch_hash": plan.crm_patch_hash}
    except Exception:
        state = ledger.inspect(claimed.approval_id)
        if state is not None and state["state"] in {"consuming", "dispatching"}:
            ledger.finish(claimed, reason="provider_unconfirmed")
        raise ValueError("CRM canary outcome requires human reconciliation") from None
