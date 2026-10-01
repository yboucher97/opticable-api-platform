from __future__ import annotations

from ..crm_write_boundary import blocked_legacy

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...customer_lifecycle import normalize_lead
from ...zoho_gateway import ZohoGatewayClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore
from ..business_autonomy import BusinessJournal
from ..phase12_followup import propose_legacy_followup
from pathlib import Path


def _records(response: dict[str, Any]) -> list[dict[str, Any]]:
    outer = response.get("data")
    if not isinstance(outer, dict):
        return []
    records = outer.get("data")
    return records if isinstance(records, list) else []


def _first_record_id(response: dict[str, Any]) -> str | None:
    records = _records(response)
    if not records:
        return None
    item = records[0]
    if not isinstance(item, dict):
        return None
    details = item.get("details")
    if isinstance(details, dict) and details.get("id"):
        return str(details["id"])
    if item.get("id"):
        return str(item["id"])
    return None


def _lead_payload(lead: dict[str, Any], *, create: bool) -> dict[str, Any]:
    address = lead.get("address") if isinstance(lead.get("address"), dict) else {}
    attr = lead.get("attribution") if isinstance(lead.get("attribution"), dict) else {}

    payload: dict[str, Any] = {
        "Last_Name": lead.get("last_name"),
        "Normalized_Email": lead.get("email"),
        "Normalized_Phone": lead.get("phone") or lead.get("mobile"),
        "Ingestion_Source": lead.get("source"),
        "Source_Record_ID": lead.get("source_record_id"),
        "Inquiry_ID": lead.get("inquiry_id"),
        "Last_Source": attr.get("source") or lead.get("source"),
        "Last_Medium": attr.get("medium"),
        "Last_Campaign": attr.get("campaign"),
        "Last_Campaign_ID": attr.get("campaign_id"),
        "Last_Term": attr.get("term"),
        "Last_Content": attr.get("content"),
        "Last_Landing_URL": attr.get("landing_url"),
        "Last_Referrer": attr.get("referrer"),
        "Last_Site": attr.get("site"),
        "Last_Touch_Time": lead.get("occurred_at"),
        "Google_GCLID": attr.get("gclid"),
        "Google_GBRAID": attr.get("gbraid"),
        "Google_WBRAID": attr.get("wbraid"),
        "Meta_FBCLID": attr.get("fbclid"),
        "Meta_FBP": attr.get("fbp"),
        "Meta_FBC": attr.get("fbc"),
        "Visitor_ID": attr.get("visitor_id"),
    }

    if create:
        payload.update(
            {
                "First_Name": lead.get("first_name"),
                "Company": lead.get("company"),
                "Email": lead.get("email"),
                "Phone": lead.get("phone"),
                "Mobile": lead.get("mobile"),
                "Street": address.get("street"),
                "City": address.get("city"),
                "State": address.get("state_province"),
                "Zip_Code": address.get("postal_code"),
                "Country": address.get("country"),
                "Description": lead.get("message"),
                "First_Source": attr.get("source") or lead.get("source"),
                "First_Medium": attr.get("medium"),
                "First_Campaign": attr.get("campaign"),
                "First_Campaign_ID": attr.get("campaign_id"),
                "First_Term": attr.get("term"),
                "First_Content": attr.get("content"),
                "First_Landing_URL": attr.get("landing_url"),
                "First_Referrer": attr.get("referrer"),
                "First_Site": attr.get("site"),
                "First_Touch_Time": lead.get("occurred_at"),
            }
        )
    else:
        # Update current communication coordinates but do not overwrite CRM
        # address/company/description fields from every subsequent touch.
        payload.update(
            {
                "Email": lead.get("email"),
                "Phone": lead.get("phone"),
                "Mobile": lead.get("mobile"),
            }
        )

    return {key: value for key, value in payload.items() if value not in (None, "")}


def _find_existing_lead(client: ZohoGatewayClient, lead: dict[str, Any]) -> dict[str, Any] | None:
    inquiry_id = lead.get("inquiry_id")
    if inquiry_id:
        result = client.request(
            "zohoapis",
            "GET",
            "/crm/v8/Leads/search",
            query={"criteria": f"(Inquiry_ID:equals:{inquiry_id})", "per_page": 2},
        )
        records = _records(result)
        if records:
            return records[0]

    source_record_id = lead.get("source_record_id")
    source = lead.get("source")
    if source_record_id and source:
        result = client.request(
            "zohoapis",
            "GET",
            "/crm/v8/Leads/search",
            query={
                "criteria": (
                    f"((Ingestion_Source:equals:{source})and"
                    f"(Source_Record_ID:equals:{source_record_id}))"
                ),
                "per_page": 2,
            },
        )
        records = _records(result)
        if records:
            return records[0]

    email = lead.get("email")
    if email:
        result = client.request(
            "zohoapis",
            "GET",
            "/crm/v8/Leads/search",
            query={"email": email, "converted": "both", "per_page": 10},
        )
        records = _records(result)
        if records:
            normalized = email.lower()
            exact = [
                item
                for item in records
                if str(item.get("Email") or item.get("Normalized_Email") or "").lower() == normalized
            ]
            return (exact or records)[0]

    phone = lead.get("phone") or lead.get("mobile")
    if phone:
        result = client.request(
            "zohoapis",
            "GET",
            "/crm/v8/Leads/search",
            query={"phone": phone, "converted": "both", "per_page": 10},
        )
        records = _records(result)
        if records:
            return records[0]

    return None


def register_lifecycle_actions(
    engine: AutomationEngine,
    client: ZohoGatewayClient,
    store: AutomationStore,
) -> None:
    def normalize_action(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        payload = step.inputs.get("lead")
        if not isinstance(payload, dict):
            raise ValueError("lifecycle.normalize_lead requires with.lead object.")
        return {"lead": normalize_lead(payload)}

    def upsert_lead(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        blocked_legacy()

    def create_followup_task(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        if set(step.inputs) != {"lead_id"}:
            raise ValueError("Follow-up Task proposal requires only exact lead_id")
        # This legacy action is now proposal-only. The bounded Phase 12 runner
        # is the sole normal path to the provider write after central policy.
        journal = BusinessJournal(Path(store.db_path).with_name("phase12-autonomy.db"))
        return propose_legacy_followup(client, journal, str(step.inputs["lead_id"]))

    engine.register_action("lifecycle.normalize_lead", normalize_action)
    engine.register_action("lifecycle.crm_upsert_lead", upsert_lead)
    engine.register_action("lifecycle.crm_create_followup_task", create_followup_task)
