"""Pure, fail-closed operational email plans; this module has no transport.

The root runner supplies freshly and independently read association/suppression
proof. A READY plan is a proposal, never send authority. The central boundary
must still require its exact scoped policy, immutable intent and off-host claim,
then re-read eligibility immediately before transport. Unknown outcomes permit
provider reconciliation only. No journal entry alone proves provider delivery.

``proof`` binds Contact/Account/Deal/Site native relationships and versions.
``context`` binds the same IDs, a native trigger/version, and fresh suppression
observations. ``history`` contains immutable, independently verified provider
effects (family, object_id, effect_key, status, sent_at, provider_message_id).
All timestamps are aware ISO-8601. All functions require an explicit clock.
Weekday cadence excludes weekends; holidays are not inferred by this planner.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
FRESH_FOR = timedelta(minutes=5)
FAMILIES = frozenset({"customer.quote.reminder", "customer.appointment.confirmation",
    "customer.appointment.reminder", "customer.completion.message"})
LANGUAGE_SOURCES = frozenset({"crm_preference", "native_finance", "intake_language", "owner_selection"})
CONTROLLED_RECIPIENTS = frozenset({"yboucher@opticable.ca"})
STOP_FLAGS = ("replied", "manual_suppression", "delivery_failure", "unsubscribed", "superseded")
UNCERTAIN = frozenset({"attempted", "provider_ack", "uncertain", "failed"})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def aware(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    return result


def normalize_recipient(value):
    """One plain address only: no display names, lists, headers or aliases guessed."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("One exact recipient address required")
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", value):
        raise ValueError("Invalid or multiple recipient addresses")
    local, domain = value.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Invalid recipient local part")
    return value.lower()


def business_days_after(start, days):
    """Toronto wall-clock cadence, preserving time across DST and weekends."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ValueError("Nonnegative whole business-day interval required")
    result = aware(start).astimezone(TORONTO)
    while days:
        result += timedelta(days=1)
        if result.weekday() < 5:
            days -= 1
    return result


def _result(family, state, reason, **extra):
    return {"family": family, "state": state, "reason": reason,
            "send_authority": False, **extra}


def _fresh(value, now):
    try:
        age = aware(now) - aware(value)
        return timedelta(0) <= age <= FRESH_FOR
    except (TypeError, ValueError):
        return False


def _ids_equal(a, b):
    return bool(a is not None and b is not None and str(a) and str(a) == str(b))


def _proof(context, proof, now):
    """Check shape/consistency; authenticity is the root runner's responsibility."""
    if proof.get("mode") not in {"TEST_ONLY", "REAL_NEW"} or proof.get("lineage_verified") is not True or proof.get("protected") is not False:
        return "Root ownership and protected-record proof required"
    if not _fresh(proof.get("observed_at"), now) or not _fresh(context.get("observed_at"), now):
        return "Fresh independent provider observations required"
    if not all(proof.get(k) for k in ("contact_version", "deal_version", "site_version")):
        return "Native provider versions required"
    for key in ("contact_id", "account_id", "deal_id", "site_id"):
        if not _ids_equal(context.get(key), proof.get(key)):
            return "Recipient/customer/site association disagrees"
    for key, expected in (("contact_account_id", "account_id"), ("deal_account_id", "account_id"),
                          ("deal_contact_id", "contact_id"), ("deal_site_id", "site_id"),
                          ("site_account_id", "account_id")):
        if not _ids_equal(proof.get(key), proof.get(expected)):
            return "Native Contact/Deal/Account/Service Location relationships disagree"
    try:
        recipient = normalize_recipient(context.get("recipient_email"))
        if recipient != normalize_recipient(proof.get("contact_email")):
            return "Recipient differs from independently read CRM Contact"
    except ValueError:
        return "Invalid recipient; human correction required"
    if proof.get("mode") == "TEST_ONLY":
        if not proof.get("test_run") or recipient not in CONTROLLED_RECIPIENTS:
            return "Controlled recipient and deterministic TEST ownership required"
    elif recipient in CONTROLLED_RECIPIENTS or recipient.endswith(("@example.com", "@example.net", "@example.org", ".invalid")):
        return "TEST or synthetic recipient is ineligible for real communications"
    if proof.get("language") not in {"fr", "en"} or proof.get("language_source") not in LANGUAGE_SOURCES:
        return "Explicit French/English preference required; never infer from name"
    if proof.get("opt_out") is not False:
        return "Contact communication preference is suppressed or unknown"
    if not _fresh(context.get("suppression_checked_at"), now):
        return "Fresh reply/delivery/suppression observation required"
    if any(context.get(flag) is None or not isinstance(context.get(flag), bool) for flag in STOP_FLAGS):
        return "Reply/delivery/suppression state is unknown"
    return None


def _gate(family, context, proof, now, enabled):
    aware(now)
    if enabled is not True:
        return _result(family, "SUPPRESSED", "Automatic customer communications are stopped")
    error = _proof(context, proof, now)
    if error:
        return _result(family, "HUMAN", error)
    if any(context[flag] for flag in STOP_FLAGS):
        return _result(family, "SUPPRESSED", "Customer reply, delivery issue, opt-out, owner suppression or superseded work")
    return None


def _history(family, identity, history):
    return [row for row in history if row.get("family") == family and _ids_equal(row.get("object_id"), identity)]


def _history_gate(family, rows):
    if any(row.get("status") in UNCERTAIN for row in rows):
        return _result(family, "RECONCILE", "Existing provider attempt has an uncertain outcome; never resend")
    if any(row.get("status") not in {"verified", "not_attempted", "suppressed"} for row in rows):
        return _result(family, "RECONCILE", "Unknown effect evidence requires independent provider reconciliation")
    verified = [row for row in rows if row.get("status") == "verified"]
    if any(not row.get("provider_message_id") or not row.get("effect_key") or not row.get("sent_at") for row in verified):
        return _result(family, "RECONCILE", "Provider verification is incomplete")
    keys = [row["effect_key"] for row in verified]
    if len(keys) != len(set(keys)):
        return _result(family, "RECONCILE", "Multiple verified effects for one key require investigation")
    return None


def _text(value, limit=160):
    result = str(value or "").strip()
    if not result or len(result) > limit or any(ord(c) < 32 for c in result):
        raise ValueError("Safe, concise native display value required")
    return result


def _ready(family, context, proof, key, subject, body, **extra):
    recipient = normalize_recipient(context["recipient_email"])
    if proof["mode"] == "TEST_ONLY":
        subject = "[OPTIBRAIN TEST] " + subject
    elif any(marker in (subject + body).upper() for marker in ("OPTIBRAIN TEST", "TEST ONLY", "TEST_ONLY", "[OPTIBRAIN TEST]")):
        return _result(family, "HUMAN", "Synthetic display context cannot enter a real customer message")
    content = {"recipient": recipient, "subject": subject, "body": body}
    return _result(family, "READY", "Eligibility and independent association proof passed",
        effect_key=key, idempotency_key=key, object_id=str(context["object_id"]),
        business_key=str(context["object_id"]), version=extra.get("schedule_version", str(extra.get("sequence", 1))),
        ordinal=extra.get("sequence", 1), recipient=recipient,
        subject=subject, body=body, plaintext=body, content=body,
        language=proof["language"], mode=proof["mode"],
        content_hash=digest(content), cc=[], bcc=[],
        expected_native_bindings={key: str(proof[key]) for key in ("contact_id", "account_id", "deal_id", "site_id")},
        proof_hash=digest(proof), trigger_hash=digest(context), **extra)


def plan_quote_reminder(context, proof, history, now, *, communications_enabled=False):
    family = "customer.quote.reminder"
    stopped = _gate(family, context, proof, now, communications_enabled)
    if stopped:
        return stopped
    equivalent = (proof.get("mode") == "TEST_ONLY"
                  and context.get("source_kind") == "TEST_STATUS_EQUIVALENT"
                  and context.get("status_equivalent_fixture") is True)
    native = context.get("finance_integrated") is True
    if proof.get("mode") == "REAL_NEW" and (context.get("source_kind") == "TEST_STATUS_EQUIVALENT"
            or context.get("native_books_verified") is not True
            or context.get("native_crm_finance_verified") is not True):
        return _result(family, "HUMAN", "Independent native Books and CRM Finance proof required for a real Estimate")
    if not (native or equivalent) or not context.get("estimate_id"):
        return _result(family, "HUMAN", "Native Finance Estimate proof required; CRM Quotes are ineligible")
    for field, expected in (("finance_account_id", "account_id"), ("finance_deal_id", "deal_id"), ("finance_site_id", "site_id")):
        if not _ids_equal(context.get(field), proof.get(expected)):
            return _result(family, "HUMAN", "Finance Estimate/customer/Deal/site relationship disagrees")
    if context.get("status") not in {"sent", "viewed"} or context.get("deal_active") is not True:
        return _result(family, "SUPPRESSED", "Estimate is not sent/active, or Deal is closed")
    identity = str(context["estimate_id"])
    if not _ids_equal(context.get("object_id"), identity):
        return _result(family, "HUMAN", "Estimate trigger identity disagrees")
    try:
        sent = aware(context["sent_at"])
        if sent > aware(now):
            return _result(family, "HUMAN", "Estimate sent timestamp is in the future")
        expiry = context.get("expiry_date")
        if expiry and datetime.fromisoformat(str(expiry)[:10]).date() < aware(now).astimezone(TORONTO).date():
            return _result(family, "SUPPRESSED", "Estimate has expired")
        number = _text(context.get("estimate_number"), 60)
    except (KeyError, TypeError, ValueError):
        return _result(family, "HUMAN", "Native sent timestamp/Estimate number/expiry is missing or invalid")
    rows = _history(family, identity, history)
    stopped = _history_gate(family, rows)
    if stopped:
        return stopped
    verified = [r for r in rows if r.get("status") == "verified"]
    sequences = {r.get("sequence") for r in verified}
    if len(verified) >= 2:
        return _result(family, "HUMAN", "Two reminders completed; further follow-up belongs to the owner")
    if sequences - {1}:
        return _result(family, "RECONCILE", "Reminder sequence evidence conflicts")
    sequence = 2 if verified else 1
    due = business_days_after(sent, 3)
    if sequence == 2:
        try:
            due = max(business_days_after(sent, 8), business_days_after(verified[0]["sent_at"], 5))
        except (TypeError, ValueError):
            return _result(family, "RECONCILE", "First reminder timestamp is invalid")
    if aware(now) < due:
        return _result(family, "WAIT", "Reminder cadence is not due", due_at=due.isoformat(), sequence=sequence)
    key = family + ":" + identity + ":" + str(sequence)
    if proof["language"] == "fr":
        subject = ("Dernier suivi de la soumission " if sequence == 2 else "Suivi de la soumission ") + number
        body = ("Bonjour,\n\nNous faisons un " + ("dernier " if sequence == 2 else "") + "suivi de notre soumission " + number +
                ". Si vous avez des questions ou souhaitez poursuivre, répondez à ce courriel.\n\nMerci,\nL’équipe Opticable")
    else:
        subject = ("Final follow-up on estimate " if sequence == 2 else "Follow-up on estimate ") + number
        body = ("Hello,\n\nWe’re " + ("making a final follow-up " if sequence == 2 else "following up ") + "on estimate " + number +
                ". If you have questions or would like to proceed, please reply to this email.\n\nThank you,\nThe Opticable team")
    return _ready(family, context, proof, key, subject, body, sequence=sequence, due_at=due.isoformat(),
                  finance_basis="TEST_STATUS_EQUIVALENT" if equivalent else "NATIVE_FINANCE")


def schedule_fingerprint(context):
    """A schedule version includes logistics, never a guessed date or technician."""
    if context.get("timezone") != "America/Toronto":
        raise ValueError("Explicit America/Toronto timezone required")
    scheduled = aware(context.get("scheduled_at"))
    local = scheduled.astimezone(TORONTO)
    # Reject fixed offsets inconsistent with Toronto, including invalid DST wall times.
    if scheduled.utcoffset() != local.utcoffset() or scheduled.replace(tzinfo=None) != local.replace(tzinfo=None):
        raise ValueError("Native scheduled date/time offset disagrees with America/Toronto")
    site = _text(context.get("site_display"))
    if context.get("technician_required") is True and not context.get("technician_id"):
        raise ValueError("Human technician assignment required")
    return digest({"installation_id": str(context.get("installation_id") or ""),
        "at_utc": scheduled.astimezone(timezone.utc).isoformat(), "timezone": "America/Toronto",
        "site_id": str(context.get("site_id") or ""), "site_display": site,
        "contact_id": str(context.get("contact_id") or ""),
        "technician_id": str(context.get("technician_id") or ""),
        "human_schedule_evidence": context.get("human_schedule_evidence"),
        "access_instructions": str(context.get("access_instructions") or "")})


def _schedule_gate(family, context, proof, now, enabled):
    stopped = _gate(family, context, proof, now, enabled)
    if stopped:
        return stopped
    if context.get("installation_status") != "Scheduled" or context.get("cancelled") is not False:
        return _result(family, "SUPPRESSED", "Installation is not scheduled or is cancelled")
    if context.get("human_schedule_confirmed") is not True or not context.get("human_schedule_evidence"):
        return _result(family, "HUMAN", "Native human scheduling transition evidence required")
    for field, expected in (("installation_account_id", "account_id"), ("installation_deal_id", "deal_id"),
                            ("installation_site_id", "site_id"), ("installation_contact_id", "contact_id")):
        if not _ids_equal(context.get(field), proof.get(expected)):
            return _result(family, "HUMAN", "Installation/customer/Deal/site/contact relationship disagrees")
    if not context.get("installation_id") or not _ids_equal(context.get("object_id"), context["installation_id"]):
        return _result(family, "HUMAN", "Installation trigger identity disagrees")
    try:
        version = schedule_fingerprint(context)
        scheduled = aware(context["scheduled_at"])
    except (TypeError, ValueError):
        return _result(family, "HUMAN", "Complete, valid human schedule in America/Toronto is required")
    if scheduled <= aware(now):
        return _result(family, "SUPPRESSED", "Appointment is no longer in the future")
    return version


def _appointment_body(context, language, *, updated=False, reminder=False):
    local = aware(context["scheduled_at"]).astimezone(TORONTO)
    # Numeric date is unambiguous and independent of the host locale.
    when = local.strftime("%Y-%m-%d à %H:%M" if language == "fr" else "%Y-%m-%d at %H:%M")
    zone = "heure de Toronto" if language == "fr" else "Toronto time"
    site = _text(context["site_display"])
    if language == "fr":
        subject = "Rappel de rendez-vous" if reminder else ("Rendez-vous mis à jour" if updated else "Confirmation de rendez-vous")
        body = f"Bonjour,\n\nNotre visite est prévue le {when} ({zone}) à {site}. Si l’accès au site a changé, répondez à ce courriel.\n\nMerci,\nL’équipe Opticable"
    else:
        subject = "Appointment reminder" if reminder else ("Updated appointment" if updated else "Appointment confirmation")
        body = f"Hello,\n\nOur visit is scheduled for {when} ({zone}) at {site}. If site access has changed, please reply to this email.\n\nThank you,\nThe Opticable team"
    return subject, body


def plan_appointment_confirmation(context, proof, history, now, *, communications_enabled=False):
    family = "customer.appointment.confirmation"
    version = _schedule_gate(family, context, proof, now, communications_enabled)
    if isinstance(version, dict):
        return version
    rows = _history(family, context["installation_id"], history)
    stopped = _history_gate(family, rows)
    if stopped:
        return stopped
    key = family + ":" + str(context["installation_id"]) + ":" + version
    if any(r.get("effect_key") == key for r in rows if r.get("status") == "verified"):
        return _result(family, "SUPPRESSED", "Confirmation already sent for this exact schedule version")
    updated = any(r.get("status") == "verified" for r in rows)
    subject, body = _appointment_body(context, proof["language"], updated=updated)
    return _ready(family, context, proof, key, subject, body, schedule_version=version, updated=updated)


def plan_appointment_reminder(context, proof, history, now, *, communications_enabled=False):
    family = "customer.appointment.reminder"
    version = _schedule_gate(family, context, proof, now, communications_enabled)
    if isinstance(version, dict):
        return version
    confirmations = _history("customer.appointment.confirmation", context["installation_id"], history)
    stopped = _history_gate(family, confirmations)
    if stopped:
        return stopped
    confirmation_key = "customer.appointment.confirmation:" + str(context["installation_id"]) + ":" + version
    if not any(r.get("status") == "verified" and r.get("effect_key") == confirmation_key for r in confirmations):
        return _result(family, "HUMAN", "Current schedule confirmation has not been independently verified")
    rows = _history(family, context["installation_id"], history)
    stopped = _history_gate(family, rows)
    if stopped:
        return stopped
    key = family + ":" + str(context["installation_id"]) + ":" + version
    if any(r.get("status") == "verified" and r.get("effect_key") == key for r in rows):
        return _result(family, "SUPPRESSED", "One reminder already sent for this schedule version")
    due = aware(context["scheduled_at"]).astimezone(timezone.utc) - timedelta(hours=24)
    if aware(now) < due:
        return _result(family, "WAIT", "Appointment reminder is not due", due_at=due.isoformat())
    subject, body = _appointment_body(context, proof["language"], reminder=True)
    return _ready(family, context, proof, key, subject, body, schedule_version=version, due_at=due.isoformat())


def plan_completion_message(context, proof, history, now, *, communications_enabled=False):
    family = "customer.completion.message"
    stopped = _gate(family, context, proof, now, communications_enabled)
    if stopped:
        return stopped
    if context.get("installation_status") != "Completed" or context.get("return_visit_required") is not False:
        return _result(family, "SUPPRESSED", "Work is not complete or a return visit remains")
    if context.get("human_completion_confirmed") is not True or not context.get("human_completion_evidence"):
        return _result(family, "HUMAN", "Native human completion transition evidence required")
    for field, expected in (("installation_account_id", "account_id"), ("installation_deal_id", "deal_id"),
                            ("installation_site_id", "site_id"), ("installation_contact_id", "contact_id")):
        if not _ids_equal(context.get(field), proof.get(expected)):
            return _result(family, "HUMAN", "Completed work/customer/Deal/site/contact relationship disagrees")
    identity = context.get("installation_id")
    if not identity or not _ids_equal(context.get("object_id"), identity):
        return _result(family, "HUMAN", "Completion trigger identity disagrees")
    try:
        if aware(context.get("completed_at")) > aware(now):
            return _result(family, "HUMAN", "Completion timestamp is in the future")
        site = _text(context.get("site_display"))
    except (TypeError, ValueError):
        return _result(family, "HUMAN", "Native completion timestamp and site display are required")
    rows = _history(family, identity, history)
    stopped = _history_gate(family, rows)
    if stopped:
        return stopped
    key = family + ":" + str(identity)
    if any(r.get("status") == "verified" for r in rows):
        return _result(family, "SUPPRESSED", "Completion message already sent for this visit")
    if proof["language"] == "fr":
        subject = "Travaux terminés"
        body = f"Bonjour,\n\nNotre visite à {site} est terminée. Merci de votre confiance. Si vous avez une question concernant les travaux, répondez à ce courriel.\n\nL’équipe Opticable"
    else:
        subject = "Work completed"
        body = f"Hello,\n\nOur visit at {site} is complete. Thank you for choosing Opticable. If you have a question about the work, please reply to this email.\n\nThe Opticable team"
    return _ready(family, context, proof, key, subject, body)


def reconcile_delivery(plan, messages):
    """Full native Sent-message reads, from the authorized account, not a journal.

    Each message requires id, outgoing=True, one ``to`` address, no cc/bcc,
    exact subject and full plain body. Caller must constrain retrieval to the
    effect's account/time/thread and normalize provider HTML to exact plain text.
    A zero match remains UNKNOWN, never permission to resend a prior attempt.
    """
    if plan.get("state") != "READY" or not plan.get("content_hash"):
        raise ValueError("Exact immutable communication plan required")
    expected = digest({"recipient": normalize_recipient(plan["recipient"]),
                       "subject": plan["subject"], "body": plan["body"]})
    if expected != plan["content_hash"]:
        raise ValueError("Communication content changed")
    matches = []
    for message in messages:
        if message.get("outgoing") is not True or not message.get("id") or message.get("cc") or message.get("bcc"):
            continue
        recipients = message.get("to")
        if not isinstance(recipients, list) or len(recipients) != 1:
            continue
        try:
            actual = digest({"recipient": normalize_recipient(recipients[0]),
                             "subject": message["subject"], "body": message["body"]})
        except (KeyError, TypeError, ValueError):
            continue
        if actual == expected:
            matches.append(str(message["id"]))
    matches = sorted(set(matches))
    if len(matches) == 1:
        return {"state": "VERIFIED", "provider_message_id": matches[0], "effect_key": plan["effect_key"], "content_hash": expected}
    return {"state": "DUPLICATE" if matches else "UNKNOWN", "provider_message_ids": matches,
            "resend_allowed": False, "effect_key": plan["effect_key"]}
