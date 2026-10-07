from __future__ import annotations

from typing import Any

from ...windsor_api import WindsorApiClient
from ..engine import AutomationEngine
from ..models import WorkflowStep
from ..store import AutomationStore


_COST_RISK_ACTIONS = {
    "create_campaign",
    "create_adset",
    "create_ad_group",
    "create_ad",
    "boost_post",
    "set_campaign_budget",
    "set_adset_budget",
    "set_ad_group_budget",
    "set_cpc_bid_ceiling",
    "set_max_cpc",
    "set_target_cpa",
    "set_target_roas",
}


def register_windsor_actions(engine: AutomationEngine, client: WindsorApiClient, store: AutomationStore) -> None:
    def read(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        connector = str(step.inputs.get("connector", "")).strip()
        fields = step.inputs.get("fields") or []
        params = step.inputs.get("params") or {}
        if not isinstance(fields, list) or not isinstance(params, dict):
            raise ValueError("windsor.read fields must be a list and params must be an object.")
        return client.read(connector, fields=fields, params=params)

    def list_actions(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        return client.list_actions(str(step.inputs.get("connector", "")).strip())

    def execute(context: dict[str, Any], step: WorkflowStep) -> dict[str, Any]:
        connector = str(step.inputs.get("connector", "")).strip()
        account = str(step.inputs.get("account", "")).strip()
        action = str(step.inputs.get("action_id", "")).strip()
        params = step.inputs.get("params") or {}
        reason = str(step.inputs.get("reason", "")).strip()
        if not isinstance(params, dict):
            raise ValueError("windsor.execute_action params must be an object.")
        if not reason:
            raise ValueError("windsor.execute_action requires with.reason.")
        if action in _COST_RISK_ACTIONS:
            raise ValueError(
                f"Windsor action {action} may create or increase paid spend and is blocked from autonomous workflows. "
                "Use an explicit human-approved execution path."
            )
        from datetime import datetime,timezone
        from ..action_evidence import ActionEvidence
        from ..acquisition_store import digest
        audit=ActionEvidence(store.db_path);aid=step.inputs.get('audit_action_id');plan=audit.get(aid) if isinstance(aid,str) else None
        expected={'connector':connector,'account':account,'action':action,'params':params}
        if not plan or plan['status']!='STARTED' or not plan['mutation'] or plan['provider']!='WINDSOR' or plan['target']['identity']!=account or digest(plan['proposed_state'])!=digest(expected):
            raise ValueError('Windsor mutation requires an exact pre-execution audit, before state, authority and rollback contract')
        if plan['readback_supported'] or not plan['unknowns']:
            raise ValueError('This generic Windsor adapter requires documented absent native readback; a verified adapter is needed otherwise')
        try:
            result = client.execute_action(connector, account=account, action=action, params=params)
        except Exception as exc:
            audit.finish(aid,datetime.now(timezone.utc),provider_success=False,failure={
                'stage':'PROVIDER_EXECUTION','error_class':type(exc).__name__,'provider_status':getattr(getattr(exc,'response',None),'status_code',None),
                'safe_details':type(exc).__name__,'partial_effects':'UNKNOWN','recovery_action':'Native provider read-only reconciliation; no retry'})
            raise
        audit.finish(aid,datetime.now(timezone.utc),provider_success=True,response=result,limitation=plan['unknowns'][0])
        event = context.get("event") or {}
        store.audit(
            category="provider_mutation",
            action=f"windsor.{connector}.{action}",
            actor="automation-engine",
            success=True,
            correlation_id=event.get("correlation_id") or event.get("event_id"),
            target=account,
            metadata={
                "reason": reason,
                "workflow_id": (context.get("workflow") or {}).get("id"),
                "step_id": step.id,
                "param_keys": sorted(params.keys()),
            },
        )
        return result

    engine.register_action("windsor.read", read, retry_safe=True)
    engine.register_action("windsor.list_actions", list_actions, retry_safe=True)
    engine.register_action("windsor.execute_action", execute)
