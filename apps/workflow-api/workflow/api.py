from __future__ import annotations

import os
import re
import hmac
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from .clients import OmadaClient
from .config import load_settings
from .jobs import JobStore
from .logging_utils import configure_logging
from .models import parse_payload
from .omada_operations import build_live_snapshot, resolve_workdrive_execution_source
from .omada_plan import operation_plan_filename
from .pipeline import SiteWorkflowPipeline
from .utils import ensure_directory, sanitize_filename, utc_timestamp
from .workdrive import WorkflowWorkDriveClient, WorkflowWorkDriveError
from .zoho_oauth import ZohoOAuthManager
from .google_oauth import GoogleOAuthManager
from .google_api import GoogleApiClient, GoogleApiError, SERVICE_BASES as GOOGLE_SERVICE_BASES
from .zoho_gateway import ZohoGatewayClient, ZohoGatewayError
from .windsor_api import WindsorApiClient
from .ovh_api import OvhApiClient
from .ai_router import AiRouter
from .cloudflare_api import CloudflareApiClient
from .github_api import GithubApiClient
from .apollo_api import ApolloApiClient
from .customer_lifecycle import EmailIntakeRequest, LeadIntakeRequest, MeetingRequest, email_event_idempotency_key, lead_event_idempotency_key
from .automation import (
    AutomationEngine,
    AutomationEvent,
    AutomationStore,
    DesiredPlan,
    DesiredStateController,
    DesiredStateDocument,
    DesiredStateRegistry,
)
from .automation.capabilities import capability_summary, load_capabilities
from .automation.health_monitor import AutomationHealthMonitor
from .automation.maintenance import AutomationMaintenance
from .automation.events import EventLedger
from .automation.sync_runtime import DeltaWorker, initialize_jobs
from .automation.event_api import install_event_routes
from .automation.event_body_limit import EventBodyLimit
from .automation.models import EventIngestResponse
from .automation.providers.google import register_google_actions
from .automation.providers.zoho import register_zoho_actions
from .automation.providers.crm_leads import register_crm_lead_actions
from .automation.providers.windsor import register_windsor_actions
from .automation.providers.ovh import register_ovh_actions
from .automation.providers.ai import register_ai_actions
from .automation.providers.core_external import register_core_external_actions
from .automation.providers.lifecycle import register_lifecycle_actions
from .automation.providers.lifecycle_extended import register_lifecycle_extended_actions
from .automation.providers.lifecycle_phase2 import register_lifecycle_phase2_actions
from .automation.providers.lifecycle_mailbox import register_lifecycle_mailbox_actions
from .automation.reconcilers.zoho_crm import ZohoCrmFieldReconciler
from .automation.reconcilers.zoho_metadata import register_crm_metadata
from .automation.reconcilers.zoho_notification import ZohoCrmNotificationReconciler
from .automation.crm_inventory import CrmInventoryCollector
from .automation.desired_journal import ApplyConflict
from .automation.desired_drift import DesiredDriftObserver
from .automation.native_notifications import NativeNotificationWorker, native_health


settings = load_settings()
logger = configure_logging(ensure_directory(settings.output.root_dir / "logs"))
job_store = JobStore(settings.output.jobs_dir, logger)
automation_store = AutomationStore(settings.automation.db_path)
automation_engine = AutomationEngine(
    automation_store,
    settings.automation.workflows_dir,
    max_event_depth=settings.automation.max_event_depth,
)
automation_health_monitor = AutomationHealthMonitor(automation_store, sync_health=lambda: delta_sync_worker.health())
desired_state_registry = DesiredStateRegistry()
desired_state_controller = DesiredStateController(desired_state_registry, automation_store)
google_oauth_manager = GoogleOAuthManager(settings.google_oauth)
google_api_client = GoogleApiClient(google_oauth_manager)
zoho_gateway_client = ZohoGatewayClient(settings.zoho_gateway, ZohoOAuthManager(settings.zoho_oauth))
delta_sync_worker = DeltaWorker(automation_store, google_oauth_manager.access_token, zoho_gateway_client)
windsor_api_client = WindsorApiClient(settings.windsor)
ovh_api_client = OvhApiClient(settings.ovh)
ai_router = AiRouter(settings.ai)
cloudflare_api_client = CloudflareApiClient(settings.cloudflare)
github_api_client = GithubApiClient(settings.github)
apollo_api_client = ApolloApiClient(settings.apollo)
desired_state_registry.register("zoho_crm", "field", ZohoCrmFieldReconciler(zoho_gateway_client))
register_crm_metadata(desired_state_registry, zoho_gateway_client)
desired_state_registry.register("zoho_crm", "notification", ZohoCrmNotificationReconciler(zoho_gateway_client))
native_notification_worker = None
if os.getenv("OPTIBRAIN_CRM_DRIFT_ENABLED") == "true":
    delta_sync_worker.observer = DesiredDriftObserver(desired_state_controller, Path(__file__).resolve().parents[1] / "config/automation/desired-state")
    native_notification_worker = NativeNotificationWorker(desired_state_controller,
        Path(__file__).resolve().parents[1] / "config/automation/desired-state/zoho-crm-notification.template.json")
register_google_actions(automation_engine, google_api_client, automation_store)
register_zoho_actions(automation_engine, zoho_gateway_client, automation_store)
register_crm_lead_actions(automation_engine, zoho_gateway_client, automation_store)
register_windsor_actions(automation_engine, windsor_api_client, automation_store)
register_ovh_actions(automation_engine, ovh_api_client, automation_store)
register_ai_actions(automation_engine, ai_router, automation_store)
register_core_external_actions(automation_engine, cloudflare_api_client, github_api_client, apollo_api_client, automation_store)
register_lifecycle_actions(automation_engine, zoho_gateway_client, automation_store)
register_lifecycle_extended_actions(automation_engine, zoho_gateway_client, ai_router, automation_store)
register_lifecycle_phase2_actions(automation_engine, zoho_gateway_client, ai_router, automation_store)
register_lifecycle_mailbox_actions(automation_engine, zoho_gateway_client, automation_store)
API_VERSION = "1.19.0"
PRIMARY_WEBHOOK_PATH = "/v1/site-and-password/webhooks/zoho"
PRIMARY_JOB_CREATE_PATH = "/v1/site-and-password/jobs"
PRIMARY_JOB_STATUS_PATH = "/v1/site-and-password/jobs/{job_id}"
WORKFLOW_CANONICAL_PATH = "/v1/workflows/site-and-password"
WORKFLOW_CANONICAL_JOB_STATUS_PATH = "/v1/workflows/site-and-password/jobs/{job_id}"
ZOHO_OAUTH_START_PATH = "/v1/integrations/zoho/oauth/start"
ZOHO_OAUTH_CALLBACK_PATH = "/v1/integrations/zoho/oauth/callback"
ZOHO_OAUTH_STATUS_PATH = "/v1/integrations/zoho/oauth/status"
GOOGLE_OAUTH_START_PATH = "/v1/integrations/google/oauth/start"
GOOGLE_OAUTH_CALLBACK_PATH = "/v1/integrations/google/oauth/callback"
GOOGLE_OAUTH_STATUS_PATH = "/v1/integrations/google/oauth/status"
PLATFORM_DOCS_PATH = "/docs"
PLATFORM_OPENAPI_PATH = "/openapi.json"


AUTOMATION_RECOVERY_STALL_SECONDS = 300.0
AUTOMATION_RECOVERY_HEARTBEAT_STALE_SECONDS = 60.0
AUTOMATION_TERMINAL_CLAIM_RETENTION_DAYS = 30
AUTOMATION_MAINTENANCE_INTERVAL_SECONDS = 3600.0
AUTOMATION_HEALTH_WATCHDOG_INTERVAL_SECONDS = 30.0

_automation_recovery_lock = threading.Lock()
_automation_recovery_thread: threading.Thread | None = None
_automation_recovery_state: dict[str, Any] = {
    "enabled": bool(settings.automation.enabled),
    "state": "not_started" if settings.automation.enabled else "disabled",
    "consecutive_failures": 0,
    "scan_in_progress": False,
    "_scan_started_monotonic": None,
    "_last_success_monotonic": None,
    "last_scan_started_at": None,
    "last_scan_completed_at": None,
    "last_success_at": None,
    "stopped_due_to_failures": False,
}


def _update_automation_recovery_state(**updates: Any) -> None:
    with _automation_recovery_lock:
        _automation_recovery_state.update(updates)


def _set_automation_recovery_thread(thread: threading.Thread | None) -> None:
    global _automation_recovery_thread
    with _automation_recovery_lock:
        _automation_recovery_thread = thread


def _automation_recovery_health() -> dict[str, Any]:
    """Return bounded in-process recovery/scheduler state without changing execution."""
    with _automation_recovery_lock:
        snapshot = dict(_automation_recovery_state)
        thread = _automation_recovery_thread

    started_monotonic = snapshot.pop("_scan_started_monotonic", None)
    last_success_monotonic = snapshot.pop("_last_success_monotonic", None)

    thread_alive = bool(thread is not None and thread.is_alive())
    enabled = bool(snapshot["enabled"])
    scan_in_progress = bool(snapshot["scan_in_progress"])

    scan_age_seconds = 0
    scan_stalled = False
    if scan_in_progress:
        if isinstance(started_monotonic, (int, float)):
            scan_age_seconds = max(0, int(time.monotonic() - started_monotonic))
            scan_stalled = scan_age_seconds >= AUTOMATION_RECOVERY_STALL_SECONDS
        else:
            scan_stalled = True

    heartbeat_age_seconds = 0
    heartbeat_stale = False
    if enabled and snapshot["state"] == "running" and not scan_in_progress:
        if isinstance(last_success_monotonic, (int, float)):
            heartbeat_age_seconds = max(
                0,
                int(time.monotonic() - last_success_monotonic),
            )
            heartbeat_stale = (
                heartbeat_age_seconds
                >= AUTOMATION_RECOVERY_HEARTBEAT_STALE_SECONDS
            )
        else:
            heartbeat_stale = True

    if not enabled:
        healthy = snapshot["state"] == "disabled"
    else:
        healthy = (
            thread_alive
            and snapshot["state"] == "running"
            and int(snapshot["consecutive_failures"]) == 0
            and not bool(snapshot["stopped_due_to_failures"])
            and not scan_stalled
            and not heartbeat_stale
        )

    snapshot["thread_alive"] = thread_alive
    snapshot["scan_age_seconds"] = scan_age_seconds
    snapshot["scan_stalled"] = scan_stalled
    snapshot["stall_after_seconds"] = int(AUTOMATION_RECOVERY_STALL_SECONDS)
    snapshot["heartbeat_age_seconds"] = heartbeat_age_seconds
    snapshot["heartbeat_stale"] = heartbeat_stale
    snapshot["heartbeat_stale_after_seconds"] = int(
        AUTOMATION_RECOVERY_HEARTBEAT_STALE_SECONDS
    )
    snapshot["healthy"] = healthy
    return snapshot


class AutomationRedriveRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


class AutomationCleanupRequest(BaseModel):
    retention_days: int = Field(default=30, ge=1, le=3650)
    limit: int = Field(default=100, ge=1, le=1000)
    reason: str = Field(
        default="Explicit bounded terminal claim retention cleanup",
        min_length=8,
        max_length=500,
    )


class ServiceRoute(BaseModel):
    name: str
    path_prefix: str
    description: str


class PlatformIndexResponse(BaseModel):
    name: str
    version: str
    docs_url: str
    openapi_url: str
    primary_webhook: str
    canonical_workflow: str
    services: list[ServiceRoute]


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    jobs_dir: str
    pdf_base_url: str
    omada_base_url: str


class WorkflowJobAcceptedResponse(BaseModel):
    status: str
    job_id: str
    building_name: str
    record_count: int
    credential_mode: str
    workflow_mode: str
    omada_operation: str
    job_status_url: str


class JobLookupResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    request_summary: dict[str, Any]
    error: str | None = None
    result: dict[str, Any] | None = None


class OmadaSiteItem(BaseModel):
    id: str
    name: str


class OmadaLanItem(BaseModel):
    id: str
    name: str
    vlan: int


class OmadaNamedItem(BaseModel):
    id: str
    name: str


class OmadaSitesResponse(BaseModel):
    ok: bool
    organizationName: str
    count: int
    items: list[OmadaSiteItem]


class OmadaSiteResponse(BaseModel):
    ok: bool
    site: OmadaSiteItem


class OmadaLansResponse(BaseModel):
    ok: bool
    siteId: str
    count: int
    items: list[OmadaLanItem]


class OmadaWlanGroupsResponse(BaseModel):
    ok: bool
    siteId: str
    count: int
    items: list[OmadaNamedItem]


class OmadaSsidsResponse(BaseModel):
    ok: bool
    siteId: str
    wlanId: str
    count: int
    items: list[OmadaNamedItem]


class OmadaJobAcceptedResponse(BaseModel):
    status: str
    job_id: str | None = None
    job_status_url: str | None = None
    job: dict[str, Any]


class OmadaWorkDriveJobRequest(BaseModel):
    workdrive_folder_id: str
    operation: Literal["create", "upsert", "update"] = "create"
    source_preference: Literal["yaml_then_txt", "yaml_only", "txt_only"] = "yaml_then_txt"
    building_name: str | None = None
    site_name: str | None = None
    city: str | None = None
    template_name: str = "Opticable_Template_01"
    omada_region: str | None = None
    omada_timezone: str | None = None
    omada_scenario: str | None = None


class OmadaWorkDriveJobAcceptedResponse(BaseModel):
    status: str
    operation: str
    source_type: str
    source_file_name: str
    source_file_id: str
    source_folder_id: str
    building_name: str
    site_name: str
    job_id: str | None = None
    job_status_url: str | None = None
    job: dict[str, Any]


class OmadaSiteSnapshotSsid(BaseModel):
    id: str
    name: str
    password: str | None = Field(default=None, description="Not exposed by current live Omada discovery.")


class OmadaSiteSnapshotWlanGroup(BaseModel):
    id: str
    name: str
    ssids: list[OmadaSiteSnapshotSsid]


class OmadaSiteSnapshotResponse(BaseModel):
    version: int
    operation: str
    source: str
    passwordsAvailable: bool
    site: OmadaSiteItem
    lans: list[OmadaLanItem]
    wlanGroups: list[OmadaSiteSnapshotWlanGroup]


class ZohoOAuthStatusResponse(BaseModel):
    provider: str
    configured: bool
    connected: bool
    accounts_base_url: str
    redirect_uri: str | None
    authorization_start_url: str
    callback_url: str
    credentials_path: str
    connected_at: str | None = None
    scope: str | None = None
    configured_scopes: list[str]
    api_domain: str | None = None
    has_refresh_token: bool
    client_id_suffix: str | None = None


class ZohoOAuthConnectResponse(BaseModel):
    provider: str
    status: str
    authorization_url: str
    callback_url: str


class ZohoOAuthCallbackResponse(BaseModel):
    provider: str
    status: str
    connected: bool
    credentials_path: str
    scope: str | None = None
    api_domain: str | None = None


class GoogleOAuthStatusResponse(BaseModel):
    provider: str = "google"
    configured: bool
    connected: bool
    redirect_uri: str | None
    authorization_start_url: str
    callback_url: str
    credentials_path: str
    connected_at: str | None = None
    granted_scope: str | None = None
    configured_scopes: list[str]
    has_refresh_token: bool
    client_id_suffix: str | None = None
    services: list[str]


class GoogleOAuthConnectResponse(BaseModel):
    provider: str = "google"
    status: str
    authorization_url: str
    callback_url: str


class GoogleOAuthCallbackResponse(BaseModel):
    provider: str = "google"
    status: str
    connected: bool
    credentials_path: str
    scope: str | None = None


def _service_catalog() -> list[ServiceRoute]:
    return [
        ServiceRoute(
            name="workflow-api",
            path_prefix="/v1/workflows/site-and-password",
            description="Primary public workflow API for webhook intake and job tracking.",
        ),
        ServiceRoute(
            name="password-pdf-service",
            path_prefix="/pdf",
            description="Raw internal PDF service proxied for health/debug access only.",
        ),
        ServiceRoute(
            name="omada-site-service",
            path_prefix="/omada",
            description="Raw internal Omada service proxied for health/debug access only.",
        ),
        ServiceRoute(
            name="workflow-raw",
            path_prefix="/workflow",
            description="Raw workflow service access for health/debug endpoints.",
        ),
        ServiceRoute(
            name="zoho-oauth",
            path_prefix="/v1/integrations/zoho",
            description="Server-side Zoho OAuth setup for WorkDrive and optional CRM integration.",
        ),
        ServiceRoute(
            name="omada",
            path_prefix="/v1/omada",
            description="Public Omada discovery and plan-submission API for sites, LANs, WLAN groups, SSIDs, and direct YAML/JSON job intake.",
        ),
        ServiceRoute(
            name="provider-inventory",
            path_prefix="/v1/system/providers",
            description="Credential-safe inventory of canonical provider paths, connection state, and standby policy.",
        ),
        ServiceRoute(
            name="automation-kernel",
            path_prefix="/v1/automation",
            description="Provider-neutral event, workflow, capability, audit, and run-control APIs.",
        ),
        ServiceRoute(
            name="google-admin",
            path_prefix="/v1/integrations/google",
            description="OAuth and controlled API access for Google Tag Manager and Google Analytics Admin.",
        ),
    ]


WORKFLOW_PAYLOAD_EXAMPLES = {
    "generated_pdf_and_site": {
        "summary": "Generated credentials, then PDFs and site creation",
        "value": {
            "building_name": "123 Main Street",
            "credential_mode": "generated",
            "workflow_mode": "pdf_and_site",
            "omada_operation": "ensure",
            "template_name": "Opticable_Template_01",
            "workdrive_folder_id": "replace-with-workdrive-folder-id",
            "site_name": "123 Main Street",
            "units": ["101", "102", "103"],
        },
    },
    "generated_pdf_only": {
        "summary": "Generated credentials, PDFs only",
        "value": {
            "building_name": "456 Example Avenue",
            "credential_mode": "generated",
            "workflow_mode": "pdf_only",
            "omada_operation": "ensure",
            "template_name": "Opticable_Template_01",
            "units": ["201", "202"],
        },
    },
    "predefined_pdf_only": {
        "summary": "Predefined credentials, PDFs only",
        "value": {
            "building_name": "789 Sample Road",
            "credential_mode": "predefined",
            "workflow_mode": "pdf_only",
            "omada_operation": "ensure",
            "template_name": "Opticable_Template_01",
            "ssids": ["APT_301_AA", "APT_302_BB"],
            "passwords": ["1234ab5678!@", "5678cd1234#$"],
        },
    },
    "predefined_site_only": {
        "summary": "Predefined credentials, Omada site only",
        "value": {
            "building_name": "Standalone Site Template",
            "site_name": "Standalone Site Template",
            "credential_mode": "predefined",
            "workflow_mode": "site_only",
            "omada_operation": "create",
            "template_name": "Opticable_Template_01",
            "ssids": ["APT_401_AA", "APT_402_BB"],
            "passwords": ["1234ab5678!@", "5678cd1234#$"],
        },
    },
    "generated_password_rotation_update": {
        "summary": "Generate fresh passwords, upload artifacts, then update existing Omada SSIDs",
        "value": {
            "building_name": "Existing Building",
            "site_name": "Existing Building",
            "credential_mode": "generated",
            "workflow_mode": "pdf_and_site",
            "omada_operation": "update",
            "template_name": "Opticable_Template_01",
            "workdrive_folder_id": "replace-with-workdrive-folder-id",
            "units": ["101", "102", "103"],
        },
    },
}

OMADA_WORKDRIVE_JOB_EXAMPLES = {
    "yaml_first_upsert": {
        "summary": "Resolve WorkDrive folder using upsert.yaml/create.yaml first, TXT second",
        "value": {
            "workdrive_folder_id": "replace-with-workdrive-folder-id",
            "operation": "upsert",
            "source_preference": "yaml_then_txt",
            "site_name": "123 Main Street",
            "building_name": "123 Main Street",
            "omada_region": "Canada",
            "omada_timezone": "America/Toronto",
            "omada_scenario": "Office",
        },
    },
    "txt_fallback_create": {
        "summary": "No YAML in WorkDrive, create site from TXT export",
        "value": {
            "workdrive_folder_id": "replace-with-workdrive-folder-id",
            "operation": "create",
            "source_preference": "yaml_then_txt",
            "site_name": "456 Example Avenue",
            "building_name": "456 Example Avenue",
        },
    },
    "yaml_update_existing": {
        "summary": "Update an existing site from update.yaml or TXT fallback",
        "value": {
            "workdrive_folder_id": "replace-with-workdrive-folder-id",
            "operation": "update",
            "source_preference": "yaml_then_txt",
            "site_name": "Existing Building",
            "building_name": "Existing Building",
        },
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Site workflow API starting")
    recovery_stop = threading.Event()
    recovery_thread: threading.Thread | None = None
    health_thread: threading.Thread | None = None

    if settings.automation.enabled:
        _update_automation_recovery_state(
            enabled=True,
            state="starting",
            consecutive_failures=0,
            scan_in_progress=False,
            _scan_started_monotonic=None,
            _last_success_monotonic=None,
            last_scan_started_at=None,
            last_scan_completed_at=None,
            last_success_at=None,
            stopped_due_to_failures=False,
        )
        _set_automation_recovery_thread(None)

        try:
            loaded_workflows = automation_engine.sync_definitions()
            sync_jobs = initialize_jobs(automation_store)
            delta_sync_worker.start(sync_jobs)
            if native_notification_worker is not None:
                native_notification_worker.start()
            logger.info(
                "Automation kernel loaded %d workflow definition(s): %s",
                len(loaded_workflows),
                loaded_workflows,
            )
        except Exception:
            _update_automation_recovery_state(state="startup_failed")
            logger.exception("Automation kernel failed to load workflow definitions")
            raise

        def observe_and_recover() -> None:
            failures = 0
            last_cleanup_monotonic = 0.0

            while not recovery_stop.is_set():
                started_at = utc_timestamp()
                _update_automation_recovery_state(
                    state="running" if failures == 0 else "degraded",
                    scan_in_progress=True,
                    _scan_started_monotonic=time.monotonic(),
                    last_scan_started_at=started_at,
                )

                stopped = False
                try:
                    automation_engine.recover_pending(limit=10)
                    failures = 0
                    completed_at = utc_timestamp()
                    _update_automation_recovery_state(
                        state="running",
                        consecutive_failures=0,
                        scan_in_progress=False,
                        _scan_started_monotonic=None,
                        _last_success_monotonic=time.monotonic(),
                        last_scan_completed_at=completed_at,
                        last_success_at=completed_at,
                        stopped_due_to_failures=False,
                    )
                except Exception:
                    failures += 1
                    completed_at = utc_timestamp()
                    stopped = failures >= 3
                    _update_automation_recovery_state(
                        state="stopped" if stopped else "degraded",
                        consecutive_failures=failures,
                        scan_in_progress=False,
                        _scan_started_monotonic=None,
                        last_scan_completed_at=completed_at,
                        stopped_due_to_failures=stopped,
                    )
                    logger.exception(
                        "Automation recovery scan failed (%d/3)",
                        failures,
                    )
                    if stopped:
                        logger.error(
                            "Automation recovery stopped; human action required"
                        )

                if stopped:
                    return

                now_monotonic = time.monotonic()
                if (
                    now_monotonic - last_cleanup_monotonic
                    >= AUTOMATION_MAINTENANCE_INTERVAL_SECONDS
                ):
                    last_cleanup_monotonic = now_monotonic
                    try:
                        cleanup = AutomationMaintenance(
                            automation_store
                        ).cleanup_terminal_claims(
                            retention_days=AUTOMATION_TERMINAL_CLAIM_RETENTION_DAYS,
                            limit=100,
                            actor="automation-maintenance",
                            reason="Automatic bounded terminal claim retention cleanup",
                        )
                        EventLedger(automation_store).cleanup()
                        if cleanup["deleted_claims"]:
                            logger.info(
                                "Automation maintenance removed %d old terminal claim(s)",
                                cleanup["deleted_claims"],
                            )
                    except Exception:
                        logger.exception(
                            "Automation terminal-claim maintenance failed"
                        )

                recovery_stop.wait(5 if failures == 0 else 30)

        recovery_thread = threading.Thread(
            target=observe_and_recover,
            name="automation-recovery",
            daemon=True,
        )
        _set_automation_recovery_thread(recovery_thread)
        recovery_thread.start()

        def observe_health() -> None:
            while not recovery_stop.is_set():
                try:
                    observed = automation_health_monitor.observe(
                        _automation_recovery_health()
                    )

                    if observed.get("state_changed"):
                        codes = [
                            item["code"]
                            for item in observed.get("alerts", [])
                            if isinstance(item, dict)
                            and item.get("code")
                        ]

                        if observed["status"] == "critical":
                            logger.error(
                                "Automation health critical: %s",
                                ",".join(codes) or "unspecified",
                            )
                        elif observed["status"] == "warning":
                            logger.warning(
                                "Automation health warning: %s",
                                ",".join(codes) or "unspecified",
                            )
                        else:
                            logger.info(
                                "Automation health recovered; "
                                "no active alerts"
                            )
                except Exception:
                    # The watchdog must never influence workflow execution.
                    logger.exception(
                        "Automation health watchdog failed"
                    )

                recovery_stop.wait(
                    AUTOMATION_HEALTH_WATCHDOG_INTERVAL_SECONDS
                )

        health_thread = threading.Thread(
            target=observe_health,
            name="automation-health-watchdog",
            daemon=True,
        )
        health_thread.start()
    else:
        _set_automation_recovery_thread(None)
        _update_automation_recovery_state(
            enabled=False,
            state="disabled",
            consecutive_failures=0,
            scan_in_progress=False,
            _scan_started_monotonic=None,
            _last_success_monotonic=None,
            last_scan_started_at=None,
            last_scan_completed_at=None,
            last_success_at=None,
            stopped_due_to_failures=False,
        )
        logger.warning(
            "Automation kernel is disabled by OPTICABLE_AUTOMATION_ENABLED"
        )

    try:
        yield
    finally:
        recovery_stop.set()
        if recovery_thread is not None:
            recovery_thread.join(timeout=5)
        delta_sync_worker.stop()
        if native_notification_worker is not None:
            native_notification_worker.stop()
        if health_thread is not None:
            health_thread.join(timeout=5)
        if settings.automation.enabled:
            _update_automation_recovery_state(
                state="shutdown",
                scan_in_progress=False,
                _scan_started_monotonic=None,
                _last_success_monotonic=None,
            )
        _set_automation_recovery_thread(None)
        logger.info("Site workflow API shutting down")


app = FastAPI(
    title="Opticable API Platform",
    version=API_VERSION,
    description=(
        "Opticable owner views, provider observation and journaled events. "
        "Business mutations require central authorization; real automation and legacy "
        "PDF, WorkDrive and Omada execution remain contained."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "platform", "description": "Platform index, catalog, and shared health endpoints."},
        {"name": "site-and-password", "description": "Primary workflow endpoints for webhook intake and job tracking."},
        {"name": "omada", "description": "Read-first Omada discovery endpoints for sites and network objects."},
        {"name": "integrations", "description": "External integration setup and status endpoints."},
        {"name": "automation", "description": "Provider-neutral autonomous event, workflow, capability and audit endpoints."},
        {"name": "compatibility", "description": "Legacy endpoints preserved for older webhook clients."},
    ],
)

# Phase 7 operator controls are absent by default. A root-owned exact-SHA
# registration manifest and explicit mode are required to install any route.
from .phase7_registration import maybe_install_phase7
def _readiness_payload():
    from .automation.readiness import build_readiness
    return build_readiness(automation_store,native_health(automation_store),api_version=API_VERSION,
                           auth_configured=bool(os.getenv(settings.api.api_key_env)))

phase7_registration = maybe_install_phase7(
    app, client=zoho_gateway_client, store=automation_store,
    engine=automation_engine, api_version=API_VERSION,readiness=_readiness_payload)


def _validate_api_key(provided_api_key: str | None) -> None:
    expected_api_key = os.getenv(settings.api.api_key_env)
    if not expected_api_key or not expected_api_key.strip():
        raise HTTPException(status_code=503, detail="Operator authentication is unavailable.")
    if provided_api_key is None or not hmac.compare_digest(provided_api_key.encode(), expected_api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def _validate_inspection_api_key(provided_api_key: str | None) -> None:
    """Inspection routes stay unavailable when server authentication is unset."""
    expected_api_key = os.getenv(settings.api.api_key_env)
    if not expected_api_key or not expected_api_key.strip():
        raise HTTPException(status_code=503, detail="Inspection authentication is unavailable.")
    _validate_api_key(provided_api_key)


@app.middleware("http")
async def account_provider_transport(request, call_next):
    from .automation.provider_usage import ProviderUsage
    # Nested job/view scopes own their calls. Unscoped API work is attributed
    # only to a route template; customer IDs, queries and health hits are absent.
    with ProviderUsage(automation_store.db_path,'http:request',persist_empty=False) as usage:
        try:
            return await call_next(request)
        finally:
            route=request.scope.get('route')
            template=getattr(route,'path','unknown')
            usage.job=('http:'+request.method+':'+re.sub(r'[^A-Za-z0-9_.:-]','.',template))[:100]


@app.middleware("http")
async def contain_retired_execution(request, call_next):
    path=request.url.path
    retired_post={PRIMARY_JOB_CREATE_PATH,WORKFLOW_CANONICAL_PATH,
        '/webhooks/zoho/site-and-password','/webhooks/zoho/site-workflow',
        '/v1/site-and-password/webhooks/zoho','/v1/omada/jobs','/v1/omada/workdrive/jobs'}
    if ((request.method!='GET' and path in retired_post) or path.startswith('/jobs/')
            or path.startswith(PRIMARY_JOB_STATUS_PATH.split('{')[0])
            or path.startswith(WORKFLOW_CANONICAL_JOB_STATUS_PATH.split('{')[0])):
        return JSONResponse(status_code=403,content={'detail':'Legacy execution and credential job routes retired'})
    return await call_next(request)


app.add_middleware(EventBodyLimit)
install_event_routes(app, lambda: automation_store, _validate_inspection_api_key, lambda: settings.automation.enabled,
                     delta_sync_worker.health)


def _validate_browser_or_header_api_key(
    header_api_key: str | None,
    query_api_key: str | None = None,
) -> None:
    if query_api_key is not None:
        raise HTTPException(status_code=400, detail="Credentials in URLs are forbidden. Use X-API-Key.")
    _validate_api_key(header_api_key)


def _zoho_oauth_manager() -> ZohoOAuthManager:
    return ZohoOAuthManager(settings.zoho_oauth)


def _google_status_payload() -> GoogleOAuthStatusResponse:
    status = google_oauth_manager.status()
    return GoogleOAuthStatusResponse(
        configured=status.configured,
        connected=status.connected,
        redirect_uri=status.redirect_uri,
        authorization_start_url=GOOGLE_OAUTH_START_PATH,
        callback_url=GOOGLE_OAUTH_CALLBACK_PATH,
        credentials_path=str(status.credentials_path),
        connected_at=status.connected_at,
        granted_scope=status.granted_scope,
        configured_scopes=list(status.scopes),
        has_refresh_token=status.has_refresh_token,
        client_id_suffix=status.client_id_suffix,
        services=sorted(GOOGLE_SERVICE_BASES),
    )


def _zoho_status_payload() -> ZohoOAuthStatusResponse:
    status = _zoho_oauth_manager().status()
    return ZohoOAuthStatusResponse(
        provider="zoho",
        configured=status.configured,
        connected=status.connected,
        accounts_base_url=status.accounts_base_url,
        redirect_uri=status.redirect_uri,
        authorization_start_url=ZOHO_OAUTH_START_PATH,
        callback_url=ZOHO_OAUTH_CALLBACK_PATH,
        credentials_path=str(status.credentials_path),
        connected_at=status.connected_at,
        scope=status.scope,
        configured_scopes=list(status.scopes),
        api_domain=status.api_domain,
        has_refresh_token=status.has_refresh_token,
        client_id_suffix=status.client_id_suffix,
    )


def _build_job_id(building_name: str) -> str:
    return f"{utc_timestamp()}-{sanitize_filename(building_name, default='site-and-password')}"


def _run_job(job_id: str, raw_payload: dict, batch) -> None:
    try:
        job_store.mark_running(job_id)
        pipeline = SiteWorkflowPipeline(settings, logger)
        result = pipeline.process(job_id, raw_payload, batch)
    except Exception as exc:  # pragma: no cover - runtime failure depends on downstream services
        logger.exception("Workflow job %s failed", job_id)
        job_store.mark_failed(job_id, str(exc))
    else:
        job_store.mark_succeeded(job_id, result)
        logger.info("Workflow job %s completed", job_id)


def _upload_omada_live_site_artifacts(workdrive_folder_id: str, omada_job: dict[str, Any]) -> list[dict[str, Any]]:
    report = omada_job.get("report")
    if not isinstance(report, dict):
        return []

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        return []

    workdrive_client = WorkflowWorkDriveClient(settings.zoho_oauth, logger)
    uploads: list[dict[str, Any]] = []

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("type", "")).strip() != "live-site-yaml":
            continue

        artifact_name = str(artifact.get("name", "")).strip() or "live-site.yaml"
        artifact_content = artifact.get("content")
        if isinstance(artifact_content, str):
            encoding = str(artifact.get("contentEncoding", "utf-8") or "utf-8")
            upload_result = workdrive_client.upload_bytes(
                artifact_content.encode(encoding),
                artifact_name,
                workdrive_folder_id,
                content_type="application/x-yaml",
            )
        else:
            artifact_path = Path(str(artifact.get("path", "")).strip())
            if not artifact_path.exists():
                logger.warning("Omada live-site artifact path is missing: %s", artifact_path)
                continue
            upload_result = workdrive_client.upload_file(artifact_path, workdrive_folder_id)
        upload_result["artifact_type"] = "live-site-yaml"
        uploads.append(upload_result)

    return uploads


def _watch_omada_workdrive_job(job_id: str, workdrive_folder_id: str) -> None:
    try:
        omada_job = OmadaClient(settings.omada).wait_for_completion(job_id)
        if str(omada_job.get("status", "")).lower() != "success":
            logger.info("Omada WorkDrive job %s finished without success. Skipping live-site upload.", job_id)
            return

        uploads = _upload_omada_live_site_artifacts(workdrive_folder_id, omada_job)
        if uploads:
            logger.info("Omada WorkDrive job %s uploaded %d live-site artifact(s).", job_id, len(uploads))
    except Exception:
        logger.exception("Omada WorkDrive job %s live-site upload watcher failed", job_id)


def _upload_omada_plan_artifacts(
    workdrive_client: WorkflowWorkDriveClient,
    *,
    workdrive_folder_id: str,
    operation: str,
    plan_text: str,
    plan_file_name: str,
) -> list[dict[str, Any]]:
    uploads: list[dict[str, Any]] = []
    operation_file_name = operation_plan_filename(operation)
    encoded_plan = plan_text.encode("utf-8")

    uploads.append(
        workdrive_client.upload_bytes(
            encoded_plan,
            "omada-plan.yaml",
            workdrive_folder_id,
            content_type="application/x-yaml",
        )
    )

    if operation_file_name != "omada-plan.yaml":
        uploads.append(
            workdrive_client.upload_bytes(
                encoded_plan,
                operation_file_name,
                workdrive_folder_id,
                content_type="application/x-yaml",
            )
        )
    elif plan_file_name != "omada-plan.yaml":
        uploads.append(
            workdrive_client.upload_bytes(
                encoded_plan,
                plan_file_name,
                workdrive_folder_id,
                content_type="application/x-yaml",
            )
        )

    return uploads


def _health_payload() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app="workflow-api",
        version=API_VERSION,
        jobs_dir=str(settings.output.jobs_dir),
        pdf_base_url=settings.pdf.base_url,
        omada_base_url=settings.omada.base_url,
    )


@app.get("/", response_model=PlatformIndexResponse, tags=["platform"])
@app.get("/api", response_model=PlatformIndexResponse, tags=["platform"])
async def platform_index() -> PlatformIndexResponse:
    return PlatformIndexResponse(
        name="Opticable API Platform",
        version=API_VERSION,
        docs_url=PLATFORM_DOCS_PATH,
        openapi_url=PLATFORM_OPENAPI_PATH,
        primary_webhook=PRIMARY_WEBHOOK_PATH,
        canonical_workflow=WORKFLOW_CANONICAL_PATH,
        services=_service_catalog(),
    )


@app.get("/health", response_model=HealthResponse, tags=["compatibility"])
@app.get("/v1/system/health", response_model=HealthResponse, tags=["platform"])
async def health() -> HealthResponse:
    return _health_payload()


@app.get("/v1/system/catalog", response_model=PlatformIndexResponse, tags=["platform"])
async def platform_catalog() -> PlatformIndexResponse:
    return await platform_index()


@app.get('/v1/system/readiness', tags=['platform'])
async def system_readiness(x_api_key: str | None = Header(default=None, alias='X-API-Key')):
    _validate_inspection_api_key(x_api_key)
    return await run_in_threadpool(_readiness_payload)

@app.get("/v1/system/providers", tags=["platform"])
async def provider_inventory(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)

    errors: dict[str, str] = {}

    def safe(provider: str, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            errors[provider] = type(exc).__name__
            return fallback

    zoho_status = safe("zoho", lambda: _zoho_oauth_manager().status(), None)
    google_status = safe("google_admin", lambda: google_oauth_manager.status(), None)

    github_auth_mode = safe("github", lambda: github_api_client.auth_mode, "unconfigured")
    github_configured = safe("github", lambda: github_api_client.configured, False)
    cloudflare_configured = safe("cloudflare", lambda: cloudflare_api_client.configured, False)
    apollo_configured = safe("apollo", lambda: apollo_api_client.configured, False)
    windsor_configured = safe("windsor", lambda: windsor_api_client.configured, False)
    ovh_configured = safe("ovhcloud", lambda: ovh_api_client.configured, False)
    ai_configured = safe(
        "ai",
        lambda: ai_router.configured(),
        {"openai": False, "anthropic": False, "gemini": False},
    )

    return {
        "master": "optibrain.opticable.ca",
        "standby": {
            "connect.opticable.ca": {
                "mode": "manual",
                "enabled": settings.zoho_gateway.standby_enabled,
            }
        },
        "providers": {
            "zoho": {
                "primary": "local_oauth",
                "configured": zoho_status.configured if zoho_status is not None else settings.zoho_oauth.enabled,
                "connected": zoho_status.connected if zoho_status is not None else False,
                "configured_scope_count": len(zoho_status.scopes) if zoho_status is not None else len(settings.zoho_oauth.scopes),
                "granted_scope_count": len(
                    [scope for scope in (zoho_status.scope or "").replace(" ", ",").split(",") if scope.strip()]
                ) if zoho_status is not None else 0,
                "standby_enabled": settings.zoho_gateway.standby_enabled,
                "status_error": errors.get("zoho"),
            },
            "google_admin": {
                "primary": "local_oauth",
                "configured": google_status.configured if google_status is not None else settings.google_oauth.enabled,
                "connected": google_status.connected if google_status is not None else False,
                "scope_count": len(google_status.scopes) if google_status is not None else len(settings.google_oauth.scopes),
                "services": sorted(GOOGLE_SERVICE_BASES),
                "status_error": errors.get("google_admin"),
            },
            "windsor": {
                "primary": "direct_api",
                "configured": windsor_configured,
                "purpose": "marketing_ads_organic_analytics_broker",
                "status_error": errors.get("windsor"),
            },
            "ovhcloud": {
                "primary": "direct_signed_api",
                "configured": ovh_configured,
                "endpoint": settings.ovh.endpoint,
                "status_error": errors.get("ovhcloud"),
            },
            "github": {
                "primary": "github_app" if github_auth_mode == "github_app" else "direct_api",
                "configured": github_configured,
                "auth_mode": github_auth_mode,
                "owner": settings.github.owner,
                "app_id": settings.github.app_id,
                "installation_id": settings.github.installation_id,
                "note": "Read-only deploy key remains separate for code checkout.",
                "status_error": errors.get("github"),
            },
            "cloudflare": {
                "primary": "direct_api",
                "configured": cloudflare_configured,
                "account_id_suffix": settings.cloudflare.account_id[-6:] if settings.cloudflare.account_id else None,
                "status_error": errors.get("cloudflare"),
            },
            "apollo": {
                "primary": "direct_api",
                "configured": apollo_configured,
                "credit_consumption_enabled": settings.apollo.allow_credit_consumption,
                "status_error": errors.get("apollo"),
            },
            "openai": {
                "primary": "direct_api",
                "configured": ai_configured.get("openai", False),
                "model_configured": settings.ai.openai_model is not None,
                "status_error": errors.get("ai"),
            },
            "anthropic": {
                "primary": "direct_api",
                "configured": ai_configured.get("anthropic", False),
                "model_configured": settings.ai.anthropic_model is not None,
                "status_error": errors.get("ai"),
            },
            "gemini": {
                "primary": "direct_api",
                "configured": ai_configured.get("gemini", False),
                "model_configured": settings.ai.gemini_model is not None,
                "status_error": errors.get("ai"),
            },
        },
        "inventory_errors": errors,
    }



@app.get("/v1/site-and-password/health", response_model=HealthResponse, tags=["site-and-password"])
async def workflow_health() -> HealthResponse:
    return _health_payload()


@app.get("/v1/automation/capabilities", tags=["automation"])
async def automation_capabilities(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    records = load_capabilities(settings.automation.capabilities_path)
    return {
        "enabled": settings.automation.enabled,
        "summary": capability_summary(records),
        "capabilities": [record.model_dump() for record in records],
    }


@app.get("/v1/automation/actions", tags=["automation"])
async def automation_actions(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return {"actions": automation_engine.action_names()}


@app.get("/v1/automation/workflows", tags=["automation"])
async def automation_workflows(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return {"workflows": automation_store.list_workflows()}


@app.post("/v1/automation/workflows/reload", tags=["automation"])
async def automation_reload_workflows(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled.")
    loaded = automation_engine.sync_definitions()
    automation_store.audit(
        category="configuration",
        action="workflows_reloaded",
        actor="api",
        success=True,
        metadata={"workflow_ids": loaded},
    )
    return {"loaded": loaded, "count": len(loaded)}


@app.post("/v1/automation/events", response_model=EventIngestResponse, tags=["automation"])
async def automation_ingest_event(
    event: AutomationEvent,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> EventIngestResponse:
    _validate_inspection_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled.")
    try:
        return await run_in_threadpool(automation_engine.ingest, event)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/lifecycle/leads", response_model=EventIngestResponse, tags=["automation"])
async def lifecycle_ingest_lead(
    payload: LeadIntakeRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> EventIngestResponse:
    _validate_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled.")

    raw = payload.model_dump(exclude_none=True)
    event = AutomationEvent(
        event_type="customer.lifecycle.lead.received",
        source=payload.source,
        occurred_at=payload.occurred_at or utc_timestamp(),
        idempotency_key=lead_event_idempotency_key(raw),
        payload=raw,
    )
    try:
        return await run_in_threadpool(automation_engine.ingest, event)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/lifecycle/emails", response_model=EventIngestResponse, tags=["automation"])
async def lifecycle_ingest_email(
    payload: EmailIntakeRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> EventIngestResponse:
    _validate_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled.")
    raw = payload.model_dump(exclude_none=True)
    event = AutomationEvent(
        event_type="customer.lifecycle.email.received",
        source=payload.source,
        occurred_at=payload.received_at or utc_timestamp(),
        idempotency_key=email_event_idempotency_key(raw),
        payload=raw,
    )
    return await run_in_threadpool(automation_engine.ingest, event)


@app.post("/v1/lifecycle/meetings", response_model=EventIngestResponse, tags=["automation"])
async def lifecycle_create_meeting(
    payload: MeetingRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> EventIngestResponse:
    _validate_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled.")
    raw = payload.model_dump(exclude_none=True)
    event = AutomationEvent(
        event_type="customer.lifecycle.meeting.requested",
        source=payload.source,
        idempotency_key=(
            f"meeting:{payload.contact_id or 'none'}:{payload.deal_id or 'none'}:"
            f"{payload.start_datetime}:{payload.end_datetime}:{payload.title}"
        ),
        payload=raw,
    )
    return await run_in_threadpool(automation_engine.ingest, event)


@app.post("/v1/automation/smoke-test", response_model=EventIngestResponse, tags=["automation"])
async def automation_smoke_test(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> EventIngestResponse:
    _validate_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled.")
    event = AutomationEvent(
        event_type="system.automation.smoke_test",
        source="internal",
        idempotency_key=f"manual-smoke:{utc_timestamp()}",
        payload={"requested_via": "api"},
    )
    return await run_in_threadpool(automation_engine.ingest, event)


class DesiredStateApplyRequest(BaseModel):
    model_config = {"extra": "forbid"}
    document: DesiredStateDocument
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=3, max_length=500)


@app.get("/v1/automation/desired-state/adapters", tags=["automation"])
async def automation_desired_state_adapters(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _validate_inspection_api_key(x_api_key)
    return {"adapters": desired_state_registry.list_adapters()}


@app.post("/v1/automation/desired-state/validate", tags=["automation"])
async def automation_desired_state_validate(document: DesiredStateDocument,
        x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _validate_inspection_api_key(x_api_key)
    # Validation is local, without provider calls.
    try:
        return {"valid": True, "document_hash": desired_state_controller.validate_document(document)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/v1/automation/desired-state/plan", response_model=DesiredPlan, tags=["automation"])
@app.post("/v1/automation/desired-state/drift", response_model=DesiredPlan, tags=["automation"])
async def automation_desired_state_plan(document: DesiredStateDocument,
        x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _validate_inspection_api_key(x_api_key)
    try:
        return await run_in_threadpool(desired_state_controller.plan, document)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/v1/automation/desired-state/apply", tags=["automation"])
async def automation_desired_state_apply(payload: DesiredStateApplyRequest,
        x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _validate_inspection_api_key(x_api_key)
    if not settings.automation.enabled:
        raise HTTPException(status_code=503, detail="Automation kernel is disabled")
    try:
        plan = await run_in_threadpool(desired_state_controller.plan, payload.document)
        if plan.plan_hash != payload.plan_hash:
            raise HTTPException(status_code=409, detail="Stale plan digest; review a fresh plan")
        results = await run_in_threadpool(desired_state_controller.apply, payload.document, plan,
                                        low_risk_additive_only=True, actor="authenticated-api")
    except ApplyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"document": payload.document.name, "plan_hash": plan.plan_hash,
            "results": [r.model_dump() for r in results], "changed": sum(r.changed for r in results),
            "failed_or_blocked": sum(r.status != "completed" for r in results)}


@app.get("/v1/automation/desired-state/last-apply", tags=["automation"])
async def automation_desired_state_last_apply(document: str = Query(min_length=1, max_length=200),
        x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _validate_inspection_api_key(x_api_key)
    return {"last_apply": desired_state_controller.journal.last(document, ("apply_result",))}


@app.get("/v1/automation/desired-state/inventory", tags=["automation"])
async def automation_desired_state_inventory(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _validate_inspection_api_key(x_api_key)
    return await run_in_threadpool(CrmInventoryCollector(zoho_gateway_client).collect)


@app.get("/v1/automation/runs", tags=["automation"])
async def automation_runs(
    limit: int = Query(default=50, ge=1, le=200),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return {"runs": automation_store.recent_runs(limit)}


@app.get("/v1/automation/execution-health", tags=["automation"])
async def automation_execution_health(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    snapshot: dict[str, Any] = automation_store.execution_health()
    snapshot["recovery_worker"] = _automation_recovery_health()
    return snapshot


@app.get("/v1/automation/health-alerts", tags=["automation"])
async def automation_health_alerts(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    # A fresh inspector ensures tests and future store swaps use the current store.
    monitor = AutomationHealthMonitor(automation_store, sync_health=lambda: delta_sync_worker.health())
    return monitor.inspect(_automation_recovery_health())


@app.get("/v1/automation/native-notifications", tags=["automation"])
async def automation_native_notifications(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return native_health(automation_store)


@app.get("/v1/automation/failed-work", tags=["automation"])
async def automation_failed_work(
    limit: int = Query(default=50, ge=1, le=100),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return {"runs": automation_store.failed_work(limit)}


@app.get("/v1/automation/runs/{run_id}/failures", tags=["automation"])
async def automation_run_failures(
    run_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    if not automation_store.run_exists(run_id):
        raise HTTPException(status_code=404, detail="Automation run not found.")
    return {"failures": automation_store.failure_history(run_id, limit)}


@app.post("/v1/automation/runs/{run_id}/redrive", tags=["automation"])
async def automation_redrive_run(
    run_id: str,
    payload: AutomationRedriveRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    try:
        return AutomationMaintenance(automation_store).redrive(
            run_id,
            actor="api",
            reason=payload.reason,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail="Automation run not found.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/automation/maintenance/cleanup-terminal-claims",
    tags=["automation"],
)
async def automation_cleanup_terminal_claims(
    payload: AutomationCleanupRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return AutomationMaintenance(automation_store).cleanup_terminal_claims(
        retention_days=payload.retention_days,
        limit=payload.limit,
        actor="api",
        reason=payload.reason,
    )


@app.get("/v1/automation/runs/{run_id}", tags=["automation"])
async def automation_run(
    run_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    run = automation_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Automation run not found.")
    return run


@app.get("/v1/automation/audit", tags=["automation"])
async def automation_audit(
    limit: int = Query(default=100, ge=1, le=500),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_inspection_api_key(x_api_key)
    return {"audit": automation_store.recent_audit(limit)}


@app.get("/v1/omada/sites", response_model=OmadaSitesResponse, tags=["omada"])
async def omada_list_sites(
    search: str | None = Query(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    return OmadaClient(settings.omada).list_sites(search)


@app.get("/v1/omada/sites/{site_id}", response_model=OmadaSiteResponse, tags=["omada"])
async def omada_get_site(
    site_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    return OmadaClient(settings.omada).get_site(site_id)


@app.get("/v1/omada/sites/{site_id}/lans", response_model=OmadaLansResponse, tags=["omada"])
async def omada_list_lans(
    site_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    return OmadaClient(settings.omada).list_lans(site_id)


@app.get("/v1/omada/sites/{site_id}/wlan-groups", response_model=OmadaWlanGroupsResponse, tags=["omada"])
async def omada_list_wlan_groups(
    site_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    return OmadaClient(settings.omada).list_wlan_groups(site_id)


@app.get("/v1/omada/sites/{site_id}/wlan-groups/{wlan_id}/ssids", response_model=OmadaSsidsResponse, tags=["omada"])
async def omada_list_ssids(
    site_id: str,
    wlan_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    return OmadaClient(settings.omada).list_ssids(site_id, wlan_id)


@app.get("/v1/omada/sites/{site_id}/snapshot", tags=["omada"])
async def omada_get_site_snapshot(
    site_id: str,
    format: Literal["json", "yaml"] = Query(default="json"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _validate_api_key(x_api_key)

    client = OmadaClient(settings.omada)
    site_response = client.get_site(site_id)
    lans_response = client.list_lans(site_id)
    wlan_groups_response = client.list_wlan_groups(site_id)

    wlan_groups: list[dict[str, Any]] = []
    for group in wlan_groups_response.get("items", []):
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            continue
        ssid_response = client.list_ssids(site_id, group_id)
        wlan_groups.append(
            {
                "id": group_id,
                "name": str(group.get("name", "")),
                "ssids": [
                    {
                        "id": str(ssid.get("id", "")),
                        "name": str(ssid.get("name", "")),
                        "password": None,
                    }
                    for ssid in ssid_response.get("items", [])
                ],
            }
        )

    snapshot = build_live_snapshot(
        site=site_response.get("site", {}),
        lans=lans_response.get("items", []),
        wlan_groups=wlan_groups,
    )

    if format == "yaml":
        return PlainTextResponse(
            yaml.safe_dump(snapshot, sort_keys=False, allow_unicode=False),
            media_type="application/yaml",
        )

    return OmadaSiteSnapshotResponse.model_validate(snapshot)


@app.get("/v1/omada/jobs/{job_id}", tags=["omada"])
async def omada_get_job(
    job_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    return OmadaClient(settings.omada).get_job(job_id)


@app.post("/v1/omada/jobs", response_model=OmadaJobAcceptedResponse, tags=["omada"])
async def omada_create_job(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_plan_file_name: str | None = Header(default=None, alias="X-Plan-File-Name"),
) -> OmadaJobAcceptedResponse:
    _validate_api_key(x_api_key)

    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="Request body cannot be empty.")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip() or None
    response = OmadaClient(settings.omada).create_job_from_raw(body, content_type, x_plan_file_name)
    job = response.get("job")
    if not isinstance(job, dict):
        raise HTTPException(status_code=502, detail="Omada service returned an unexpected job payload.")

    job_id = str(job.get("id")) if job.get("id") is not None else None
    return OmadaJobAcceptedResponse(
        status="accepted",
        job_id=job_id,
        job_status_url=f"/v1/omada/jobs/{job_id}" if job_id else None,
        job=job,
    )


@app.post("/v1/omada/workdrive/jobs", response_model=OmadaWorkDriveJobAcceptedResponse, tags=["omada"])
async def omada_create_job_from_workdrive(
    payload: OmadaWorkDriveJobRequest = Body(..., openapi_examples=OMADA_WORKDRIVE_JOB_EXAMPLES),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> OmadaWorkDriveJobAcceptedResponse:
    _validate_api_key(x_api_key)

    workdrive_client = WorkflowWorkDriveClient(settings.zoho_oauth, logger)
    try:
        resolved = resolve_workdrive_execution_source(
            workdrive_client,
            parent_folder_id=payload.workdrive_folder_id,
            operation=payload.operation,
            source_preference=payload.source_preference,
            settings=settings,
            building_name=payload.building_name,
            site_name=payload.site_name,
            city=payload.city,
            template_name=payload.template_name,
            omada_region=payload.omada_region,
            omada_timezone=payload.omada_timezone,
            omada_scenario=payload.omada_scenario,
        )
    except (WorkflowWorkDriveError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        _upload_omada_plan_artifacts(
            workdrive_client,
            workdrive_folder_id=payload.workdrive_folder_id,
            operation=payload.operation,
            plan_text=resolved.plan_text,
            plan_file_name=resolved.plan_file_name,
        )
    except WorkflowWorkDriveError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to upload Omada plan artifacts to WorkDrive: {exc}") from exc

    response = OmadaClient(settings.omada).create_job_from_raw(
        resolved.plan_text.encode("utf-8"),
        "application/x-yaml",
        resolved.plan_file_name,
    )
    job = response.get("job")
    if not isinstance(job, dict):
        raise HTTPException(status_code=502, detail="Omada service returned an unexpected job payload.")

    job_id = str(job.get("id")) if job.get("id") is not None else None
    if job_id:
        threading.Thread(
            target=_watch_omada_workdrive_job,
            args=(job_id, payload.workdrive_folder_id),
            daemon=True,
        ).start()

    return OmadaWorkDriveJobAcceptedResponse(
        status="accepted",
        operation=payload.operation,
        source_type=resolved.source_type,
        source_file_name=resolved.file_name,
        source_file_id=resolved.file_id,
        source_folder_id=resolved.folder_id,
        building_name=resolved.building_name,
        site_name=resolved.site_name,
        job_id=job_id,
        job_status_url=f"/v1/omada/jobs/{job_id}" if job_id else None,
        job=job,
    )


@app.get(GOOGLE_OAUTH_STATUS_PATH, response_model=GoogleOAuthStatusResponse, tags=["integrations"])
async def google_oauth_status(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
) -> GoogleOAuthStatusResponse:
    _validate_browser_or_header_api_key(x_api_key, api_key)
    return _google_status_payload()


@app.get(GOOGLE_OAUTH_START_PATH, response_model=GoogleOAuthConnectResponse, tags=["integrations"])
async def google_oauth_start(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
    response_mode: str = Query(default="redirect", pattern="^(redirect|json)$"),
):
    _validate_browser_or_header_api_key(x_api_key, api_key)
    try:
        authorization_url = google_oauth_manager.build_authorization_redirect()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if response_mode == "json":
        return GoogleOAuthConnectResponse(
            status="ready",
            authorization_url=authorization_url,
            callback_url=GOOGLE_OAUTH_CALLBACK_PATH,
        )
    return RedirectResponse(authorization_url, status_code=307)


@app.get(GOOGLE_OAUTH_CALLBACK_PATH, tags=["integrations"])
async def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    response_mode: str = Query(default="html", pattern="^(html|json)$"),
):
    if error:
        detail = error_description or error
        raise HTTPException(status_code=400, detail=f"Google authorization failed: {detail}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Google callback is missing the authorization code or state.")
    try:
        google_oauth_manager.validate_state(state)
        token_payload = google_oauth_manager.exchange_code(code)
        credentials_path = google_oauth_manager.save_credentials(token_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    status_payload = GoogleOAuthCallbackResponse(
        status="connected",
        connected=True,
        credentials_path=str(credentials_path),
        scope=str(token_payload.get("scope")) if token_payload.get("scope") else None,
    )
    automation_store.audit(
        category="integration",
        action="google_oauth_connected",
        actor="oauth",
        success=True,
        target="google",
        metadata={"scope": status_payload.scope},
    )
    if response_mode == "json":
        return status_payload.model_dump()
    return HTMLResponse(
        content=(
            "<html><body style='font-family:sans-serif;padding:2rem;line-height:1.5'>"
            "<h1>Google Admin APIs connected</h1>"
            "<p>Google Tag Manager and Google Analytics Admin authorization was stored successfully.</p>"
            "<p>You can close this window and return to ChatGPT.</p>"
            "</body></html>"
        ),
        status_code=200,
    )


@app.api_route(
    "/v1/google/{service}/{resource_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    tags=["integrations"],
)
async def google_admin_api(
    request: Request,
    service: str,
    resource_path: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_change_reason: str | None = Header(default=None, alias="X-Change-Reason"),
):
    _validate_api_key(x_api_key)
    method = request.method.upper()
    if service not in GOOGLE_SERVICE_BASES:
        raise HTTPException(status_code=404, detail=f"Unsupported Google service: {service}")

    body: Any = None
    if method in {"POST", "PUT", "PATCH"}:
        raw = await request.body()
        if raw:
            try:
                body = await request.json()
            except Exception as exc:
                raise HTTPException(status_code=422, detail="Google API mutation body must be JSON.") from exc

    if method != "GET" and not (x_change_reason or "").strip():
        raise HTTPException(status_code=422, detail="X-Change-Reason is required for Google API mutations.")

    params = dict(request.query_params)
    correlation_id = request.headers.get("X-Correlation-ID")
    try:
        result = google_api_client.request(
            service,
            method,
            resource_path,
            params=params,
            body=body,
        )
    except (ValueError, GoogleApiError) as exc:
        if method != "GET":
            automation_store.audit(
                category="provider_mutation",
                action=f"google.{service}.{method.lower()}",
                actor="api",
                success=False,
                correlation_id=correlation_id,
                target=resource_path,
                metadata={"reason": x_change_reason, "error": str(exc)},
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if method != "GET":
        automation_store.audit(
            category="provider_mutation",
            action=f"google.{service}.{method.lower()}",
            actor="api",
            success=True,
            correlation_id=correlation_id,
            target=resource_path,
            metadata={
                "reason": x_change_reason,
                "status": result.get("status"),
                "body_keys": sorted(body.keys()) if isinstance(body, dict) else [],
            },
        )
    return result


@app.get("/v1/integrations/zoho-gateway/status", tags=["integrations"])
async def zoho_gateway_status(
    verify: bool = Query(default=False),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _validate_api_key(x_api_key)
    payload: dict[str, Any] = {
        "configured": zoho_gateway_client.configured,
        "base_url": settings.zoho_gateway.base_url,
        "uses_centralized_oauth": True,
    }
    if not verify or not zoho_gateway_client.configured:
        return payload
    try:
        result = zoho_gateway_client.request(
            "zohoapis",
            "GET",
            "/crm/v8/org",
        )
        payload["verified"] = bool(result.get("ok"))
        payload["provider_status"] = result.get("status")
    except Exception as exc:
        payload["verified"] = False
        payload["error"] = str(exc)
    return payload


@app.get(ZOHO_OAUTH_STATUS_PATH, response_model=ZohoOAuthStatusResponse, tags=["integrations"])
async def zoho_oauth_status(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
) -> ZohoOAuthStatusResponse:
    _validate_browser_or_header_api_key(x_api_key, api_key)
    return _zoho_status_payload()


@app.get(ZOHO_OAUTH_START_PATH, response_model=ZohoOAuthConnectResponse, tags=["integrations"])
async def zoho_oauth_start(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
    response_mode: str = Query(default="redirect", pattern="^(redirect|json)$"),
):
    _validate_browser_or_header_api_key(x_api_key, api_key)

    manager = _zoho_oauth_manager()
    try:
        authorization_url = manager.build_authorization_redirect()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if response_mode == "json":
        return ZohoOAuthConnectResponse(
            provider="zoho",
            status="ready",
            authorization_url=authorization_url,
            callback_url=ZOHO_OAUTH_CALLBACK_PATH,
        )

    return RedirectResponse(authorization_url, status_code=307)


@app.get(ZOHO_OAUTH_CALLBACK_PATH, tags=["integrations"])
async def zoho_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    response_mode: str = Query(default="html", pattern="^(html|json)$"),
):
    manager = _zoho_oauth_manager()
    if error:
        detail = error_description or error
        raise HTTPException(status_code=400, detail=f"Zoho authorization failed: {detail}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Zoho callback is missing the authorization code or state.")

    try:
        manager.validate_state(state)
        token_payload = manager.exchange_code(code)
        credentials_path = manager.save_credentials(token_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    status_payload = ZohoOAuthCallbackResponse(
        provider="zoho",
        status="connected",
        connected=True,
        credentials_path=str(credentials_path),
        scope=str(token_payload.get("scope")) if token_payload.get("scope") else None,
        api_domain=str(token_payload.get("api_domain")) if token_payload.get("api_domain") else None,
    )

    if response_mode == "json":
        return status_payload.model_dump()

    html = f"""
<html>
  <head><title>Zoho Connected</title></head>
  <body style="font-family: sans-serif; padding: 2rem; line-height: 1.5;">
    <h1>Zoho Connected</h1>
    <p>The server stored the Zoho OAuth credentials successfully.</p>
    <p>Credentials path: <code>{status_payload.credentials_path}</code></p>
    <p>Next check: <code>{ZOHO_OAUTH_STATUS_PATH}</code></p>
  </body>
</html>
"""
    return HTMLResponse(content=html, status_code=200)


@app.get("/jobs/{job_id}", response_model=JobLookupResponse, tags=["compatibility"])
@app.get(PRIMARY_JOB_STATUS_PATH, response_model=JobLookupResponse, tags=["site-and-password"])
@app.get(WORKFLOW_CANONICAL_JOB_STATUS_PATH, response_model=JobLookupResponse, tags=["site-and-password"])
async def get_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _create_job_from_payload(payload: dict[str, Any]) -> WorkflowJobAcceptedResponse:
    try:
        batch = parse_payload(payload, settings)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_id = _build_job_id(batch.building_name)
    job_store.create(
        job_id,
        {
            "building_name": batch.building_name,
            "record_count": len(batch.records),
            "credential_mode": batch.credential_mode,
            "workflow_mode": batch.workflow_mode,
            "omada_operation": batch.omada_operation,
            "template_name": batch.template_name,
            "site_name": batch.site_name or batch.building_name,
        },
    )

    worker = threading.Thread(target=_run_job, args=(job_id, payload, batch), daemon=True)
    worker.start()

    return WorkflowJobAcceptedResponse(
        status="accepted",
        job_id=job_id,
        building_name=batch.building_name,
        record_count=len(batch.records),
        credential_mode=batch.credential_mode,
        workflow_mode=batch.workflow_mode,
        omada_operation=batch.omada_operation,
        job_status_url=WORKFLOW_CANONICAL_JOB_STATUS_PATH.replace("{job_id}", job_id),
    )


@app.post(PRIMARY_JOB_CREATE_PATH, response_model=WorkflowJobAcceptedResponse, tags=["site-and-password"])
@app.post(WORKFLOW_CANONICAL_PATH, response_model=WorkflowJobAcceptedResponse, tags=["site-and-password"])
@app.post("/webhooks/zoho/site-and-password", response_model=WorkflowJobAcceptedResponse, tags=["compatibility"])
@app.post("/webhooks/zoho/site-workflow", response_model=WorkflowJobAcceptedResponse, tags=["compatibility"])
@app.post("/v1/site-and-password/webhooks/zoho", response_model=WorkflowJobAcceptedResponse, tags=["site-and-password"])
async def create_site_workflow_job(
    payload: dict[str, Any] = Body(..., openapi_examples=WORKFLOW_PAYLOAD_EXAMPLES),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> WorkflowJobAcceptedResponse:
    _validate_api_key(x_api_key)

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Payload must be a JSON object.")

    return _create_job_from_payload(payload)
