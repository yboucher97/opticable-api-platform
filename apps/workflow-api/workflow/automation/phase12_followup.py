"""Central-policy proposal for the formerly blocked legacy follow-up Task action.

The workflow/API service may only enqueue a reviewed proposal. The separate
root-only scheduled runner performs exact Test Lab provider writes later.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .business_autonomy import Action, BusinessJournal, Policy, aware, classify_crm_record, decide

LAB = Path("/etc/optibrain/phase8-test-lab-registry.json")
BASELINE = Path("/etc/optibrain/phase9-protected-baseline.json")
TORONTO = ZoneInfo("America/Toronto")
CLOSED = {"Closed", "Closed Lost", "Disqualified", "Converted", "Junk Lead"}


def _lead(client, lead_id: str) -> dict:
    if not re.fullmatch(r"[0-9]{1,30}", str(lead_id)):
        raise ValueError("Exact numeric Lead ID required")
    reply = client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}")
    rows = (reply.get("data") or {}).get("data") or []
    if reply.get("ok") is not True or len(rows) != 1 or str(rows[0].get("id")) != lead_id:
        raise ValueError("Exact Lead provider read unavailable")
    return rows[0]


def propose_legacy_followup(client, journal: BusinessJournal, lead_id: str, *,
                            now: datetime | None = None, lab_path: Path = LAB,
                            baseline_path: Path = BASELINE) -> dict:
    """No provider mutation; hardcoded Task shape and immutable due-window key."""
    clock = aware(now or datetime.now(timezone.utc))
    lead = _lead(client, lead_id)
    registry, baseline = json.loads(lab_path.read_text()), json.loads(baseline_path.read_text())
    ownership = classify_crm_record("Leads", lead,
        registered_test_ids=set(registry["records"]["Leads"]),
        protected_ids=set(baseline["modules"]["Leads"]["ids"]))
    deadline = lead.get("Next_Followup_At")
    if not deadline or str(lead.get("Lead_Status") or "") in CLOSED:
        return {"state": "no_action", "reason": "No actionable open follow-up obligation", "ownership": ownership}
    due = aware(deadline)
    local_day = due.astimezone(TORONTO).date().isoformat()
    fingerprint = sha256(f"{lead_id}|{due.isoformat()}".encode()).hexdigest()[:20]
    subject = f"OPTIBRAIN TEST — PHASE 12 — Follow-up review {lead_id} {fingerprint}"
    action = Action("crm.task.create", "Leads", lead_id,
        f"phase12:followup:{lead_id}:{fingerprint}",
        {"Subject": subject, "Due_Date": local_day, "Status": "Not Started",
         "purpose": "Internal follow-up review; no customer send"},
        expected_version=lead["Modified_Time"],
        expected_state={"Next_Followup_At": deadline, "Lead_Status": lead.get("Lead_Status")})
    decision = decide(action, ownership, Policy(automatic_mutations=True, auto_test_task=True))
    if ownership != "TEST_ONLY":
        row = journal.prepare(action, decision)
        return {"state": row["state"], "reason": row["reason"], "ownership": ownership,
                "action_id": row["action_id"]}
    journal.prepare(action, decision)
    scheduled = journal.enqueue(action, due_at=due.isoformat(),
                                source_trigger="legacy.crm_create_followup_task")
    return {"state": scheduled["state"], "ownership": ownership,
            "action_id": action.action_id, "due_at": due.isoformat(), "overdue": due <= clock}
