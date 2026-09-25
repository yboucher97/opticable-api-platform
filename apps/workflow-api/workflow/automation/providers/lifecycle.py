from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...customer_lifecycle import normalize_lead
from ...zoho_gateway import ZohoGatewayClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


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
        lead = step.inputs.get("lead")
        if not isinstance(lead, dict):
            raise ValueError("lifecycle.crm_upsert_lead requires with.lead object.")

        existing = _find_existing_lead(client, lead)
        if existing and existing.get("id"):
            record_id = str(existing["id"])
            payload = _lead_payload(lead, create=False)
            response = client.request(
                "zohoapis",
                "PUT",
                f"/crm/v8/Leads/{record_id}",
                body={"data": [payload]},
                reason="Customer lifecycle: update deduplicated CRM lead",
                confirm=True,
            )
            action = "updated"
        else:
            payload = _lead_payload(lead, create=True)
            response = client.request(
                "zohoapis",
                "POST",
                "/crm/v8/Leads",
                body={"data": [payload]},
                reason="Customer lifecycle: create CRM lead from normalized intake",
                confirm=True,
            )
            record_id = _first_record_id(response)
            if not record_id:
                raise RuntimeError("Zoho CRM did not return the created Lead id.")
            action = "created"

        event = context.get("event") or {}
        store.audit(
            category="customer_lifecycle",
            action=f"crm_lead_{action}",
            actor="automation-engine",
            success=True,
            correlation_id=event.get("correlation_id") or event.get("event_id"),
            target=record_id,
            metadata={
                "source": lead.get("source"),
                "inquiry_id": lead.get("inquiry_id"),
                "identity_hash": lead.get("identity_hash"),
            },
        )
        return {"lead_id": record_id, "action": action, "lead": lead}

    def create_followup_task(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        lead_id = str(step.inputs.get("lead_id") or "").strip()
        if not lead_id:
            raise ValueError("lifecycle.crm_create_followup_task requires with.lead_id.")

        lead = step.inputs.get("lead") if isinstance(step.inputs.get("lead"), dict) else {}
        label = (
            " ".join(
                part for part in (str(lead.get("first_name") or "").strip(), str(lead.get("last_name") or "").strip())
                if part
            )
            or str(lead.get("company") or "").strip()
            or lead_id
        )
        due_days = int(step.inputs.get("due_days", 1))
        due_days = max(0, min(due_days, 30))
        due_date = (datetime.now(ZoneInfo("America/Toronto")).date() + timedelta(days=due_days)).isoformat()

        description_parts = ["Automatically created by OptiBrain customer lifecycle."]
        if lead.get("service_type"):
            description_parts.append(f"Service requested: {lead['service_type']}")
        if lead.get("message"):
            description_parts.append(f"Inquiry: {lead['message']}")

        response = client.request(
            "zohoapis",
            "POST",
            "/crm/v8/Tasks",
            body={
                "data": [
                    {
                        "Subject": f"Review new lead: {label}"[:255],
                        "Due_Date": due_date,
                        "Who_Id": lead_id,
                        "$se_module": "Leads",
                        "Description": "\n".join(description_parts),
                    }
                ]
            },
            reason="Customer lifecycle: create next-action task for new or updated lead",
            confirm=True,
        )
        task_id = _first_record_id(response)
        return {"task_id": task_id, "due_date": due_date}

    engine.register_action("lifecycle.normalize_lead", normalize_action)
    engine.register_action("lifecycle.crm_upsert_lead", upsert_lead)
    engine.register_action("lifecycle.crm_create_followup_task", create_followup_task)
