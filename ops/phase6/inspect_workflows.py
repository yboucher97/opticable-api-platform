#!/usr/bin/env python3
"""Read-only definition hashes/actions; never print customer inputs or initialize DB."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/workflow-api"))
from workflow.automation.models import WorkflowDefinition


def definition_hash(document):
    normalized = WorkflowDefinition.model_validate(document).model_dump(by_alias=True)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def inspect(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        result = []
        for name, enabled, raw in connection.execute("SELECT workflow_id,enabled,definition_json FROM automation_workflows ORDER BY workflow_id"):
            document = json.loads(raw)
            definition = WorkflowDefinition.model_validate(document)
            if definition.id != name or bool(enabled) != definition.enabled:
                raise RuntimeError("workflow_metadata_mismatch")
            result.append({"workflow_id": name, "enabled": bool(enabled), "definition_sha256": definition_hash(document),
                           "actions": [step.action for step in definition.steps]})
        return result


if __name__ == "__main__":
    if len(sys.argv) != 1:
        raise SystemExit("No path overrides permitted")
    print(json.dumps({"workflows": inspect(Path("/var/lib/opticable-workflow-api/output/automation/automation.db"))}))
