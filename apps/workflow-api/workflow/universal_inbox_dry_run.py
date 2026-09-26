from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

LEGACY_DOMAIN = "opti-plex.ca"
OPTICABLE_SENDERS = {
    "yboucher@opticable.ca", "quotes@opticable.ca", "soumissions@opticable.ca",
    "support@opticable.ca", "installations@opticable.ca", "admin@opticable.ca",
    "partners@opticable.ca", "factures@opticable.ca", "facturation@opticable.ca",
    "info@opticable.ca", "ventes@opticable.ca", "logs@opticable.ca", "noreply@opticable.ca",
}

@dataclass(frozen=True)
class DryRunDecision:
    category: str
    confidence: float
    proposed_folder: str | None
    business_object: str | None
    next_action: str | None
    priority: str
    waiting_on: str | None
    migration_candidate: bool
    migration_target: str | None
    books_write: bool = False
    mutate_mail: bool = False
    mutate_crm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(message: dict[str, Any]) -> str:
    return " ".join(str(message.get(key) or "") for key in ("fromAddress", "toAddress", "ccAddress", "subject", "summary", "content")).lower()


def _recipient(message: dict[str, Any]) -> str:
    return str(message.get("toAddress") or "").lower()


def _sender(message: dict[str, Any]) -> str:
    return str(message.get("fromAddress") or "").lower().strip()


def _legacy_recipient(message: dict[str, Any]) -> bool:
    return LEGACY_DOMAIN in _recipient(message)


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _no_action(category: str, confidence: float = 0.99) -> DryRunDecision:
    return DryRunDecision(category, confidence, None, None, None, "low", None, False, None)


def classify_message(message: dict[str, Any]) -> DryRunDecision:
    """Return a proposal only. This function performs no network calls or mutations."""
    text, sender, recipient = _text(message), _sender(message), _recipient(message)
    legacy = _legacy_recipient(message)

    if "@hoplajeux.ca" in sender or "@hoplajeux.ca" in recipient:
        return _no_action("other_business_hopla_jeux")

    if sender in OPTICABLE_SENDERS:
        return _no_action("outbound_opticable_message")

    if sender == "support@fieldnation.com" or "fieldnation.com/workorders/" in text:
        urgent = _has_any(text, ("hard down", "asap", "dispatch request", "routed wo:"))
        return DryRunDecision("partner_job", 0.99, "/Opticable/Partners/Partner Jobs", "partner_work_opportunity", "Review partner work order and accept/decline based on schedule, scope, distance and rate", "urgent" if urgent else "high", "opticable", False, None)

    invoice_terms = ("invoice", "facture", "receipt", "reçu", "payment received", "paid ", "tax invoice")
    supplier_fingerprints = ("infinitecables.com", "phantomcables.com", "ovhcloud.com", "hyperline.co", "freightcom.com", "vistaprint", "zohocorp.com", "guillevin.com", "paypal.com", "homedepot.com", "duroequipement.com", "anthropic.com")
    if _has_any(text, invoice_terms) and _has_any(text, supplier_fingerprints):
        return DryRunDecision("supplier_invoice_or_receipt", 0.96, "/Business Records/Bills and Receipts/Supplier Invoices", "supplier_invoice_observation", None, "normal", None, legacy, "factures@opticable.ca" if legacy else None, books_write=False)

    if _has_any(text, ("mfa", "verification code", "verify your device", "2-step", "authentication", "clicséqur")):
        return DryRunDecision("security_authentication", 0.95, "/Systems/Security", "security_event", "Review immediately if the authentication event was not expected", "high", "opticable", legacy, "admin@opticable.ca" if legacy else None)

    if _has_any(text, ("run failed:", "all jobs have failed", "workflow run", "github actions")) and "github" in sender:
        return DryRunDecision("automation_failure", 0.98, "/Systems/Deployments", "system_incident", "Inspect the failed workflow and determine whether production or automation is affected", "high", "opticable", False, None)

    if _has_any(text, ("undelivered mail", "delivery status notification", "could not be delivered", "permanent failure")):
        return DryRunDecision("outbound_delivery_failure", 0.98, "/Opticable/Leads and Quotes", "crm_data_quality_task", "Verify recipient email/contact details and decide whether to retry through another channel", "high", "opticable", False, None)

    partner_terms = ("subcontract", "subcontractor", "partnership opportunity", "service coordinator", "work opportunity", "dispatch request")
    if "partners@opticable.ca" in recipient or _has_any(text, partner_terms):
        return DryRunDecision("partner_opportunity", 0.94, "/Opticable/Partners/Partner Jobs", "partner_work_opportunity", "Review partner relationship or work opportunity and set next response/action", "high", "opticable", False, None)

    support_terms = ("en trouble", "ne fonctionne", "not working", "offline", "débarrer", "reconnecter", "problem", "issue")
    if "support@opticable.ca" in recipient or _has_any(text, support_terms):
        return DryRunDecision("customer_support", 0.86 if "support@opticable.ca" not in recipient else 0.97, "/Opticable/Support and Service", "support_case_or_service", "Identify customer and service location, then create or link the service/support action", "high" if _has_any(text, ("offline", "en trouble", "not working")) else "normal", "opticable", legacy, "support@opticable.ca" if legacy else None)

    installation_terms = ("installation", "scheduled", "schedule", "accès", "access", "plans", "plan électrique", "cabling", "câblage", "finition")
    if "installations@opticable.ca" in recipient or _has_any(text, installation_terms):
        return DryRunDecision("project_or_installation", 0.80 if "installations@opticable.ca" not in recipient else 0.97, "/Opticable/Clients and Projects", "service_or_installation", "Link to active project/site and extract scheduling, access, scope or material changes", "normal", "opticable", legacy, "installations@opticable.ca" if legacy else None)

    if "quotes@opticable.ca" in recipient or "soumissions@opticable.ca" in recipient:
        won_terms = ("bon de commande", "purchase order", "po attached", "go ahead", "approved", "accepté", "accepted")
        vendor_terms = ("demo", "our software", "our platform", "partnership", "subcontract", "service coordinator")
        if _has_any(text, vendor_terms):
            return DryRunDecision("vendor_or_partner_inquiry", 0.88, "/Opticable/Admin and Providers", "provider_or_partner_inquiry", "Review vendor/partner proposition; do not create a sales lead automatically", "low", "opticable", False, None)
        if _has_any(text, won_terms):
            return DryRunDecision("won_work_or_project_handoff", 0.94, "/Opticable/Clients and Projects", "deal_to_service_handoff", "Confirm scope and create/link Service or Installation scheduling action", "high", "opticable", False, None)
        return DryRunDecision("direct_quote_or_lead", 0.96, "/Opticable/Leads and Quotes", "lead_or_deal", "Identify/deduplicate lead or deal, classify service need, and set the next sales action", "normal", "opticable", False, None)

    provider_terms = ("account", "subscription", "usage limits", "order", "shipment", "delivery", "portal", "renewal")
    if "admin@opticable.ca" in recipient or _has_any(text, provider_terms):
        migration = legacy and _has_any(sender, ("ui.com", "github.com", "cloudflare", "adiglobal", "zohocorp", "amazon", "ovh"))
        return DryRunDecision("admin_provider", 0.83 if "admin@opticable.ca" not in recipient else 0.95, "/Opticable/Admin and Providers", "provider_account_or_admin_record", "Review only if the message changes access, billing, service status, renewal or account configuration", "normal", None, migration, "admin@opticable.ca" if migration else None)

    if legacy:
        human_sender = sender and not _has_any(sender, ("noreply", "no-reply", "do-not-reply", "donotreply", "notification", "notifications", "service@intl.paypal"))
        return DryRunDecision("legacy_address_review", 0.70, "/Business Records/Legacy Opti-Plex Migration", "provider_migration_candidate" if not human_sender else "legacy_correspondence_review", "Determine whether this sender/account should be migrated to an Opticable address", "low", "opticable", not human_sender, "admin@opticable.ca" if not human_sender else None)

    return _no_action("unclassified", 0.35)


def classify_batch(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        key = str(message.get("threadId") or message.get("messageId") or "") + "|" + _sender(message) + "|" + str(message.get("subject") or "")
        if key in seen:
            continue
        seen.add(key)
        decision = classify_message(message).to_dict()
        decision.update({"messageId": message.get("messageId"), "subject": message.get("subject"), "fromAddress": message.get("fromAddress"), "toAddress": message.get("toAddress")})
        results.append(decision)
    return results
