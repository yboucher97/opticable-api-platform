"""Exact-release, root-controlled Phase 7 operator route registration.

No environment flag by itself installs a writer. An immutable local release
manifest must bind the checked-out SHA, operator identity and narrowly pinned
approval IDs. The absence of a manifest or flag leaves every route absent.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import stat

from .automation.phase7_lead_create import POLICY as CREATE_POLICY, LeadCreateLedger, execute_approved_create
from .automation.phase7_crm_approval import CrmCanaryApprovalLedger
from .automation.outbound_approval import OutboundApprovalLedger
from .automation.phase7_crm_executor import execute_approved_canary
from .automation.providers.outbound_mail import register_outbound_mail_action
from .operator_access import AccessIdentityVerifier
from .operator_phase7_api import install_phase7_canary_routes
from .operator_phase7_create_api import install_phase7_create_routes


MODE = "phase7-single-canary-v1"
MANIFEST = Path("/etc/optibrain/phase7-canary-registration.json")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_PIN = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PINNED_SOURCES = frozenset({
    "workflow/api.py", "workflow/phase7_registration.py",
    "workflow/operator_access.py", "workflow/operator_phase7_api.py",
    "workflow/operator_manager_api.py",
    "workflow/automation/manager_store.py", "workflow/automation/manager_sources.py",
    "workflow/automation/manager_intelligence.py", "workflow/automation/manager_runtime.py",
    "workflow/automation/manager_preparation.py", "workflow/automation/manager_forms.py",
    "workflow/automation/manager_preview.py", "workflow/automation/optimization_store.py",
    "workflow/automation/ads_runtime.py",
    "workflow/zoho_oauth.py",
    "workflow/operator_phase7_create_api.py",
    "workflow/automation/phase7_lead_create.py",
    "workflow/automation/phase7_crm_approval.py",
    "workflow/automation/phase7_crm_executor.py",
    "workflow/automation/sales_operator_view.py",
    "workflow/automation/sales_queue.py",
    "workflow/automation/sales_lab.py",
    "workflow/automation/phase9_intake.py",
    "workflow/automation/phase9_form_receipts.py",
    "workflow/automation/phase9_form_enrichment.py",
    "workflow/automation/followup_mail.py",
    "workflow/automation/crm_write_boundary.py",
    "workflow/automation/test_lab_boundary.py",
    "workflow/automation/business_autonomy.py",
    "workflow/automation/phase12_followup.py",
    "workflow/automation/providers/lifecycle.py",
    "workflow/automation/outbound_approval.py",
    "workflow/automation/providers/outbound_mail.py",
    "workflow/automation/mutation_control.py", "workflow/automation/remote_effects.py",
    "workflow/automation/provider_usage.py",
    "workflow/automation/today.py", "workflow/automation/readiness.py",
    "workflow/automation/lifecycle.py", "workflow/automation/lifecycle_control.py",
    "workflow/automation/real_internal.py",
    "workflow/automation/customer_communications.py", "workflow/automation/customer_send_control.py",
    "workflow/automation/customer_delivery.py", "workflow/automation/customer_runtime.py",
    "workflow/automation/customer_finance_evidence.py", "workflow/automation/operational_lifecycle.py",
    "workflow/automation/read_inventory_cache.py", "workflow/automation/mail_observation_cache.py",
    "workflow/automation/customer_lifecycle.py", "workflow/automation/operations.py",
    "workflow/automation/providers/lifecycle_mailbox.py",
    "workflow/automation/providers/crm_leads.py",
    "workflow/zoho_gateway.py", "workflow/google_api.py", "workflow/cloudflare_api.py", "workflow/github_api.py",
})


def _trusted_manifest(path: Path = MANIFEST, *, trusted_uid: int = 0) -> dict:
    for parent in list(path.parents)[:-1]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != trusted_uid or info.st_mode & 0o022:
            raise ValueError("Untrusted Phase 7 registration parent")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != trusted_uid
                or stat.S_IMODE(info.st_mode) != 0o644 or info.st_nlink != 1):
            raise ValueError("Untrusted Phase 7 registration manifest")
        with os.fdopen(fd) as stream:
            fd = -1
            value = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    return value


def validate_registration(manifest: dict, *, checkout_sha: str, env: dict) -> dict:
    """Pure, fail-closed registration plan suitable for fixture tests."""
    if env.get("OPTIBRAIN_PHASE7_REGISTRATION") != MODE:
        return {"registered": False, "create": False, "crm": False, "outbound": False}
    if not isinstance(manifest, dict) or set(manifest) != {
            "mode", "candidate_sha", "api_version", "allowed_origin", "team_domain",
            "access_audience", "allowed_subjects", "allowed_emails", "mailbox_account_id",
            "from_address", "create_approval_id", "create_request_hash",
            "crm_approval_id", "outbound_approval_id",
            "business_actions_enabled", "source_hashes"}:
        raise ValueError("Phase 7 registration manifest has unexpected fields")
    if (manifest["mode"] != MODE or not isinstance(checkout_sha, str)
            or not _SHA.fullmatch(checkout_sha) or manifest["candidate_sha"] != checkout_sha
            or env.get("OPTIBRAIN_PHASE7_RELEASE_SHA") != checkout_sha
            or manifest["api_version"] != "1.29.0"):
        raise ValueError("Phase 7 registration is not bound to this release")
    if not isinstance(manifest["business_actions_enabled"], bool):
        raise ValueError("Invalid Phase 7 business-action setting")
    hashes = manifest["source_hashes"]
    if (not isinstance(hashes, dict) or set(hashes) != _PINNED_SOURCES
            or any(not isinstance(value, str) or not _HASH.fullmatch(value)
                   for value in hashes.values())):
        raise ValueError("Phase 7 registration source hash set is incomplete")
    enabled = manifest["business_actions_enabled"]
    pins = {"create": "create_approval_id", "crm": "crm_approval_id",
            "outbound": "outbound_approval_id"}
    active = {}
    for action, key in pins.items():
        value = manifest[key]
        if value is not None and (not isinstance(value, str) or not _PIN.fullmatch(value)):
            raise ValueError("Invalid Phase 7 single-use approval pin")
        active[action] = enabled and value is not None
    if enabled and not any(active.values()):
        raise ValueError("Business-action registration requires an exact approval pin")
    create_hash = manifest["create_request_hash"]
    if create_hash is not None and (not isinstance(create_hash, str) or not _HASH.fullmatch(create_hash)):
        raise ValueError("Invalid exact Lead create request hash")
    if active["create"] and create_hash is None:
        raise ValueError("Lead create pin requires an exact reviewed request hash")
    return {"registered": True, **active}


def verify_source_hashes(expected: dict, *, root: Path) -> None:
    """Bind service-readable code to the root-reviewed exact-SHA manifest.

    The service identity cannot read production Git metadata. Root verifies
    HEAD/ancestry during staging and installs this exact content-hash manifest.
    """
    for relative in sorted(_PINNED_SOURCES):
        path = root / relative
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o022:
                raise ValueError("Unsafe Phase 7 source file")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
        finally:
            if fd >= 0:
                os.close(fd)
        if actual != expected[relative]:
            raise ValueError("Phase 7 source differs from reviewed release")


def maybe_install_phase7(app, *, client, store, engine, api_version: str,
                         manifest_path: Path = MANIFEST, readiness=None):
    if os.environ.get("OPTIBRAIN_PHASE7_REGISTRATION") is None:
        return {"registered": False, "create": False, "crm": False, "outbound": False}
    if api_version != "1.29.0":
        raise ValueError("Phase 7 registration requires API 1.29.0")
    manifest = _trusted_manifest(manifest_path)
    plan = validate_registration(manifest, checkout_sha=manifest["candidate_sha"], env=os.environ)
    if not plan["registered"]:
        return plan
    verify_source_hashes(manifest["source_hashes"], root=Path(__file__).resolve().parents[1])
    verifier = AccessIdentityVerifier(
        team_domain=manifest["team_domain"], audience=manifest["access_audience"],
        allowed_subjects=manifest["allowed_subjects"],
        allowed_emails=manifest["allowed_emails"])
    create_callback = None
    crm_callback = None
    outbound_callback = None
    if plan["create"]:
        pin = manifest["create_approval_id"]
        if (os.environ.get("OPTIBRAIN_LEAD_CREATE_CANARY") != CREATE_POLICY
                or os.environ.get("OPTIBRAIN_LEAD_CREATE_APPROVAL_ID") != pin):
            raise ValueError("Lead create execution pin differs from registration")
        approval = LeadCreateLedger(store).inspect(pin)
        if (approval is None or approval["state"] != "issued"
                or approval["approval"].payload_hash != manifest["create_request_hash"]):
            raise ValueError("Lead create approval differs from release registration")
        create_callback = lambda approval_id, fields: execute_approved_create(client, store, approval_id, fields)
    if plan["crm"]:
        pin = manifest["crm_approval_id"]
        if (os.environ.get("OPTIBRAIN_CRM_CANARY") != MODE
                or os.environ.get("OPTIBRAIN_CRM_CANARY_APPROVAL_ID") != pin):
            raise ValueError("CRM execution pin differs from registration")
        approval = CrmCanaryApprovalLedger(store).inspect(pin)
        if approval is None or approval["state"] != "issued":
            raise ValueError("CRM approval differs from release registration")
        crm_callback = lambda approval_id: execute_approved_canary(client, store, approval_id)
    if plan["outbound"]:
        pin = manifest["outbound_approval_id"]
        if (os.environ.get("OPTIBRAIN_OUTBOUND_SENDS") != MODE
                or os.environ.get("OPTIBRAIN_OUTBOUND_CANARY_APPROVAL_ID") != pin):
            raise ValueError("Outbound execution pin differs from registration")
        approval = OutboundApprovalLedger(store).inspect(pin)
        if approval is None or approval["state"] != "issued":
            raise ValueError("Outbound approval differs from release registration")
        handler = register_outbound_mail_action(engine, client, store)
        from types import SimpleNamespace
        outbound_callback = lambda request: handler({"event": {}}, SimpleNamespace(inputs={"send": request}))
    install_phase7_canary_routes(
        app, verifier=verifier, client=client, store=store,
        account_id=manifest["mailbox_account_id"], from_address=manifest["from_address"],
        allowed_origin=manifest["allowed_origin"],
        consume_callback=crm_callback, outbound_consume_callback=outbound_callback,readiness=readiness)
    install_phase7_create_routes(
        app, verifier=verifier, client=client, store=store,
        allowed_origin=manifest["allowed_origin"], consume_callback=create_callback)
    return plan
