from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


LEGACY_DOMAIN = "opti-plex.ca"


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
    return " ".join(
        str(message.get(key) or "")
        for key in ("fromAddress", "toAddress", "ccAddress", "subject", "summary", "content")
    ).lower()


def _recipient(message: dict[str, Any]) -> str:
    return str(message.get("toAddress") or "").lower()


def _sender(message: dict[str, Any]) -> str:
    return str(message.get("fromAddress") or "").lower().strip()


def _legacy_recipient(message: dict[str, Any]) -> bool:
    return LEGACY_DOMAIN in _recipient(message)


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def classify_message(message: dict[str, Any]) -> DryRunDecision:
    """Return a proposal only. This function performs no network calls or mutations."""
    text = _text(message)
    sender = _sender(message)
    recipient = _recipient(message)
    legacy = _legacy_recipient(message)

    # Explicit platform work-order fingerprints are more reliable than mailbox alias.
    if sender == "support@fieldnation.com" or "fieldnation.com/workorders/" in text:
        urgent = _has_any(text, ("hard down", "asap", "dispatch request", "routed wo:"))
        return DryRunDecision(
            category="partner_job",
            confidence=0.99,
            proposed_folder="/Opticable/Partners/Partner Jobs",
            business_object="partner_work_opportunity",
            next_action="Review partner work order and accept/decline based on schedule, scope, distance and rate",
            priority="urgent" if urgent else "high",
            waiting_on="opticable",
            migration_candidate=False,
            migration_target=None,
        )

    invoice_terms = ("invoice", "facture", "receipt", "reçu", "payment received", "paid ", "tax invoice")
    supplier_fingerprints = (
        "infinitecables.com", "phantomcables.com", "ovhcloud.com", "hyperline.co",
        "freightcom.com", "vistaprint", "zohocorp.com", "guillevin.com",
        "paypal.com", "homedepot.com", "duroequipement.com",
    )
    if _has_any(text, invoice_terms) and _has_any(text, supplier_fingerprints):
        return DryRunDecision(
            category="supplier_invoice_or_receipt",
            confidence=0.96,
            proposed_folder="/Business Records/Bills and Receipts/Supplier Invoices",
            business_object="supplier_invoice_observation",
            next_action=None,
            priority="normal",
            waiting_on=None,
            migration_candidate=legacy,
            migration_target="factures@opticable.ca" if legacy else None,
            books_write=False,
        )

    if _has_any(text, ("mfa", "verification code", "verify your device", "2-step", "authentication", "clicséqur")):
        return DryRunDecision(
            category="security_authentication",
            confidence=0.95,
            proposed_folder="/Systems/Security",
            business_object="security_event",
            next_action="Review immediately if the authentication event was not expected",
            priority="high",
            waiting_on="opticable",
            migration_candidate=legacy,
            migration_target="admin@opticable.ca" if legacy else None,
        )

    if _has_any(text, ("undelivered mail", "delivery status notification", "could not be delivered", "permanent failure")):
        return DryRunDecision(
            category="outbound_delivery_failure",
            confidence=0.98,
            proposed_folder="/Opticable/Leads and Quotes",
            business_object="crm_data_quality_task",
            next_action="Verify recipient email/contact details and decide whether to retry through another channel",
            priority="high",
            waiting_on="opticable",
            migration_candidate=False,
            migration_target=None,
        )

    support_terms = ("en trouble", "ne fonctionne", "not working", "offline", "support", "débarrer", "reconnecter", "problem", "issue")
    if "support@opticable.ca" in recipient or _has_any(text, support_terms):
        return DryRunDecision(
            category="customer_support",
            confidence=0.86 if "support@opticable.ca" not in recipient else 0.97,
            proposed_folder="/Opticable/Support and Service",
            business_object="support_case_or_service",
            next_action="Identify customer and service location, then create or link the service/support action",
            priority="high" if _has_any(text, ("offline", "en trouble", "not working")) else "normal",
            waiting_on="opticable",
            migration_candidate=legacy,
            migration_target="support@opticable.ca" if legacy else None,
        )

    installation_terms = ("installation", "scheduled", "schedule", "accès", "access", "plans", "plan électrique", "cabling", "câblage", "finition")
    if "installations@opticable.ca" in recipient or _has_any(text, installation_terms):
        return DryRunDecision(
            category="project_or_installation",
            confidence=0.80 if "installations@opticable.ca" not in recipient else 0.97,
            proposed_folder="/Opticable/Clients and Projects",
            business_object="service_or_installation",
            next_action="Link to active project/site and extract scheduling, access, scope or material changes",
            priority="normal",
            waiting_on="opticable",
            migration_candidate=legacy,
            migration_target="installations@opticable.ca" if legacy else None,
        )

    if "quotes@opticable.ca" in recipient or "soumissions@opticable.ca" in recipient:
        won_terms = ("bon de commande", "purchase order", "po attached", "go ahead", "approved", "accepté", "accepted")
        if _has_any(text, won_terms):
            return DryRunDecision(
                category="won_work_or_project_handoff",
                confidence=0.94,
                proposed_folder="/Opticable/Clients and Projects",
                business_object="deal_to_service_handoff",
                next_action="Confirm scope and create/link Service or Installation scheduling action",
                priority="high",
                waiting_on="opticable",
                migration_candidate=False,
                migration_target=None,
            )
        return DryRunDecision(
            category="direct_quote_or_lead",
            confidence=0.96,
            proposed_folder="/Opticable/Leads and Quotes",
            business_object="lead_or_deal",
            next_action="Identify/deduplicate lead or deal, classify service need, and set the next sales action",
            priority="normal",
            waiting_on="opticable",
            migration_candidate=False,
            migration_target=None,
        )

    provider_terms = ("account", "subscription", "usage limits", "order", "shipment", "delivery", "portal", "renewal")
    if "admin@opticable.ca" in recipient or _has_any(text, provider_terms):
        migration = legacy and _has_any(sender, ("ui.com", "github.com", "cloudflare", "adiglobal", "zohocorp", "amazon", "ovh"))
        return DryRunDecision(
            category="admin_provider",
            confidence=0.83 if "admin@opticable.ca" not in recipient else 0.95,
            proposed_folder="/Opticable/Admin and Providers",
            business_object="provider_account_or_admin_record",
            next_action="Review only if the message changes access, billing, service status, renewal or account configuration",
            priority="normal",
            waiting_on=None,
            migration_candidate=migration,
            migration_target="admin@opticable.ca" if migration else None,
        )

    if legacy:
        human_sender = sender and not _has_any(sender, ("noreply", "no-reply", "do-not-reply", "donotreply", "notification", "notifications", "service@intl.paypal"))
        return DryRunDecision(
            category="legacy_address_review",
            confidence=0.70,
            proposed_folder="/Business Records/Legacy Opti-Plex Migration",
            business_object="provider_migration_candidate" if not human_sender else "legacy_correspondence_review",
            next_action="Determine whether this sender/account should be migrated to an Opticable address",
            priority="low",
            waiting_on="opticable",
            migration_candidate=not human_sender,
            migration_target="admin@opticable.ca" if not human_sender else None,
        )

    return DryRunDecision(
        category="unclassified",
        confidence=0.35,
        proposed_folder=None,
        business_object=None,
        next_action=None,
        priority="low",
        waiting_on=None,
        migration_candidate=False,
        migration_target=None,
    )


def classify_batch(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for message in messages:
        decision = classify_message(message).to_dict()
        decision["messageId"] = message.get("messageId")
        decision["subject"] = message.get("subject")
        decision["fromAddress"] = message.get("fromAddress")
        decision["toAddress"] = message.get("toAddress")
        results.append(decision)
    return results
