from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...zoho_gateway import ZohoGatewayClient
from ..engine import AutomationEngine
from ..models import AutomationEvent, WorkflowStep
from ..store import AutomationStore

_TERMINAL_STATUSES = {"completed", "declined", "expired", "recalled"}


def _raw(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("data")
    return value if isinstance(value, dict) else {}


def _created_id(response: dict[str, Any]) -> str | None:
    raw = _raw(response)
    rows = raw.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    details = rows[0].get("details")
    if isinstance(details, dict) and details.get("id"):
        return str(details["id"])
    return str(rows[0].get("id")) if rows[0].get("id") else None


def register_lifecycle_sign_tracking_actions(
    engine: AutomationEngine,
    client: ZohoGatewayClient,
    store: AutomationStore,
) -> None:
    def poll_sign_status(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        max_requests = max(1, min(100, int(step.inputs.get("max_requests") or 100)))
        audit = store.recent_audit(500)
        sent_by_id: dict[str, dict[str, Any]] = {}
        for item in audit:
            if item.get("action") != "contract_sent" or not item.get("success"):
                continue
            request_id = str(item.get("target") or "").strip()
            if request_id and request_id not in sent_by_id:
                sent_by_id[request_id] = item
            if len(sent_by_id) >= max_requests:
                break

        parent = AutomationEvent.model_validate(context["event"])
        checked = 0
        terminal = 0
        emitted = 0
        nonterminal = 0
        failed = 0
        statuses: dict[str, int] = {}

        for request_id, audit_item in sent_by_id.items():
            try:
                response = client.request("sign", "GET", f"/requests/{request_id}")
                raw = _raw(response)
                request = raw.get("requests")
                if not isinstance(request, dict):
                    raise RuntimeError("Zoho Sign did not return request details.")
                checked += 1
                status = str(request.get("request_status") or "unknown").strip().lower()
                statuses[status] = statuses.get(status, 0) + 1
                if status not in _TERMINAL_STATUSES:
                    nonterminal += 1
                    continue

                terminal += 1
                metadata = audit_item.get("metadata") if isinstance(audit_item.get("metadata"), dict) else {}
                actions = request.get("actions") if isinstance(request.get("actions"), list) else []
                signer = next(
                    (
                        action for action in actions
                        if isinstance(action, dict) and str(action.get("action_type") or "").upper() == "SIGN"
                    ),
                    {},
                )
                child = AutomationEvent(
                    event_type=f"customer.lifecycle.contract.{status}",
                    source="zoho-sign-status-poller",
                    correlation_id=parent.correlation_id or parent.event_id,
                    causation_id=parent.event_id,
                    idempotency_key=f"contract-status:{request_id}:{status}",
                    depth=parent.depth + 1,
                    payload={
                        "request_id": request_id,
                        "request_name": request.get("request_name"),
                        "status": status,
                        "deal_id": metadata.get("deal_id"),
                        "service_id": metadata.get("service_id"),
                        "template": metadata.get("template"),
                        "recipient_email": signer.get("recipient_email"),
                        "recipient_name": signer.get("recipient_name"),
                        "action_status": signer.get("action_status"),
                    },
                )
                result = engine.ingest(child)
                if not result.duplicate:
                    emitted += 1
                    store.audit(
                        category="customer_lifecycle",
                        action="contract_terminal_status_observed",
                        actor="automation-engine",
                        success=True,
                        correlation_id=child.correlation_id,
                        target=request_id,
                        metadata={"status": status, "deal_id": metadata.get("deal_id")},
                    )
            except Exception as exc:
                failed += 1
                store.audit(
                    category="customer_lifecycle",
                    action="contract_status_poll_failed",
                    actor="automation-engine",
                    success=False,
                    correlation_id=parent.correlation_id or parent.event_id,
                    target=request_id,
                    metadata={"error": type(exc).__name__},
                )

        return {
            "tracked": len(sent_by_id),
            "checked": checked,
            "terminal": terminal,
            "nonterminal": nonterminal,
            "emitted": emitted,
            "failed": failed,
            "statuses": statuses,
            "sign_mutations": 0,
            "books_mutations": 0,
        }

    def create_contract_status_task(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        contract = step.inputs.get("contract")
        if not isinstance(contract, dict):
            raise ValueError("lifecycle.crm_contract_status_task requires with.contract object.")
        status = str(contract.get("status") or "").strip().lower()
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal contract status: {status}")
        request_id = str(contract.get("request_id") or "").strip()
        if not request_id:
            raise ValueError("Contract status task requires request_id.")
        deal_id = str(contract.get("deal_id") or "").strip() or None
        subject_map = {
            "completed": "Contract signed - prepare project handoff",
            "declined": "Contract declined - review customer follow-up",
            "expired": "Contract expired - review and resend if appropriate",
            "recalled": "Contract recalled - review next action",
        }
        description = (
            f"Zoho Sign request: {request_id}\n"
            f"Status: {status}\n"
            f"Request: {str(contract.get('request_name') or '')}\n"
            f"Service ID: {str(contract.get('service_id') or '')}\n"
            f"Recipient: {str(contract.get('recipient_name') or '')} <{str(contract.get('recipient_email') or '')}>"
        )
        record: dict[str, Any] = {
            "Subject": subject_map[status],
            "Due_Date": datetime.now(ZoneInfo("America/Toronto")).date().isoformat(),
            "Priority": "High" if status in {"declined", "expired"} else "Normal",
            "Description": description[:32000],
        }
        if deal_id:
            record["What_Id"] = deal_id
            record["$se_module"] = "Deals"
        response = client.request(
            "zohoapis",
            "POST",
            "/crm/v8/Tasks",
            body={"data": [record]},
            reason=f"Customer lifecycle: create CRM task for terminal contract status {status}",
            confirm=True,
        )
        task_id = _created_id(response)
        return {"task_id": task_id, "status": status, "request_id": request_id, "deal_id": deal_id}

    engine.register_action("lifecycle.sign_poll_status", poll_sign_status)
    engine.register_action("lifecycle.crm_contract_status_task", create_contract_status_task)
