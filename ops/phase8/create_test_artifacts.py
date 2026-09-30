#!/usr/bin/env python3
"""Manual, root-only, at-most-once controlled Phase 8 Task and unsent draft."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path("/opt/opticable-api-platform")
APP = ROOT / "apps/workflow-api"
STATE = Path("/var/lib/optibrain/phase8/20260930-consolidation/artifacts.json")
LEAD = "5062683000007880001"
EMAIL = "hckyan97@gmail.com"
SENDER = "yboucher@opticable.ca"
ACCOUNT = "1083319000000008002"
DRAFT_FOLDER = "1083319000000008016"
TORONTO = ZoneInfo("America/Toronto")


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def atomic(state):
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, STATE)


def loaded():
    if STATE.exists():
        info = STATE.lstat()
        if not STATE.is_file() or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("Unsafe artifact state")
        return json.loads(STATE.read_text())
    return {}


def provider_rows(response, *, empty=False):
    if empty and response.get("ok") is True and response.get("status") == 204:
        return []
    if response.get("ok") is not True or response.get("status") != 200:
        raise ValueError("Provider read failed")
    value = (response.get("data") or {}).get("data")
    if not isinstance(value, list):
        raise ValueError("Provider records unavailable")
    return value


def task_matches(row, subject, due):
    related = row.get("What_Id")
    related_id = related.get("id") if isinstance(related, dict) else None
    return (row.get("Subject") == subject and str(related_id) == LEAD
            and row.get("Due_Date") == due and row.get("Status") == "Not Started")


def task_search(client, subject, due):
    rows = provider_rows(client.request("zohoapis", "GET", "/crm/v8/Tasks/search",
        query={"criteria": f"(Subject:equals:{subject})", "per_page": 10}), empty=True)
    if len(rows) > 1 or any(not task_matches(x, subject, due) for x in rows):
        raise ValueError("Task collision or ambiguous relation")
    return rows


def task_id_from_ack(response):
    if response.get("ok") is not True or response.get("status") not in {200, 201, 202}:
        raise ValueError("Task acknowledgement failed; reconcile before retry")
    rows = (response.get("data") or {}).get("data")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "success":
        raise ValueError("Task acknowledgement ambiguous; reconcile before retry")
    identity = str((rows[0].get("details") or {}).get("id") or "")
    if not re.fullmatch(r"[0-9]{1,30}", identity):
        raise ValueError("Task acknowledgement has no provider ID")
    return identity


def draft_list(client):
    rows = []
    for start in range(0, 500, 100):
        response = client.request("mail", "GET", f"/api/accounts/{ACCOUNT}/messages/view",
                                  query={"folderId": DRAFT_FOLDER, "start": start, "limit": 100})
        outer = response.get("data") or {}
        if (response.get("ok") is not True or response.get("status") != 200
                or (outer.get("status") or {}).get("code") != 200
                or not isinstance(outer.get("data"), list)):
            raise ValueError("Draft folder read failed")
        rows.extend(outer["data"])
        if len(outer["data"]) < 100:
            return rows
    raise ValueError("Draft folder exceeds bounded reconciliation")


def draft_candidates(client, subject):
    return [x for x in draft_list(client)
            if x.get("subject") == subject and str(x.get("toAddress") or "").casefold().find(EMAIL) >= 0]


def prepare(client, db_path):
    from workflow.automation.sales_operator_view import build_sales_operator_view
    from workflow.automation.sales_queue import future_controlled_draft
    from workflow.automation.crm_write_boundary import fingerprint
    view = build_sales_operator_view(client, db_path, account_id=ACCOUNT,
                                     from_address=SENDER, lead_id=LEAD)
    if (view["lead"]["email"].casefold() != EMAIL or view["dedupe"]["matches"] != 1
            or view["follow_up"]["status"] != "WAIT"
            or view["evidence"]["mail"]["reply_state"] != "NO_REPLY_YET"
            or view["evidence"]["mail"]["last_outbound"]["message_id"] != "1790714949014155100"):
        raise ValueError("Controlled Lead no longer satisfies test preflight")
    lead_due = view["follow_up"]["current"]
    # The CRM Task has a date-only Due_Date; the Lead keeps the precise 17:00 deadline.
    from workflow.automation.sales_operator_view import _aware
    detail = provider_rows(client.request("zohoapis", "GET", f"/crm/v8/Leads/{LEAD}"))[0]
    due_instant = _aware(detail["Next_Followup_At"]).astimezone(TORONTO)
    if due_instant <= datetime.now(timezone.utc).astimezone(TORONTO):
        raise ValueError("Follow-up deadline is no longer in the future")
    due = due_instant.date().isoformat()
    generation = sha(LEAD + "|" + due + "|phase8-test")[:16]
    subject = f"TEST ONLY — OPTIBRAIN PHASE 8 — {LEAD} — {generation}"
    task = {"data": [{"Subject": subject, "What_Id": {"id": LEAD}, "$se_module": "Leads",
                      "Status": "Not Started", "Due_Date": due}], "trigger": []}
    preview = future_controlled_draft(view)
    if preview is None:
        raise ValueError("No safe future draft for controlled Lead")
    draft_subject, draft_body = preview["subject"], preview["body"]
    draft = {"mode": "draft", "fromAddress": SENDER, "toAddress": EMAIL,
             "subject": draft_subject, "content": draft_body, "mailFormat": "plaintext"}
    return task, draft, {"lead_id": LEAD, "deadline_local": lead_due,
                         "task_date": due, "task_subject": subject,
                         "task_payload_hash": fingerprint("POST", "/crm/v8/Tasks", task, None),
                         "draft_subject": draft_subject, "draft_body_sha256": sha(draft_body),
                         "draft_payload_sha256": sha(json.dumps(draft, sort_keys=True, ensure_ascii=False))}


def main():
    if os.geteuid() != 0 or sys.argv[1:] not in (["--dry-run"], ["--execute"]):
        raise SystemExit("Root and --dry-run or --execute required")
    if subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip() != (
            subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "main"], text=True).strip()):
        raise ValueError("Production/main mismatch")
    pid = subprocess.check_output(["systemctl", "show", "opticable-workflow-api.service",
                                   "-p", "MainPID", "--value"], text=True).strip()
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            os.environ[key.decode()] = value.decode()
    sys.path.insert(0, str(APP))
    from workflow.config import load_settings
    from workflow.zoho_oauth import ZohoOAuthManager
    from workflow.zoho_gateway import ZohoGatewayClient
    from workflow.automation.crm_write_boundary import (
        PHASE8_TEST_TASK_POLICY, reviewed_phase8_test_task_call)
    from workflow.automation.providers.mail_drafts import save_mail_draft
    from workflow.automation.followup_mail import _data, _plain_body
    settings = load_settings()
    client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
    task, draft, plan = prepare(
        client, Path("/var/lib/opticable-workflow-api/output/automation/automation.db"))
    if sys.argv[1] == "--dry-run":
        print(json.dumps(plan, indent=2))
        return
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = STATE.with_suffix(".lock")
    with lock.open("a+") as handle:
        os.chmod(lock, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = loaded()
        if state and state.get("plan") != plan:
            if (state.get("task", {}).get("state") != "rejected"
                    or state.get("draft", {}).get("state") != "pending"
                    or state["plan"]["task_subject"] != plan["task_subject"]
                    or state["plan"]["draft_payload_sha256"] != plan["draft_payload_sha256"]
                    or task_search(client, state["plan"]["task_subject"], state["plan"]["task_date"])):
                raise ValueError("Artifact plan changed; manual reconciliation required")
            state.setdefault("rejected_attempts", []).append({
                "plan": state["plan"], "task": state["task"]})
            state["plan"] = plan
            state["task"] = {"state": "pending"}
            atomic(state)
        if not state:
            state = {"plan": plan, "task": {"state": "pending"}, "draft": {"state": "pending"}}
            atomic(state)
        prior = task_search(client, plan["task_subject"], plan["task_date"])
        if state["task"]["state"] == "pending":
            if prior:
                raise ValueError("Equivalent Task already exists outside journal")
            state["task"] = {"state": "attempted", "at": datetime.now(timezone.utc).isoformat()}
            atomic(state)
            os.environ["OPTIBRAIN_PHASE8_TEST_TASK"] = PHASE8_TEST_TASK_POLICY
            with reviewed_phase8_test_task_call(client, task, payload_hash=plan["task_payload_hash"]):
                response = client.request("zohoapis", "POST", "/crm/v8/Tasks", body=task,
                                          reason="Single authorized controlled Phase 8 test Task",
                                          confirm=True)
            state["task"]["ack_id"] = task_id_from_ack(response)
            atomic(state)
        prior = task_search(client, plan["task_subject"], plan["task_date"])
        ack_id = state["task"].get("ack_id") or state["task"].get("id")
        if not ack_id and len(prior) == 1:
            ack_id = str(prior[0]["id"])
        if not ack_id:
            raise ValueError("Task acknowledgement ambiguous; no retry")
        task_id = str(ack_id)
        readback = provider_rows(client.request("zohoapis", "GET", f"/crm/v8/Tasks/{task_id}"))
        if len(readback) != 1 or not task_matches(readback[0], plan["task_subject"], plan["task_date"]):
            raise ValueError("Task readback mismatch")
        if prior and (len(prior) != 1 or str(prior[0]["id"]) != task_id):
            raise ValueError("Task duplicate search conflicts with readback")
        state["task"] = {"state": "verified", "id": task_id}
        atomic(state)
        previous_drafts = draft_candidates(client, plan["draft_subject"])
        if state["draft"]["state"] == "pending":
            if previous_drafts:
                raise ValueError("Equivalent draft already exists outside journal")
            state["draft"] = {"state": "attempted", "at": datetime.now(timezone.utc).isoformat()}
            atomic(state)
            response = save_mail_draft(client, ACCOUNT, draft)
            state["draft"]["response"] = response.get("data")
            atomic(state)
        previous_drafts = draft_candidates(client, plan["draft_subject"])
        if len(previous_drafts) != 1:
            raise ValueError("Draft acknowledgement ambiguous; no retry")
        item = previous_drafts[0]
        draft_id = str(item.get("messageId") or "")
        folder = str(item.get("folderId") or "")
        if not re.fullmatch(r"[0-9]{1,30}", draft_id) or folder != DRAFT_FOLDER:
            raise ValueError("Draft readback identity mismatch")
        path = f"/api/accounts/{ACCOUNT}/folders/{folder}/messages/{draft_id}"
        details = _data(client.request("mail", "GET", path + "/details"), dict)
        content = _plain_body(client.request("mail", "GET", path + "/content"))
        if (details.get("subject") != plan["draft_subject"]
                or EMAIL not in str(details.get("toAddress") or "").casefold()
                or SENDER not in str(details.get("fromAddress") or "").casefold()
                or sha(content) != plan["draft_body_sha256"]):
            raise ValueError("Draft readback or body hash mismatch; do not send")
        state["draft"] = {"state": "verified", "id": draft_id,
                          "body_sha256": sha(content), "folder_id": folder, "sent": False}
        atomic(state)
        print(json.dumps({"task_id": task_id, "task_date": plan["task_date"],
                          "draft_id": draft_id, "sent": False,
                          "draft_body_sha256": state["draft"]["body_sha256"]}))


if __name__ == "__main__":
    main()
