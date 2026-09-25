# Opticable API Platform

This repository is the monorepo for the Opticable API platform. It keeps one `main` branch and organizes the platform by service folders, not by branches or endpoints.

Included services:

- `apps/workflow-api`
- `apps/password-pdf-service`
- `apps/omada-site-service`

Repository docs:

- [Repository Structure](./docs/repository-structure.md)
- [Architecture](./docs/architecture.md)
- [API Blueprint](./docs/api-blueprint.md)
- [Omada Operation Strategy](./docs/omada-operation-strategy.md)
- [Deploy Notes](./deploy/README.md)

## Install On One Linux VM

Use the top-level installer to deploy the full stack from this monorepo:

```bash
sudo SITE_AND_PASSWORD_API_HOST=api01.opticable.ca \
bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/opticable-api-platform/main/install.sh)
```

What it does:

- clones or updates this repo into `/opt/opticable-api-platform`
- installs Python, Node.js, Caddy, and Playwright Chromium
- creates swap automatically on small VMs when no swap exists
- creates and enables:
  - `opticable-password-pdf.service`
  - `opticable-omada-site.service`
  - `opticable-workflow-api.service`
- creates default runtime files:
  - `/etc/opticable-password-pdf.env`
  - `/etc/opticable-password-pdf/brand_settings.json`
  - `/etc/opticable-omada-site.env`
  - `/etc/opticable-workflow-api.env`
- `/root/opticable-api-platform.generated.env`
- migrates old `password-pdf-generator`, `omada-site-creator`, and `site-and-password-workflow` runtime artifacts to the new `opticable-*` names, then removes the stale units and config files after the new services are running
- optionally writes one master Caddy site if you provide `SITE_AND_PASSWORD_API_HOST`

Important runtime paths:

- combined code: `/opt/opticable-api-platform`
- PDF data: `/var/lib/opticable-password-pdf`
- Omada data: `/var/lib/opticable-omada-site`
- Workflow data: `/var/lib/opticable-workflow-api`
- PDF config: `/etc/opticable-password-pdf/brand_settings.json`
- PDF secrets: `/etc/opticable-password-pdf.env`
- Omada secrets: `/etc/opticable-omada-site.env`
- Workflow secrets: `/etc/opticable-workflow-api.env`
- Generated runtime snapshot: `/root/opticable-api-platform.generated.env`

Optional installer variables:

- `SITE_AND_PASSWORD_API_HOST`
- `PASSWORD_PDF_API_KEY`
- `OMADA_SITE_CREATOR_WEBHOOK_TOKEN`
- `SITE_AND_PASSWORD_WORKFLOW_API_KEY`
- `PASSWORD_PDF_ENABLE_WORKDRIVE`
- `PASSWORD_PDF_ZOHO_REGION`
- `ZOHO_OAUTH_CLIENT_ID`
- `ZOHO_OAUTH_CLIENT_SECRET`
- `ZOHO_OAUTH_ACCOUNTS_BASE_URL`
- `ZOHO_OAUTH_REDIRECT_URI`
- `ZOHO_OAUTH_SCOPES`
- `ZOHO_OAUTH_CREDENTIALS_PATH`
- `AUTO_SWAP_ENABLED`
- `AUTO_SWAP_SIZE_GB`
- `ZOHO_WORKDRIVE_PARENT_FOLDER_ID`
- `OMADA_SITE_CREATOR_CLOUD_EMAIL`
- `OMADA_SITE_CREATOR_CLOUD_PASSWORD`
- `OMADA_SITE_CREATOR_DEVICE_USERNAME`
- `OMADA_SITE_CREATOR_DEVICE_PASSWORD`

## Autonomous Automation Kernel

The workflow API now includes a provider-neutral automation kernel for future Zoho, Google, Meta, Cloudflare, and browser-driven workflows.

Key properties:

- durable event intake with idempotency
- Git-versioned YAML workflows
- step retries and failure capture
- correlation/causation IDs
- SQLite/WAL durable execution state
- append-only audit history
- provider action registry
- capability grading so missing access is explicit

Primary endpoints:

- `GET /v1/automation/capabilities`
- `GET /v1/automation/actions`
- `GET /v1/automation/workflows`
- `POST /v1/automation/events`
- `POST /v1/automation/smoke-test`
- `GET /v1/automation/runs`
- `GET /v1/automation/audit`

Architecture: [Autonomous Automation Platform](./docs/autonomous-automation-platform.md)

## Included Apps

### Password PDF Service

Location: `apps/password-pdf-service`

Purpose:

- generate WiFi PDFs
- generate merged PDF, ZIP, and text exports
- upload the output to Zoho WorkDrive

### Omada Site Service

Location: `apps/omada-site-service`

Purpose:

- receive a plan file
- authenticate to TP-Link Omada
- create sites, LANs, WLAN groups, and SSIDs

### Workflow API

Location: `apps/workflow-api`

Purpose:

- receive the Zoho webhook
- decide whether credentials are generated or predefined
- run the PDF generator first
- optionally create the Omada site after PDFs succeed

## Public Endpoint Layout

With `SITE_AND_PASSWORD_API_HOST=api01.opticable.ca`, Caddy exposes:

- `https://api01.opticable.ca/`
- `https://api01.opticable.ca/docs`
- `https://api01.opticable.ca/openapi.json`
- `https://api01.opticable.ca/v1/system/health`
- `https://api01.opticable.ca/v1/system/catalog`
- `https://api01.opticable.ca/v1/integrations/zoho/oauth/start`
- `https://api01.opticable.ca/v1/integrations/zoho/oauth/callback`
- `https://api01.opticable.ca/v1/integrations/zoho/oauth/status`
- `https://api01.opticable.ca/v1/omada/sites`
- `https://api01.opticable.ca/v1/omada/sites/{siteId}`
- `https://api01.opticable.ca/v1/omada/sites/{siteId}/lans`
- `https://api01.opticable.ca/v1/omada/sites/{siteId}/wlan-groups`
- `https://api01.opticable.ca/v1/omada/sites/{siteId}/wlan-groups/{wlanId}/ssids`
- `https://api01.opticable.ca/v1/omada/sites/{siteId}/snapshot`
- `https://api01.opticable.ca/v1/omada/jobs`
- `https://api01.opticable.ca/v1/omada/workdrive/jobs`
- `https://api01.opticable.ca/v1/omada/jobs/{job_id}`
- `https://api01.opticable.ca/v1/workflows/site-and-password`
- `https://api01.opticable.ca/v1/workflows/site-and-password/jobs/{job_id}`
- `https://api01.opticable.ca/pdf/health`
- `https://api01.opticable.ca/omada/api/health`
- `https://api01.opticable.ca/workflow/health`

The root host proxies to the workflow API by default, so Zoho can post directly to the canonical workflow route:

- `https://api01.opticable.ca/v1/workflows/site-and-password`

Compatibility aliases still work:

- `https://api01.opticable.ca/v1/site-and-password/webhooks/zoho`
- `https://api01.opticable.ca/webhooks/zoho/site-and-password`
- `https://api01.opticable.ca/webhooks/zoho/site-workflow`
- `https://api01.opticable.ca/health`
- `https://api01.opticable.ca/jobs/{job_id}`

## API Documentation

The public workflow service now exposes a real OpenAPI surface:

- Swagger UI: `https://api01.opticable.ca/docs`
- OpenAPI JSON: `https://api01.opticable.ca/openapi.json`
- root platform index: `https://api01.opticable.ca/`

This gives you one documented master API endpoint for current and future webhook-driven apps.

The Omada domain now starts with GET-first discovery endpoints so callers can resolve site IDs, VLAN/LAN objects, WLAN groups, and SSIDs before using future POST actions.

The Omada domain also supports direct plan submission:

- `POST /v1/omada/jobs`
- `GET /v1/omada/jobs/{job_id}`

Use that path when you already have an Omada YAML/JSON plan and want the master API host to submit it directly.

The Omada domain also supports:

- `POST /v1/omada/workdrive/jobs`
- YAML-first, TXT-fallback WorkDrive execution

- `GET /v1/omada/sites/{siteId}/snapshot`
- `GET /v1/omada/sites/{siteId}/snapshot?format=yaml`
- live controller export for review and future update work

## Zoho OAuth

The platform now supports a proper server-side Zoho OAuth flow for WorkDrive and optional CRM access.

Recommended Zoho client type:

- `Server-based Application`

Suggested redirect URI:

- `https://api01.opticable.ca/v1/integrations/zoho/oauth/callback`

Typical setup:

1. set `ZOHO_OAUTH_CLIENT_ID` and `ZOHO_OAUTH_CLIENT_SECRET`
2. install the VM
3. open `https://api01.opticable.ca/v1/integrations/zoho/oauth/start?api_key=YOUR_WORKFLOW_API_KEY`
4. sign in to Zoho and approve access
5. the platform stores the Zoho OAuth credentials in the shared server credential file

Useful endpoints:

- `GET /v1/integrations/zoho/oauth/start`
- `GET /v1/integrations/zoho/oauth/callback`
- `GET /v1/integrations/zoho/oauth/status`

The PDF service reads the shared Zoho credential file automatically, so new tokens are picked up on the next job without restarting the stack.

## Monorepo Conventions

- `main` is the source of truth
- short-lived feature branches are for changes only, not for separating apps
- each service lives under `apps/`
- shared future code should live under `packages/`
- deployment assets belong under `deploy/` or service-local `deploy/`
- design and runbook docs belong under `docs/`

## Workflow Modes

Supported webhook flags:

- `credential_mode: generated | predefined`
- `workflow_mode: pdf_only | pdf_and_site | site_only`
- `omada_operation: ensure | create | upsert | update`

`generated`:

- send units like `101,102,103`
- the VM generates SSIDs like `APT_101_XX`
- the VM generates passwords

`predefined`:

- send final SSIDs and passwords
- the VM uses them as-is

`pdf_only`:

- creates PDFs, merged PDF, ZIP, and text export
- uploads to WorkDrive
- also writes `omada-plan.yaml` and uploads it to WorkDrive
- skips Omada

`pdf_and_site`:

- creates PDFs first
- uploads to WorkDrive
- also writes `omada-plan.yaml` and uploads it to WorkDrive
- then creates the Omada site from the same generated batch

`site_only`:

- skips PDF/password document generation
- writes `omada-plan.yaml`
- uploads `omada-plan.yaml` to WorkDrive when `workdrive_folder_id` is provided
- creates the Omada site directly

## Current Omada Update Behavior

Current Omada execution supports:

- `ensure`
- `create`
- `upsert`
- `update`

What works today:

- existing SSIDs can be updated in place
- new SSIDs, WLAN groups, and LANs can be created when allowed by the mutation mode
- password rotation can be done by generating new passwords and using `omada_operation=update`

Still conservative today:

- if an existing LAN conflicts with the desired definition, the run fails
- WLAN-group renaming is not implemented
- live snapshots should still be used to review the controller state before larger update work

That is intentional for now, because keeping an SSID inside the same existing WLAN group is the safe way to preserve AP assignment. The next build step should add explicit update modes instead of silent overwrite behavior.

## Suggested Deployment Model

- expose only the workflow/webhook entrypoint publicly
- keep the PDF generator and Omada creator on localhost behind Caddy or another reverse proxy
- run each app from its own runtime environment

## Notes

- This is the main monorepo for the combined system.
- Build artifacts, runtime data, and nested Git metadata are intentionally excluded.
- The older standalone workflow repo can be retired after you finish this migration.
