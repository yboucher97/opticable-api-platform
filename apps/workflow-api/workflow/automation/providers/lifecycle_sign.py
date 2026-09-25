from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ...zoho_gateway import ZohoGatewayClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


_TEMPLATE_MAP = {
    "general_terms": {
        "template_id": "325018000000115001",
        "template_name": "01-conditions-generales",
        "crm_contract_type": None,
    },
    "installation": {
        "template_id": "325018000000115116",
        "template_name": "02-contrat-installation",
        "crm_contract_type": "Installation",
    },
}


def _provider_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _crm_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _provider_payload(response)
    records = payload.get("data")
    return records if isinstance(records, list) else []


def _get_crm_record(client: ZohoGatewayClient, module: str, record_id: str) -> dict[str, Any] | None:
    response = client.request(
        "zohoapis",
        "GET",
        f"/crm/v8/{module}/{record_id}",
    )
    records = _crm_records(response)
    return records[0] if records else None


def _signed_at(request_data: dict[str, Any]) -> str:
    millis = request_data.get("sign_submitted_time") or request_data.get("action_time")
    if millis is not None:
        try:
            return datetime.fromtimestamp(float(millis) / 1000.0, timezone.utc).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError, OSError):
            pass
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def register_lifecycle_sign_actions(
    engine: AutomationEngine,
    client: ZohoGatewayClient,
    store: AutomationStore,
) -> None:
    def send_contract(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        contract = step.inputs.get("contract")
        if not isinstance(contract, dict):
            raise ValueError("lifecycle.sign_send_contract requires with.contract object.")

        contract_type = str(contract.get("contract_type") or "").strip()
        template_config = _TEMPLATE_MAP.get(contract_type)
        if template_config is None:
            raise ValueError("Unsupported contract_type. Only approved Opticable Sign templates may be used.")

        recipient_name = str(contract.get("recipient_name") or "").strip()
        recipient_email = str(contract.get("recipient_email") or "").strip().lower()
        if not recipient_name or not recipient_email or "@" not in recipient_email:
            raise ValueError("Contract recipient_name and a valid recipient_email are required.")

        service_id = str(contract.get("service_id") or "").strip() or None
        deal_id = str(contract.get("deal_id") or "").strip() or None
        account_id = str(contract.get("account_id") or "").strip() or None
        contact_id = str(contract.get("contact_id") or "").strip() or None

        if contract_type == "installation" and not service_id:
            raise ValueError("Installation contracts require service_id for idempotent CRM linkage.")
        if contract_type == "general_terms" and not account_id:
            raise ValueError("General-terms contracts require account_id for CRM linkage.")

        # For installation contracts, an existing Sign request on the Service is
        # authoritative and prevents accidental duplicate envelopes.
        if service_id:
            current_service = _get_crm_record(client, "Services", service_id)
            existing_request_id = str((current_service or {}).get("Sign_Request_ID") or "").strip()
            if existing_request_id:
                return {
                    "sent": False,
                    "already_exists": True,
                    "request_id": existing_request_id,
                    "template_id": template_config["template_id"],
                }

        template_id = template_config["template_id"]
        detail_response = client.request("sign", "GET", f"/templates/{template_id}")
        template = _provider_payload(detail_response).get("templates")
        if not isinstance(template, dict):
            raise RuntimeError("Zoho Sign template details were not returned.")

        actions: list[dict[str, Any]] = []
        for original in template.get("actions") or []:
            if not isinstance(original, dict):
                continue
            action = {
                "action_id": original.get("action_id"),
                "action_type": original.get("action_type"),
                "signing_order": original.get("signing_order"),
                "role": original.get("role"),
                "verify_recipient": bool(original.get("verify_recipient", False)),
                "private_notes": str(original.get("private_notes") or ""),
            }
            if str(original.get("action_type") or "").upper() == "SIGN" and not original.get("recipient_email"):
                action["recipient_name"] = recipient_name
                action["recipient_email"] = recipient_email
            else:
                action["recipient_name"] = original.get("recipient_name")
                action["recipient_email"] = original.get("recipient_email")
            actions.append({key: value for key, value in action.items() if value is not None})

        if not any(
            str(action.get("action_type") or "").upper() == "SIGN"
            and str(action.get("recipient_email") or "").lower() == recipient_email
            for action in actions
        ):
            raise RuntimeError("Approved Sign template does not expose a signer action that can be assigned.")

        field_data = {
            "field_text_data": contract.get("field_text_data") or {},
            "field_date_data": contract.get("field_date_data") or {},
            "field_boolean_data": contract.get("field_boolean_data") or {},
        }
        request_name = str(
            contract.get("request_name")
            or f"{template_config['template_name']} - {recipient_name}"
        )[:255]

        data = {
            "templates": {
                "actions": actions,
                "field_data": field_data,
                "request_name": request_name,
            }
        }
        response = client.request(
            "sign",
            "POST",
            f"/templates/{template_id}/createdocument",
            body={"data": json.dumps(data, ensure_ascii=False), "is_quicksend": "true"},
            content_type="application/x-www-form-urlencoded",
            reason=f"Customer lifecycle: send approved {contract_type} Sign template",
            confirm=True,
        )
        payload = _provider_payload(response)
        request_data = payload.get("requests")
        if not isinstance(request_data, dict) or not request_data.get("request_id"):
            raise RuntimeError("Zoho Sign did not return a request_id after sending.")
        request_id = str(request_data["request_id"])

        if service_id:
            update: dict[str, Any] = {
                "Sign_Request_ID": request_id,
                "Service_Stage": "Contract Sent",
            }
            if template_config.get("crm_contract_type"):
                update["Contract_Type"] = template_config["crm_contract_type"]
            client.request(
                "zohoapis",
                "PUT",
                f"/crm/v8/Services/{service_id}",
                body={"data": [update]},
                reason="Customer lifecycle: link sent Zoho Sign contract to CRM Service",
                confirm=True,
            )

        if deal_id:
            client.request(
                "zohoapis",
                "PUT",
                f"/crm/v8/Deals/{deal_id}",
                body={"data": [{"Stage": "Contracts In Progress"}]},
                reason="Customer lifecycle: advance Deal after contract send",
                confirm=True,
            )

        event = context.get("event") or {}
        store.audit(
            category="customer_lifecycle",
            action="contract_sent",
            actor="automation-engine",
            success=True,
            correlation_id=event.get("correlation_id") or event.get("event_id"),
            target=request_id,
            metadata={
                "contract_type": contract_type,
                "template_id": template_id,
                "service_id": service_id,
                "deal_id": deal_id,
                "account_id": account_id,
            },
        )
        return {
            "sent": True,
            "request_id": request_id,
            "request_status": request_data.get("request_status"),
            "template_id": template_id,
            "template_name": template_config["template_name"],
        }

    def sync_contract_status(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        status_request = step.inputs.get("status")
        if not isinstance(status_request, dict):
            raise ValueError("lifecycle.sign_sync_status requires with.status object.")

        request_id = str(status_request.get("request_id") or "").strip()
        contract_type = str(status_request.get("contract_type") or "").strip()
        if not request_id or contract_type not in _TEMPLATE_MAP:
            raise ValueError("Valid request_id and approved contract_type are required.")

        response = client.request("sign", "GET", f"/requests/{request_id}")
        request_data = _provider_payload(response).get("requests")
        if not isinstance(request_data, dict):
            raise RuntimeError("Zoho Sign request details were not returned.")

        request_status = str(request_data.get("request_status") or "").lower()
        completed = request_status == "completed"
        service_id = str(status_request.get("service_id") or "").strip() or None
        deal_id = str(status_request.get("deal_id") or "").strip() or None
        account_id = str(status_request.get("account_id") or "").strip() or None
        contact_id = str(status_request.get("contact_id") or "").strip() or None
        signed_at = _signed_at(request_data) if completed else None

        if completed and contract_type == "installation":
            if service_id:
                client.request(
                    "zohoapis",
                    "PUT",
                    f"/crm/v8/Services/{service_id}",
                    body={
                        "data": [
                            {
                                "Sign_Request_ID": request_id,
                                "Service_Stage": "Contract Signed",
                                "Service_Contract_Signed_Date": signed_at,
                            }
                        ]
                    },
                    reason="Customer lifecycle: record completed installation contract",
                    confirm=True,
                )
            if deal_id:
                client.request(
                    "zohoapis",
                    "PUT",
                    f"/crm/v8/Deals/{deal_id}",
                    body={"data": [{"Stage": "Contracts Signed"}]},
                    reason="Customer lifecycle: advance Deal after completed contract",
                    confirm=True,
                )

        if completed and contract_type == "general_terms" and account_id:
            account_update: dict[str, Any] = {"General_Terms_Signed": signed_at}
            if contact_id:
                account_update["General_Terms_Signer"] = {"id": contact_id}
            client.request(
                "zohoapis",
                "PUT",
                f"/crm/v8/Accounts/{account_id}",
                body={"data": [account_update]},
                reason="Customer lifecycle: record signed general terms on Account",
                confirm=True,
            )

        event = context.get("event") or {}
        store.audit(
            category="customer_lifecycle",
            action="contract_status_synced",
            actor="automation-engine",
            success=True,
            correlation_id=event.get("correlation_id") or event.get("event_id"),
            target=request_id,
            metadata={
                "contract_type": contract_type,
                "request_status": request_status,
                "completed": completed,
            },
        )
        return {
            "request_id": request_id,
            "request_status": request_status,
            "completed": completed,
            "signed_at": signed_at,
        }

    engine.register_action("lifecycle.sign_send_contract", send_contract)
    engine.register_action("lifecycle.sign_sync_status", sync_contract_status)
