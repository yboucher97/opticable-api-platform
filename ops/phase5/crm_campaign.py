#!/usr/bin/env python3
"""Review/apply declared CRM additions through the canonical Desired State engine.

The JSON-lines bridge lets the authorized connector supply live responses without
copying any credentials into this process. Each write is requested once only.
EOF/transport loss leaves the committed intent unresolved. Never resume with a
fresh evidence database after an interrupted write.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/workflow-api"))
from workflow.automation.crm_inventory import normalize, snapshot
from workflow.automation.desired_state import DesiredStateController, DesiredStateRegistry
from workflow.automation.reconcilers.zoho_crm import ZohoCrmFieldReconciler
from workflow.automation.reconcilers.zoho_metadata import register_crm_metadata
from workflow.automation.store import AutomationStore


class SnapshotClient:
    def __init__(self, source):
        self.entries = source["entries"]

    def request(self, service, method, path, **kwargs):
        if service != "zohoapis" or method != "GET":
            raise ValueError("snapshot is read-only")
        module = (kwargs.get("query") or {}).get("module")
        if "/workflow_rules/" in path:
            key = "workflow:" + path.rsplit("/", 1)[1]
        elif "/layouts/" in path:
            key = "layouts:" + module
        elif "/webhooks/" in path:
            key = "webhooks"
        else:
            key = path.rsplit("/", 1)[1] + (":" + module if module else "")
        item = self.entries[key]
        return {"ok": item["status"] in {"complete", "empty"}, "status": item["http_status"], "data": item.get("data", {})}


class ConnectorBridge:
    def request(self, service, method, path, **kwargs):
        # The bridge only permits bounded CRM metadata GETs and two exact
        # optional-field additions. No general write gateway is exposed.
        if service != "zohoapis" or not path.startswith("/crm/v8/settings/"):
            raise ValueError("bridge path denied")
        if method != "GET":
            fields = (kwargs.get("body") or {}).get("fields", [])
            if method != "POST" or path != "/crm/v8/settings/fields" or kwargs.get("query") != {"module": "Leads"} or len(fields) != 1:
                raise ValueError("bridge mutation denied")
            expected = {"Service_Types": {"api_name": "Service_Types", "field_label": "Service Types", "data_type": "text", "length": 255},
                        "Next_Followup_At": {"api_name": "Next_Followup_At", "field_label": "Next Followup At", "data_type": "datetime"}}
            if fields[0] != expected.get(fields[0].get("api_name")):
                raise ValueError("bridge field definition denied")
        print(json.dumps({"bridge_request": {"service": service, "method": method, "path": path, **kwargs}}), flush=True)
        line = sys.stdin.readline()
        if not line:
            raise TimeoutError("connector bridge response lost")
        response = json.loads(line)
        if response.get("bridge_error"):
            raise TimeoutError("connector bridge transport outcome unknown")
        return response


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--document", required=True)
    p.add_argument("--snapshot")
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--apply-plan-hash")
    args = p.parse_args()
    if sys.stdin.isatty():
        import termios
        attributes = termios.tcgetattr(sys.stdin.fileno())
        attributes[3] &= ~(termios.ECHO | termios.ICANON)
        attributes[6][termios.VMIN] = 1
        attributes[6][termios.VTIME] = 0
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, attributes)
    target = Path(args.evidence_dir)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = SnapshotClient(json.loads(Path(args.snapshot).read_text())) if args.snapshot else ConnectorBridge()
    registry = DesiredStateRegistry()
    registry.register("zoho_crm", "field", ZohoCrmFieldReconciler(client))
    register_crm_metadata(registry, client)
    store = AutomationStore(target / "evidence.db")
    controller = DesiredStateController(registry, store)
    document = controller.load(Path(args.document))
    plan = controller.plan(document)
    (target / "plan.json").write_text(json.dumps(plan.model_dump(mode="json"), sort_keys=True, indent=2) + "\n")
    if args.apply_plan_hash:
        if args.snapshot or args.apply_plan_hash != plan.plan_hash:
            raise ValueError("live reviewed immutable plan required")
        if any(c.action not in {"create", "noop"} or c.risk != "low" for c in plan.changes):
            raise ValueError("campaign permits additive low-risk changes only")
        results = controller.apply(document, plan, low_risk_additive_only=True, actor="authorized-phase5-campaign")
        after = controller.plan(document)
        result = {"plan_hash": plan.plan_hash, "document_hash": plan.document_hash,
                  "results": [r.model_dump() for r in results], "after": after.model_dump(),
                  "result": "PASS" if all(r.status == "completed" for r in results) and after.summary == {"noop": len(results)} else "MANUAL"}
        (target / "apply.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        print(json.dumps({"campaign_result": result["result"], "after": after.summary}), flush=True)
    else:
        print(json.dumps({"campaign_result": "PLAN", "plan_hash": plan.plan_hash, "summary": plan.summary}), flush=True)


if __name__ == "__main__":
    main()
