#!/usr/bin/env python3
"""Create one registered synthetic due Lead and enqueue through the legacy proposal path.

This prepares the scenario only. The scheduled runner alone selects and creates
the internal follow-up Task after policy evaluation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase11"))
from workflow.automation.business_autonomy import BusinessJournal
from workflow.automation.phase12_followup import propose_legacy_followup
from test_lab_operations import LAB, STATE, load, provider, read, write

DB = Path("/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db")
KEY = "phase12:closure-due-lead-v2"
TORONTO = ZoneInfo("America/Toronto")


def main():
    if os.geteuid() != 0 or sys.argv[1:] != ["--prepare"]:
        raise SystemExit("root and --prepare required")
    client, lab, state = provider(), load(LAB), load(STATE)
    previous = state["operations"].get(KEY)
    if previous:
        if previous.get("state") != "verified" or not previous.get("id"):
            raise ValueError("Lead create attempted; reconcile before replay")
        row = read(client, "Leads", previous["id"])
    else:
        due = (datetime.now(timezone.utc)-timedelta(minutes=10)).astimezone(TORONTO).replace(microsecond=0).isoformat()
        row = write(client, state, lab, KEY, "Leads", {
            "Last_Name": "OPTIBRAIN TEST — PHASE 12 — Scheduled Follow-up",
            "Company": "OPTIBRAIN TEST — PHASE 12 — Runner Lab",
            "Description": "OPTIBRAIN TEST — PHASE 12\nSynthetic due follow-up; internal Task only. No customer outreach.",
            "Email": "scheduled.phase12@optibrain.invalid", "Lead_Status": "Not Contacted",
            "Next_Followup_At": due, "OptiBrain_Test": True,
            "Ingestion_Source": "manual / CRM", "First_Source": "Phase 12 Test Lab"})
    journal = BusinessJournal(DB)
    proposal = propose_legacy_followup(client, journal, str(row["id"]))
    if proposal["state"] != "pending" or proposal["ownership"] != "TEST_ONLY":
        raise ValueError("Central proposal path did not queue due Test Lead")
    print(json.dumps({"lead_id": str(row["id"]), "deadline": row["Next_Followup_At"],
                      "action_id": proposal["action_id"], "state": proposal["state"]}, indent=2))


if __name__ == "__main__": main()
