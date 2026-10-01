#!/usr/bin/env python3
"""Exactly one mission-authorized controlled TEST_ONLY Phase 12 R3 Mail proof.

The approver is the explicit manual-mission authority, recorded as such; this
does not simulate a Cloudflare login or expose a customer-send API endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

APP = Path(__file__).resolve().parents[2] / "apps/workflow-api"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase11"))
from workflow.automation.business_autonomy import (Action, BusinessJournal,
    Policy, classify_crm_record, decide, dispatch_approved)
from workflow.automation.followup_mail import _data, _plain_body
from workflow.automation.providers.outbound_mail import _provider_message_id
from test_lab_operations import LAB, BASELINE, load, provider, read

ROOT = Path("/var/lib/optibrain/phase12/test-lab")
STATE = ROOT / "approved-mail.json"
DB = Path("/var/lib/opticable-workflow-api/output/automation/phase12-autonomy.db")
ACCOUNT = "1083319000000008002"
SENT = "1083319000000008022"
LEAD = "5062683000007915001"
SENDER = "yboucher@opticable.ca"
RECIPIENT = "hckyan97+obp8wait@gmail.com"
ACTOR = "human:manual_phase12_mission"


def atomic(value):
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_name(".approved-mail.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temp, STATE)


def lead(client, lab, baseline):
    row = read(client, "Leads", LEAD)
    owned = classify_crm_record("Leads", row,
        registered_test_ids=set(lab["records"]["Leads"]),
        protected_ids=set(baseline["modules"]["Leads"]["ids"]))
    if owned != "TEST_ONLY" or row.get("Email") != RECIPIENT:
        raise ValueError("Controlled TEST_ONLY Lead identity changed")
    row["ownership"] = owned
    return row


def action(value):
    return Action("email.send", "Leads", LEAD,
        "phase12:r3-mail:" + value["token"],
        {"sender": SENDER, "recipient": RECIPIENT, "subject": value["subject"],
         "body_hash": value["body_hash"], "mailbox_account_id": ACCOUNT,
         "purpose": "Manual mission controlled Test Lab approval proof"},
        expected_version=value["lead_version"], expected_state={"Email": RECIPIENT},
        provider="zoho_mail")


def verify_sent(client, message_id, value):
    if not str(message_id).isdigit(): return None
    path = f"/api/accounts/{ACCOUNT}/folders/{SENT}/messages/{message_id}"
    item = _data(client.request("mail", "GET", path + "/details"), dict)
    body = _plain_body(client.request("mail", "GET", path + "/content"))
    if (str(item.get("messageId")) != str(message_id) or str(item.get("folderId")) != SENT
            or item.get("subject") != value["subject"]
            or SENDER not in str(item.get("fromAddress") or "").lower()
            or RECIPIENT not in str(item.get("toAddress") or "").lower()
            or sha256(body.encode()).hexdigest() != value["body_hash"]):
        return None
    return str(message_id)


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "approve", "send", "status"}:
        raise SystemExit("root required: approved_test_mail.py prepare|approve|send|status")
    command = sys.argv[1]
    client = provider(); lab, baseline = load(LAB), load(BASELINE)
    journal = BusinessJournal(DB)
    value = json.loads(STATE.read_text()) if STATE.exists() else None
    if command == "prepare":
        if value: raise ValueError("Controlled send already prepared; reconcile, never recreate")
        current = lead(client, lab, baseline)
        token = uuid4().hex[:16]
        subject = f"OPTIBRAIN TEST — PHASE 12 — Approval boundary {token}"
        body = (f"OPTIBRAIN TEST ONLY. Controlled operator-to-operator message {token}.\n"
                "This verifies an exact, single-use human-approved business action.\n"
                "No customer request or real project is represented.\n")
        value = {"token": token, "subject": subject, "body": body,
                 "body_hash": sha256(body.encode()).hexdigest(),
                 "lead_version": current["Modified_Time"], "state": "prepared",
                 "approval_basis": "Explicit 2026-10-01 manual Phase 12 closure mission authorizes one controlled TEST_ONLY send"}
        proposal = action(value)
        row = journal.prepare(proposal, decide(proposal, "TEST_ONLY", Policy()))
        if row["state"] != "approval_required": raise ValueError("R3 policy did not require approval")
        value["action_id"] = proposal.action_id; value["payload_hash"] = proposal.payload_hash
        atomic(value)
    elif command == "approve":
        if not value or value["state"] != "prepared": raise ValueError("Exact prepared proposal required")
        current = lead(client, lab, baseline)
        if current["Modified_Time"] != value["lead_version"]: raise ValueError("Approval target became stale")
        proposal = action(value)
        approval = journal.issue(proposal, actor=ACTOR,
            expires_at=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat())
        value["approval_id"] = approval["approval_id"]
        value["approval_expires_at"] = approval["expires_at"]
        value["state"] = "approved"; atomic(value)
    elif command == "send":
        if not value or value["state"] != "approved": raise ValueError("One unused exact approval required")
        proposal = action(value)
        def execute():
            if value["state"] != "approved": raise ValueError("Mail attempt already recorded")
            value["state"] = "attempted"; atomic(value)
            response = client.request("mail", "POST", f"/api/accounts/{ACCOUNT}/messages",
                body={"fromAddress": SENDER, "toAddress": RECIPIENT,
                      "subject": value["subject"], "content": value["body"],
                      "mailFormat": "plaintext"},
                reason="One exact mission-approved controlled Phase 12 TEST_ONLY send", confirm=True)
            message_id = _provider_message_id(response)
            if not message_id: raise ValueError("Mail acknowledgement ambiguous; no retry")
            value["ack_id"] = message_id; atomic(value)
            return message_id
        result = dispatch_approved(proposal, approval_id=value["approval_id"], actor=ACTOR,
            journal=journal, fresh=lambda: lead(client, lab, baseline), execute=execute,
            reconcile=lambda: verify_sent(client, value.get("ack_id"), value))
        if result["state"] == "succeeded":
            value["state"] = "verified"; value["message_id"] = result["provider_id"]
            value["verified_at_utc"] = datetime.now(timezone.utc).isoformat(); atomic(value)
        else:
            raise ValueError("Approved send requires read-only reconciliation; never resend")
    else:
        if not value: raise ValueError("No controlled mail proposal")
        value = {k: v for k, v in value.items() if k != "body"}
        if value.get("ack_id"):
            value["sent_readback"] = bool(verify_sent(client, value["ack_id"], value))
    print(json.dumps({k: v for k, v in value.items() if k != "body"}, indent=2, sort_keys=True))


if __name__ == "__main__": main()
