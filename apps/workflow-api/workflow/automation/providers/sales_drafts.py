"""Opt-in Phase 6 drafts using the existing mail transport and durable journal.

Bodies and recipients exist only in memory. A started operation fences every
later version of its source until a human resolves an uncertain provider result.
"""
from __future__ import annotations

from datetime import datetime
import os
import re

from ...zoho_gateway import ZohoWriteUnconfirmedError
from ..desired_journal import DesiredJournal
from ..event_schema import digest
from ..events import EventLedger
from ..sales_decision import ACTIVE_STATUSES, POLICY_VERSION, validate_sales_decision
from .crm_leads import FIELDS, _utc_iso, records
from .mail_drafts import save_mail_draft


TEMPLATES = {
    "fr": ("Votre demande auprès d’Opticable",
           "Bonjour,\n\nMerci pour votre demande. Pourriez-vous préciser vos besoins, "
           "l’adresse du site et l’échéancier souhaité?\n\nL’équipe Opticable"),
    "en": ("Your inquiry with Opticable",
           "Hello,\n\nThank you for your inquiry. Could you share your requirements, "
           "the site address, and your preferred timeline?\n\nThe Opticable team"),
}
_ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")


def address(value):
    value = str(value or "").strip().lower()
    return value if len(value) <= 254 and _ADDRESS.fullmatch(value) else None


def register_sales_draft_action(engine, client, store):
    journal = DesiredJournal(store)

    def read_lead(identity):
        if not re.fullmatch(r"[0-9]{1,30}", identity):
            raise ValueError("Invalid reviewed Lead identity")
        rows = records(client.request("zohoapis", "GET", "/crm/v8/Leads/" + identity,
                                      query={"fields": FIELDS}))
        if len(rows) != 1 or str(rows[0].get("id")) != identity:
            raise ValueError("Reviewed Lead identity mismatch")
        return rows[0]

    def contact_gate(record, version):
        if _utc_iso(record.get("Modified_Time")) != version:
            return "superseded"
        if (record.get("Converted__s") is not False
                or record.get("Lead_Status") not in ACTIVE_STATUSES):
            return "inactive"
        # Missing/unknown consent fails closed for mail even if a decision was
        # constructed from an incomplete or advisory snapshot.
        if record.get("Email_Opt_Out") is not False:
            return "email_opt_out_or_unknown"
        if not address(record.get("Email")):
            return "no_recipient"
        return None

    def draft(context, step):
        if os.environ.get("OPTIBRAIN_SALES_DRAFTS") != POLICY_VERSION:
            return {"drafted": False, "reason": "observe"}
        event = context["event"]
        if event.get("source") != "crm-lead-observer" or event.get("event_type") != "opticable.crm.lead.reviewed":
            raise ValueError("Draft requires an internal reviewed Lead event")
        reviewed = event["payload"]
        identity = str(reviewed.get("lead_id") or "")
        version = _utc_iso(reviewed.get("version"))
        decision = validate_sales_decision(reviewed.get("sales_decision"))
        if decision.lead_id != identity or decision.version != version:
            raise ValueError("Draft decision identity/version mismatch")
        if (not decision.active or decision.converted or decision.email_opt_out
                or not decision.email_contactable or decision.next_action != "draft_reply"):
            return {"drafted": False, "reason": "decision_not_contactable"}
        if decision.language not in TEMPLATES:
            return {"drafted": False, "reason": "language_requires_review"}

        account = os.environ.get("OPTIBRAIN_SALES_DRAFT_ACCOUNT_ID", "")
        sender = address(os.environ.get("OPTIBRAIN_SALES_DRAFT_FROM"))
        if not re.fullmatch(r"[0-9]{1,30}", account) or not sender or sender.rsplit("@", 1)[1] != "opticable.ca":
            return {"drafted": False, "reason": "mailbox_requires_configuration"}

        with journal.lock():
            lead = read_lead(identity)
            refusal = contact_gate(lead, version)
            if refusal:
                return {"drafted": False, "reason": refusal}
            recipient = address(lead.get("Email"))
            # The connected CRM namespace is fixed by the provider client.
            # Notification metadata must not change the dedupe/ambiguity fence.
            source_identity = ["Leads", identity]
            source_version = version
            message_id = None
            reply_header = None
            # Optional inbound-message binding uses the immutable captured
            # source, not caller/AI recipient or body fields.
            if reviewed.get("message_event_id"):
                captured = EventLedger(store).inspect(str(reviewed["message_event_id"]))
                if not captured or captured["content_hash"] != reviewed.get("message_content_hash"):
                    raise ValueError("Reviewed message hash mismatch")
                envelope = captured["envelope"]
                email = envelope["payload"]
                if (envelope["source"] != "zoho-mail-poller"
                        or envelope["event_type"] != "customer.lifecycle.email.received"
                        or email.get("mailbox_account_id") != account
                        or address(email.get("mailbox_address")) != sender
                        or address(email.get("sender_email")) != recipient
                        or email.get("email_opt_out") not in (None, False)):
                    raise ValueError("Reviewed message does not match Lead/mailbox")
                message_id = str(email.get("message_id") or "")
                reply_header = str(email.get("internet_message_id") or "")
                if (not re.fullmatch(r"[0-9]{1,30}", message_id)
                        or not re.fullmatch(r"<[^<>\s]{1,250}@[^<>\s]{1,250}>", reply_header)):
                    return {"drafted": False, "reason": "message_identity_requires_review"}
                source_identity.extend([account, message_id])
                source_version = digest([version, captured["content_hash"]])
            if recipient.rsplit("@", 1)[1] in {"opticable.ca", "opti-plex.ca"}:
                return {"drafted": False, "reason": "internal_sender_loop_guard"}

            subject, content = TEMPLATES[decision.language]
            payload = {"mode": "draft", "fromAddress": sender, "toAddress": recipient,
                       "subject": subject, "content": content, "mailFormat": "plaintext"}
            if reply_header:
                payload["inReplyTo"] = reply_header
            content_hash = digest(payload)
            key = "sales-draft:" + digest(source_identity)
            evidence = {"policy": POLICY_VERSION, "lead_id": identity, "version": version,
                        "source_hash": digest(source_identity), "source_version": source_version,
                        "message_id": message_id, "account_id": account,
                        "content_hash": content_hash, "language": decision.language,
                        "draft_identity": digest([source_identity, source_version, content_hash])}
            if journal.unresolved(key):
                raise ZohoWriteUnconfirmedError("Previous draft outcome requires human reconciliation")
            previous = journal.last(key, ("verified",))
            if previous:
                prior = previous["metadata"]
                if datetime.fromisoformat(version) < datetime.fromisoformat(prior["version"]):
                    return {"drafted": False, "reason": "superseded"}
                if version == prior["version"]:
                    if evidence["draft_identity"] != prior["draft_identity"]:
                        raise ZohoWriteUnconfirmedError("Reviewed version already has different draft content")
                    return {"drafted": True, "deduplicated": True,
                            "draft_id": prior["draft_id"], "content_hash": prior["content_hash"]}
                evidence["supersedes_draft_id"] = prior["draft_id"]

            # Recheck just before the write; the Mail API cannot condition a
            # draft POST on a CRM version, so cross-provider atomicity is not
            # claimed. A detected change always cancels this operation.
            current = read_lead(identity)
            refusal = contact_gate(current, version)
            if refusal or address(current.get("Email")) != recipient:
                return {"drafted": False, "reason": refusal or "recipient_changed"}
            if os.environ.get("OPTIBRAIN_SALES_DRAFTS") != POLICY_VERSION:
                return {"drafted": False, "reason": "observe"}
            journal.record("started", key, evidence, "phase6-sales-draft")
            try:
                response = save_mail_draft(client, account, payload)
                outer = response.get("data") or {}
                data = outer.get("data") or {}
                draft_id = str(data.get("messageId") or "")
                if (response.get("ok") is not True or response.get("status") not in {200, 201}
                        or (outer.get("status") or {}).get("code") != 200
                        or not re.fullmatch(r"[0-9]{1,30}", draft_id)):
                    raise ZohoWriteUnconfirmedError("Mail draft response is unconfirmed")
            except Exception as exc:
                journal.record("manual", key, {**evidence, "error": type(exc).__name__}, "phase6-sales-draft")
                raise ZohoWriteUnconfirmedError("Mail draft outcome requires human reconciliation") from None
            journal.record("verified", key, {**evidence, "draft_id": draft_id}, "phase6-sales-draft")
            return {"drafted": True, "deduplicated": False, "draft_id": draft_id,
                    "content_hash": content_hash}

    engine.register_action("lifecycle.sales_draft", draft)  # Never retry a mail write.
