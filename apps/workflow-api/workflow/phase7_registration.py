"""Exact-release, root-controlled Phase 7 operator route registration.

No environment flag by itself installs a writer. An immutable local release
manifest must bind the checked-out SHA, operator identity and narrowly pinned
approval IDs. The absence of a manifest or flag leaves every route absent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess

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
            "business_actions_enabled"}:
        raise ValueError("Phase 7 registration manifest has unexpected fields")
    if (manifest["mode"] != MODE or not isinstance(checkout_sha, str)
            or not _SHA.fullmatch(checkout_sha) or manifest["candidate_sha"] != checkout_sha
            or env.get("OPTIBRAIN_PHASE7_RELEASE_SHA") != checkout_sha
            or manifest["api_version"] != "1.11.0"):
        raise ValueError("Phase 7 registration is not bound to this release")
    if not isinstance(manifest["business_actions_enabled"], bool):
        raise ValueError("Invalid Phase 7 business-action setting")
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


def maybe_install_phase7(app, *, client, store, engine, api_version: str,
                         manifest_path: Path = MANIFEST):
    if os.environ.get("OPTIBRAIN_PHASE7_REGISTRATION") is None:
        return {"registered": False, "create": False, "crm": False, "outbound": False}
    if api_version != "1.11.0":
        raise ValueError("Phase 7 registration requires API 1.11.0")
    raw = subprocess.check_output(["/usr/bin/git", "-C", "/opt/opticable-api-platform",
                                   "rev-parse", "HEAD"], text=True, timeout=10).strip()
    manifest = _trusted_manifest(manifest_path)
    plan = validate_registration(manifest, checkout_sha=raw, env=os.environ)
    if not plan["registered"]:
        return plan
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
        consume_callback=crm_callback, outbound_consume_callback=outbound_callback)
    install_phase7_create_routes(
        app, verifier=verifier, client=client, store=store,
        allowed_origin=manifest["allowed_origin"], consume_callback=create_callback)
    return plan
