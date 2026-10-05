"""Fail-closed normalization of a newly created Zoho Forms Lead.

The form notification has no CRM ID. We bind it to one provider-created Lead
using a complete inventory, exact submitted identity, a tight time window and
Zoho's creation timeline. Any collision or intervening edit requires review.
The write is journaled before transport and is never blindly retried.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .crm_write_boundary import _AUTHORITY, fingerprint
from .phase9_form_receipts import FormReceiptLedger
from .phase9_intake import IntakeLedger

POLICY = "phase9-form-enrichment-v1"
BASELINE = Path("/etc/optibrain/phase9-protected-baseline.json")
BASELINE_SHA256 = "b928cd44884169e150cbf7481edf07c5943bd7bc8989be667467936fda702d33"
FIELDS = ("id,Email,Normalized_Email,Phone,Company,First_Name,Last_Name,Description,"
          "Created_Time,Modified_Time,Ingestion_Source,First_Source,Last_Source,"
          "First_Touch_Time,Last_Touch_Time,Inquiry_ID,Source_Record_ID,OptiBrain_Test")
NORMALIZED = {"Email", "Normalized_Email", "Ingestion_Source", "First_Source", "Last_Source",
              "First_Touch_Time", "Last_Touch_Time", "Inquiry_ID", "Source_Record_ID",
              "OptiBrain_Test", "Description"}


def aware(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("Form enrichment requires aware instants")
    return dt.astimezone(timezone.utc)


def protected_ids(path=BASELINE):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("Protected CRM baseline digest changed")
    value = json.loads(raw)
    leads = value.get("modules", {}).get("Leads", {})
    if value.get("schema") != 1 or leads.get("status") != "complete" or len(leads.get("ids", [])) != 11:
        raise ValueError("Protected Lead baseline invalid")
    return set(leads["ids"]), aware(value["captured_at_utc"])


def _one(client, path):
    answer = client.request("zohoapis", "GET", path)
    rows = (answer.get("data") or {}).get("data")
    if answer.get("ok") is not True or not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Exact CRM provider readback unavailable")
    return rows[0]


def _inventory(client, module, fields):
    rows = []
    for page in range(1, 6):
        answer = client.request("zohoapis", "GET", f"/crm/v8/{module}",
            query={"fields": fields, "per_page": 200, "page": page})
        if answer.get("ok") is True and answer.get("status") == 204 and page == 1:
            return []
        data = answer.get("data") or {}
        if answer.get("ok") is not True or not isinstance(data.get("data"), list):
            raise ValueError(f"Complete {module} inventory unavailable")
        rows.extend(data["data"])
        if not (data.get("info") or {}).get("more_records"):
            return rows
    raise ValueError(f"{module} inventory exceeded safe bound")


def _creation_proof(client, lead, occurred):
    lead_id = str(lead.get("id") or "")
    result = client.request("zohoapis", "GET", f"/crm/v8/Leads/{lead_id}/__timeline")
    data = result.get("data") or {}
    events = data.get("__timeline")
    if (result.get("ok") is not True or not isinstance(events, list)
            or (data.get("info") or {}).get("more_records") or len(events) != 1):
        raise ValueError("Zoho Forms creation timeline is incomplete or changed")
    created = aware(lead["Created_Time"])
    event = events[0]
    if (event.get("action") != "added" or event.get("source") != "zoho_forms"
            or abs((aware(event.get("audited_time")) - created).total_seconds()) > 5
            or abs((created - occurred).total_seconds()) > 180):
        raise ValueError("CRM creation is not proven to be this form submission")
    return str(event.get("id") or "")


def _same(value, expected):
    if expected is True:
        return value is True
    if expected is None:
        return value is None
    if str(value or "") == str(expected):
        return True
    if str(expected).startswith("20"):
        try:
            return aware(value) == aware(expected)
        except (ValueError, TypeError):
            return False
    return False


def _expected(receipt, lead):
    email = str(receipt["submitted_email"]).strip().casefold()
    created = aware(lead["Created_Time"]).isoformat()
    expected = {"Email": email, "Normalized_Email": email,
                "Ingestion_Source": "zoho_form", "First_Source": "zoho_form",
                "Last_Source": "zoho_form", "First_Touch_Time": created,
                "Last_Touch_Time": created, "Inquiry_ID": receipt["event_id"],
                "Source_Record_ID": receipt["provider_message_id"]}
    if receipt["test_only"]:
        note = str(receipt["fields"].get("notes") or "")[:2500]
        expected.update({"OptiBrain_Test": True,
            "Description": "OPTIBRAIN TEST — PHASE 9\n" + note})
    return expected


def _preflight(client, ledger, receipt, lead, *, go_live, baseline_path=BASELINE):
    protected, baseline_at = protected_ids(baseline_path)
    lead_id = str(lead.get("id") or "")
    if not re.fullmatch(r"[0-9]{1,30}", lead_id) or lead_id in protected:
        raise ValueError("Protected or invalid CRM Lead target")
    created = aware(lead.get("Created_Time"))
    occurred = aware(receipt["occurred_at"])
    if created <= baseline_at or occurred < go_live or created < go_live:
        raise ValueError("Form Lead predates protected baseline or enabled collector")
    if aware(lead.get("Modified_Time")) != created:
        raise ValueError("Form Lead has intervening provider edits")
    fields = receipt["fields"]
    name = str(fields.get("name") or "")
    if ", " not in name:
        raise ValueError("Form name cannot be bound exactly")
    first, last = name.split(", ", 1)
    if (str(lead.get("First_Name") or "").strip() != first
            or str(lead.get("Last_Name") or "").strip() != last
            or str(lead.get("Company") or "").strip() != str(fields.get("company") or "")
            or re.sub(r"\D", "", str(lead.get("Phone") or "")) !=
               re.sub(r"\D", "", str(fields.get("phone") or ""))):
        raise ValueError("Form and CRM identity are not exact")
    if receipt["test_only"] and not str(lead.get("Company") or "").startswith("OPTIBRAIN TEST — PHASE 9"):
        raise ValueError("Test-only marker is unproven")
    if not receipt["test_only"] and (lead.get("OptiBrain_Test") is True
                                      or "OPTIBRAIN TEST" in str(lead.get("Company") or "")):
        raise ValueError("Test identity is not authenticated by the receipt")
    timeline_id = _creation_proof(client, lead, occurred)
    if not timeline_id:
        raise ValueError("Zoho Forms creation event has no ID")
    expected = _expected(receipt, lead)
    for key, value in expected.items():
        current = lead.get(key)
        if current not in (None, "", False) and not _same(current, value):
            raise ValueError(f"CRM field {key} conflicts with exact form receipt")
    email = receipt["submitted_email"]
    for module in ("Leads", "Contacts"):
        for row in _inventory(client, module, "id,Email"):
            if (str(row.get("Email") or "").strip().casefold() == email
                    and str(row.get("id")) != lead_id):
                raise ValueError("Exact email already belongs to another CRM identity")
    return expected, timeline_id


def validate_form_request(method, path, body, headers, value):
    if os.environ.get("OPTIBRAIN_PHASE9_FORM_ENRICHMENT") != POLICY:
        raise ValueError("Form enrichment policy disabled")
    match = re.fullmatch(r"/crm/v8/Leads/([0-9]{1,30})", str(path))
    if method != "PUT" or not match or not isinstance(body, dict) or set(body) != {
            "data", "trigger", "skip_feature_execution"} or body["trigger"] != [] or body["skip_feature_execution"] != [{"name": "cadences"}]:
        raise ValueError("Form enrichment exceeds exact Lead PUT boundary")
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("Form enrichment requires one Lead")
    row = rows[0]
    if (row.get("id") != match[1] or len(row) < 2 or not set(row) <= NORMALIZED | {"id"}
            or set(headers or {}) != {"If-Unmodified-Since"}):
        raise ValueError("Form enrichment field or version boundary exceeded")
    aware(headers["If-Unmodified-Since"])
    protected, _ = protected_ids(value["baseline_path"])
    if match[1] in protected or match[1] != value["crm_id"]:
        raise ValueError("Form enrichment target is protected or changed")
    state = value["ledger"].enrichment_state(value["event_id"])
    if (not state or state["state"] != "ATTEMPTED" or state["crm_id"] != match[1]
            or state["payload_hash"] != value["hash"]):
        raise ValueError("No exact pre-transport enrichment journal")
    evidence = json.loads(state["evidence_json"])
    expected, patch = evidence.get("expected"), evidence.get("patch")
    if (not isinstance(expected, dict) or not isinstance(patch, dict)
            or row != {"id": match[1], **patch}
            or any(expected.get(key) != item for key, item in patch.items())
            or aware(headers["If-Unmodified-Since"]) != aware(evidence.get("source_version"))):
        raise ValueError("Form enrichment values differ from immutable receipt plan")


@contextmanager
def reviewed_form_call(client, ledger, event_id, crm_id, body, headers, *, baseline_path=BASELINE):
    path = f"/crm/v8/Leads/{crm_id}"
    value = {"client": client, "hash": fingerprint("PUT", path, body, headers),
             "policy": POLICY, "used": False, "ledger": ledger, "event_id": event_id,
             "crm_id": crm_id, "baseline_path": baseline_path}
    validate_form_request("PUT", path, body, headers, value)
    if _AUTHORITY.get() is not None:
        raise ValueError("Nested CRM authority forbidden")
    token = _AUTHORITY.set(value)
    try:
        yield
    finally:
        _AUTHORITY.reset(token)


def _record_test_intake(ledger, receipt, lead):
    if not receipt["test_only"]:
        return
    intake = IntakeLedger(ledger.path.parent / "phase9-intake.db")
    prior = intake.trace(str(lead["id"])) if intake.path.exists() else None
    if prior and any(event.get("inquiry_id") == receipt["event_id"] for event in prior["events"]):
        return
    evidence = {"form_id": receipt["form_id"], "provider_message_id": receipt["provider_message_id"],
                "internet_message_id": receipt["internet_message_id"], "raw_hash": receipt["raw_hash"]}
    result = intake.record({"source": "zoho_form", "inquiry_id": receipt["event_id"],
        "email": receipt["submitted_email"], "occurred_at": receipt["occurred_at"],
        "source_detail": receipt["source_detail"], "form_id": receipt["form_id"],
        "attribution": {}, "request": evidence, "crm_action": "form_created_lead"}, lead)
    intake.feedback(kind="LEAD_CREATED", canonical_id=str(lead["id"]),
        related_module="Leads", related_id=str(lead["id"]), occurred_at=receipt["occurred_at"],
        evidence={"intake_event": result["event_id"], "provider_message_id": receipt["provider_message_id"]})


def enrich_form_leads(client, ledger: FormReceiptLedger, *, go_live, baseline_path=BASELINE):
    """Reconcile first. Exactly one transport attempt per new form receipt."""
    if os.environ.get("OPTIBRAIN_PHASE9_FORM_ENRICHMENT") != POLICY:
        raise ValueError("Form enrichment is not enabled")
    start = aware(go_live)
    result = {"eligible": 0, "verified": 0, "attempted": 0, "review": 0}
    for receipt_row in ledger.list(100):
        if (receipt_row.get("quarantined") or aware(receipt_row["occurred_at"]) < start
                or not receipt_row["canonical_id"]):
            continue
        event = receipt_row["event_id"]
        state = ledger.enrichment_state(event)
        if state and state["state"] == "REVIEW":
            continue
        if state and state["state"] == "VERIFIED":
            if receipt_row["test_only"]:
                intake_path = ledger.path.parent / "phase9-intake.db"
                prior = IntakeLedger(intake_path).trace(str(receipt_row["canonical_id"])) if intake_path.exists() else None
                if not prior or not any(item.get("inquiry_id") == event for item in prior["events"]):
                    _record_test_intake(ledger, json.loads(receipt_row["evidence_json"]),
                        _one(client, f"/crm/v8/Leads/{receipt_row['canonical_id']}"))
            continue
        result["eligible"] += 1
        receipt = json.loads(receipt_row["evidence_json"])
        lead_id = str(receipt_row["canonical_id"])
        lead = _one(client, f"/crm/v8/Leads/{lead_id}")
        if str(lead.get("id")) != lead_id:
            raise ValueError("CRM Lead identity changed")
        if state and state["state"] == "ATTEMPTED":
            expected = json.loads(state["evidence_json"])["expected"]
            if all(_same(lead.get(key), value) for key, value in expected.items()):
                ledger.journal_enrichment(event, lead_id, "VERIFIED", state["payload_hash"],
                    {"resolution": "readback_after_attempt", "crm_version": lead.get("Modified_Time")})
                result["verified"] += 1
                _record_test_intake(ledger, receipt, lead)
            else:
                ledger.journal_enrichment(event, lead_id, "REVIEW", state["payload_hash"],
                    {"resolution": "ambiguous_after_attempt", "crm_version": lead.get("Modified_Time")})
                result["review"] += 1
            continue
        try:
            expected, timeline_id = _preflight(client, ledger, receipt, lead,
                go_live=start, baseline_path=baseline_path)
        except ValueError:
            result["review"] += 1
            continue
        patch = {key: value for key, value in expected.items() if not _same(lead.get(key), value)}
        body = {"data": [{"id": lead_id, **patch}], "trigger": [],
                "skip_feature_execution": [{"name": "cadences"}]}
        headers = {"If-Unmodified-Since": lead["Modified_Time"]}
        path = f"/crm/v8/Leads/{lead_id}"
        digest = fingerprint("PUT", path, body, headers)
        if patch:
            ledger.journal_enrichment(event, lead_id, "ATTEMPTED", digest,
                {"expected": expected, "patch": patch, "timeline_id": timeline_id,
                 "source_version": lead["Modified_Time"]})
            result["attempted"] += 1
            with reviewed_form_call(client, ledger, event, lead_id, body, headers,
                                    baseline_path=baseline_path):
                response = client.request("zohoapis", "PUT", path, body=body, headers=headers,
                    reason="Normalize exact newly created Zoho Forms Lead", confirm=True)
            rows = (response.get("data") or {}).get("data")
            if (response.get("ok") is not True or not isinstance(rows, list) or len(rows) != 1
                    or rows[0].get("status") != "success"
                    or str((rows[0].get("details") or {}).get("id")) != lead_id):
                raise ValueError("CRM form enrichment acknowledgement ambiguous; reconcile without retry")
            lead = _one(client, path)
        if not all(_same(lead.get(key), value) for key, value in expected.items()):
            raise ValueError("CRM form enrichment readback ambiguous; reconcile without retry")
        if patch:
            ledger.journal_enrichment(event, lead_id, "VERIFIED", digest,
                {"resolution": "provider_readback", "crm_version": lead.get("Modified_Time")})
        else:
            # Native Forms mapping already supplied every field; no transport needed.
            ledger.journal_enrichment(event, lead_id, "VERIFIED", digest,
                {"resolution": "native_mapping_readback", "crm_version": lead.get("Modified_Time")})
        result["verified"] += 1
        _record_test_intake(ledger, receipt, lead)
    return result
