from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw.strip())


@dataclass(frozen=True)
class ApiSettings:
    api_key_env: str
    bind_host: str
    bind_port: int


@dataclass(frozen=True)
class OutputSettings:
    root_dir: Path
    jobs_dir: Path


@dataclass(frozen=True)
class DownstreamPdfSettings:
    base_url: str
    api_key: str | None
    poll_interval_seconds: int
    timeout_seconds: int


@dataclass(frozen=True)
class DownstreamOmadaSettings:
    base_url: str
    webhook_token: str
    poll_interval_seconds: int
    timeout_seconds: int
    organization_name: str
    cloud_base_url: str
    browser_channel: str
    headless: bool
    region: str
    timezone: str
    scenario: str
    device_username: str | None
    device_password: str | None


@dataclass(frozen=True)
class NamingSettings:
    ssid_prefix: str
    ssid_template: str
    ssid_suffix_length: int
    password_specials: str


@dataclass(frozen=True)
class AutomationSettings:
    enabled: bool
    root_dir: Path
    db_path: Path
    workflows_dir: Path
    capabilities_path: Path
    max_event_depth: int


@dataclass(frozen=True)
class AiProviderSettings:
    openai_api_key: str | None
    openai_model: str | None
    anthropic_api_key: str | None
    anthropic_model: str | None
    gemini_api_key: str | None
    gemini_model: str | None
    provider_order: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class GoogleOAuthSettings:
    enabled: bool
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    scopes: tuple[str, ...]
    credentials_path: Path
    state_secret: str
    state_ttl_seconds: int


@dataclass(frozen=True)
class ZohoGatewaySettings:
    base_url: str
    api_key: str | None
    timeout_seconds: int
    standby_enabled: bool


@dataclass(frozen=True)
class CloudflareSettings:
    api_token: str | None
    account_id: str | None
    timeout_seconds: int


@dataclass(frozen=True)
class GithubSettings:
    api_token: str | None
    owner: str
    timeout_seconds: int


@dataclass(frozen=True)
class ApolloSettings:
    api_key: str | None
    timeout_seconds: int
    allow_credit_consumption: bool


@dataclass(frozen=True)
class OvhSettings:
    endpoint: str
    application_key: str | None
    application_secret: str | None
    consumer_key: str | None
    timeout_seconds: int


@dataclass(frozen=True)
class WindsorSettings:
    base_url: str
    api_key: str | None
    timeout_seconds: int


@dataclass(frozen=True)
class ZohoOAuthSettings:
    enabled: bool
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    accounts_base_url: str
    scopes: tuple[str, ...]
    credentials_path: Path
    state_secret: str
    state_ttl_seconds: int


@dataclass(frozen=True)
class AppSettings:
    api: ApiSettings
    output: OutputSettings
    pdf: DownstreamPdfSettings
    omada: DownstreamOmadaSettings
    naming: NamingSettings
    automation: AutomationSettings
    ai: AiProviderSettings
    google_oauth: GoogleOAuthSettings
    zoho_gateway: ZohoGatewaySettings
    zoho_oauth: ZohoOAuthSettings
    windsor: WindsorSettings
    ovh: OvhSettings
    cloudflare: CloudflareSettings
    github: GithubSettings
    apollo: ApolloSettings


def load_settings() -> AppSettings:
    output_root = Path(os.getenv("SITE_WORKFLOW_OUTPUT_ROOT", PROJECT_ROOT / "output" / "site_workflow")).resolve()
    api_key_env = os.getenv("SITE_WORKFLOW_API_KEY_ENV", "SITE_WORKFLOW_API_KEY")
    api_key_value = os.getenv(api_key_env, "")
    zoho_scopes_raw = os.getenv(
        "ZOHO_OAUTH_SCOPES",
        "WorkDrive.files.READ,WorkDrive.files.CREATE,WorkDrive.files.UPDATE",
    )
    zoho_scopes = tuple(scope.strip() for scope in zoho_scopes_raw.split(",") if scope.strip())
    zoho_credentials_path = Path(
        os.getenv("ZOHO_OAUTH_CREDENTIALS_PATH", output_root / "integrations" / "zoho-oauth.json")
    ).resolve()
    zoho_client_id = os.getenv("ZOHO_OAUTH_CLIENT_ID")
    zoho_client_secret = os.getenv("ZOHO_OAUTH_CLIENT_SECRET")
    zoho_redirect_uri = os.getenv("ZOHO_OAUTH_REDIRECT_URI")
    zoho_accounts_base_url = os.getenv("ZOHO_OAUTH_ACCOUNTS_BASE_URL", "https://accounts.zoho.com").rstrip("/")
    zoho_state_secret = os.getenv("ZOHO_OAUTH_STATE_SECRET") or api_key_value or "workflow-api"

    google_scopes_raw = os.getenv(
        "GOOGLE_OAUTH_SCOPES",
        ",".join(
            [
                "https://www.googleapis.com/auth/analytics.edit",
                "https://www.googleapis.com/auth/analytics.readonly",
                "https://www.googleapis.com/auth/tagmanager.readonly",
                "https://www.googleapis.com/auth/tagmanager.edit.containers",
                "https://www.googleapis.com/auth/tagmanager.delete.containers",
                "https://www.googleapis.com/auth/tagmanager.edit.containerversions",
                "https://www.googleapis.com/auth/tagmanager.publish",
                "https://www.googleapis.com/auth/tagmanager.manage.accounts",
                "https://www.googleapis.com/auth/tagmanager.manage.users",
            ]
        ),
    )
    google_scopes = tuple(scope.strip() for scope in google_scopes_raw.split(",") if scope.strip())
    google_credentials_path = Path(
        os.getenv("GOOGLE_OAUTH_CREDENTIALS_PATH", output_root / "integrations" / "google-oauth.json")
    ).resolve()
    google_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    google_redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    google_state_secret = os.getenv("GOOGLE_OAUTH_STATE_SECRET") or api_key_value or "workflow-api-google"

    automation_root = Path(
        os.getenv("OPTICABLE_AUTOMATION_ROOT", output_root / "automation")
    ).resolve()
    automation_workflows_dir = Path(
        os.getenv(
            "OPTICABLE_AUTOMATION_WORKFLOWS_DIR",
            PROJECT_ROOT / "config" / "automation" / "workflows",
        )
    ).resolve()
    automation_capabilities_path = Path(
        os.getenv(
            "OPTICABLE_AUTOMATION_CAPABILITIES_PATH",
            PROJECT_ROOT / "config" / "automation" / "capabilities.yaml",
        )
    ).resolve()

    return AppSettings(
        api=ApiSettings(
            api_key_env=api_key_env,
            bind_host=os.getenv("SITE_WORKFLOW_HOST", "127.0.0.1"),
            bind_port=_env_int("SITE_WORKFLOW_PORT", 8100),
        ),
        output=OutputSettings(
            root_dir=output_root,
            jobs_dir=output_root / "jobs",
        ),
        pdf=DownstreamPdfSettings(
            base_url=os.getenv("PASSWORD_PDF_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            api_key=os.getenv("PASSWORD_PDF_API_KEY"),
            poll_interval_seconds=_env_int("PASSWORD_PDF_POLL_INTERVAL_SECONDS", 2),
            timeout_seconds=_env_int("PASSWORD_PDF_TIMEOUT_SECONDS", 600),
        ),
        omada=DownstreamOmadaSettings(
            base_url=os.getenv("OMADA_SITE_CREATOR_BASE_URL", "http://127.0.0.1:3210").rstrip("/"),
            webhook_token=os.getenv("OMADA_SITE_CREATOR_WEBHOOK_TOKEN", ""),
            poll_interval_seconds=_env_int("OMADA_SITE_CREATOR_POLL_INTERVAL_SECONDS", 2),
            timeout_seconds=_env_int("OMADA_SITE_CREATOR_TIMEOUT_SECONDS", 900),
            organization_name=os.getenv("OMADA_ORGANIZATION_NAME", "Opti-plex"),
            cloud_base_url=os.getenv("OMADA_CLOUD_BASE_URL", "https://use1-omada-cloud.tplinkcloud.com/"),
            browser_channel=os.getenv("OMADA_BROWSER_CHANNEL", "chromium"),
            headless=_env_bool("OMADA_HEADLESS", True),
            region=os.getenv("OMADA_DEFAULT_REGION", "Canada"),
            timezone=os.getenv("OMADA_DEFAULT_TIMEZONE", "America/Toronto"),
            scenario=os.getenv("OMADA_DEFAULT_SCENARIO", "Office"),
            device_username=os.getenv("OMADA_DEVICE_USERNAME"),
            device_password=os.getenv("OMADA_DEVICE_PASSWORD"),
        ),
        naming=NamingSettings(
            ssid_prefix=os.getenv("SITE_WORKFLOW_SSID_PREFIX", "APT_"),
            ssid_template=os.getenv("SITE_WORKFLOW_SSID_TEMPLATE", "{prefix}{identifier}_{suffix}"),
            ssid_suffix_length=_env_int("SITE_WORKFLOW_SSID_SUFFIX_LENGTH", 2),
            password_specials=os.getenv("SITE_WORKFLOW_PASSWORD_SPECIALS", "*!$@#"),
        ),
        automation=AutomationSettings(
            enabled=_env_bool("OPTICABLE_AUTOMATION_ENABLED", True),
            root_dir=automation_root,
            db_path=Path(
                os.getenv("OPTICABLE_AUTOMATION_DB_PATH", automation_root / "automation.db")
            ).resolve(),
            workflows_dir=automation_workflows_dir,
            capabilities_path=automation_capabilities_path,
            max_event_depth=_env_int("OPTICABLE_AUTOMATION_MAX_EVENT_DEPTH", 8),
        ),
        ai=AiProviderSettings(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            anthropic_model=os.getenv("ANTHROPIC_MODEL"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL"),
            provider_order=tuple(
                x.strip().lower()
                for x in os.getenv("OPTIBRAIN_AI_PROVIDER_ORDER", "openai,anthropic,gemini").split(",")
                if x.strip()
            ),
            timeout_seconds=_env_int("OPTIBRAIN_AI_TIMEOUT_SECONDS", 120),
        ),
        google_oauth=GoogleOAuthSettings(
            enabled=bool(google_client_id and google_client_secret and google_redirect_uri),
            client_id=google_client_id,
            client_secret=google_client_secret,
            redirect_uri=google_redirect_uri,
            scopes=google_scopes,
            credentials_path=google_credentials_path,
            state_secret=google_state_secret,
            state_ttl_seconds=_env_int("GOOGLE_OAUTH_STATE_TTL_SECONDS", 900),
        ),
        zoho_gateway=ZohoGatewaySettings(
            base_url=os.getenv("OPTICABLE_ZOHO_GATEWAY_URL", "https://connect.opticable.ca").rstrip("/"),
            api_key=os.getenv("OPTICABLE_ZOHO_GATEWAY_API_KEY"),
            timeout_seconds=_env_int("OPTICABLE_ZOHO_GATEWAY_TIMEOUT_SECONDS", 60),
            standby_enabled=_env_bool("OPTICABLE_CONNECT_STANDBY_ENABLED", False),
        ),
        cloudflare=CloudflareSettings(
            api_token=os.getenv("CLOUDFLARE_API_TOKEN"),
            account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID"),
            timeout_seconds=_env_int("CLOUDFLARE_TIMEOUT_SECONDS", 60),
        ),
        github=GithubSettings(
            api_token=os.getenv("GITHUB_API_TOKEN"),
            owner=os.getenv("GITHUB_OWNER", "yboucher97"),
            timeout_seconds=_env_int("GITHUB_TIMEOUT_SECONDS", 60),
        ),
        apollo=ApolloSettings(
            api_key=os.getenv("APOLLO_API_KEY"),
            timeout_seconds=_env_int("APOLLO_TIMEOUT_SECONDS", 60),
            allow_credit_consumption=_env_bool("OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION", False),
        ),
        ovh=OvhSettings(
            endpoint=os.getenv("OVH_ENDPOINT", "ovh-ca"),
            application_key=os.getenv("OVH_APPLICATION_KEY"),
            application_secret=os.getenv("OVH_APPLICATION_SECRET"),
            consumer_key=os.getenv("OVH_CONSUMER_KEY"),
            timeout_seconds=_env_int("OVH_TIMEOUT_SECONDS", 60),
        ),
        windsor=WindsorSettings(
            base_url=os.getenv("WINDSOR_CONNECTORS_BASE_URL", "https://connectors.windsor.ai").rstrip("/"),
            api_key=os.getenv("WINDSOR_API_KEY"),
            timeout_seconds=_env_int("WINDSOR_TIMEOUT_SECONDS", 60),
        ),
        zoho_oauth=ZohoOAuthSettings(
            enabled=bool(zoho_client_id and zoho_client_secret and zoho_redirect_uri),
            client_id=zoho_client_id,
            client_secret=zoho_client_secret,
            redirect_uri=zoho_redirect_uri,
            accounts_base_url=zoho_accounts_base_url,
            scopes=zoho_scopes,
            credentials_path=zoho_credentials_path,
            state_secret=zoho_state_secret,
            state_ttl_seconds=_env_int("ZOHO_OAUTH_STATE_TTL_SECONDS", 900),
        ),
    )
