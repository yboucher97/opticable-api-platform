> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](../../docs/OPTIBRAIN_CODEX_ONBOARDING.md).

# Workflow API

This app is the orchestration layer inside the monorepo. It sits in front of:

- `apps/password-pdf-service`
- `apps/omada-site-service`

## Flow

1. receive the inbound webhook
2. normalize the payload
3. generate SSIDs and passwords if `credential_mode=generated`
4. always build `omada-plan.yaml`
5. always build the operation-specific plan file like `create.yaml`, `upsert.yaml`, or `update.yaml`
6. if the workflow includes PDFs, call the PDF generator
7. if the workflow includes PDFs, wait for PDF generation and WorkDrive upload to finish
8. if `workdrive_folder_id` is present, upload `omada-plan.yaml` and the operation-specific plan to WorkDrive
9. if the workflow includes Omada, call Omada site creation
10. after successful Omada execution, refresh `live-site.yaml`

## Endpoints

- `GET /`
- `GET /api`
- `GET /docs`
- `GET /openapi.json`
- `GET /v1/system/health`
- `GET /v1/system/catalog`
- `GET /v1/integrations/zoho/oauth/start`
- `GET /v1/integrations/zoho/oauth/callback`
- `GET /v1/integrations/zoho/oauth/status`
- `GET /v1/omada/sites`
- `GET /v1/omada/sites/{site_id}`
- `GET /v1/omada/sites/{site_id}/lans`
- `GET /v1/omada/sites/{site_id}/wlan-groups`
- `GET /v1/omada/sites/{site_id}/wlan-groups/{wlan_id}/ssids`
- `GET /v1/omada/sites/{site_id}/snapshot`
- `POST /v1/omada/jobs`
- `POST /v1/omada/workdrive/jobs`
- `GET /v1/omada/jobs/{job_id}`
- `POST /v1/workflows/site-and-password`
- `GET /v1/workflows/site-and-password/jobs/{job_id}`
- `GET /v1/site-and-password/health`
- `GET /v1/site-and-password/jobs/{job_id}`
- `POST /v1/site-and-password/jobs`
- `POST /v1/site-and-password/webhooks/zoho`
- `GET /health`
- `GET /jobs/{job_id}`
- `POST /webhooks/zoho/site-and-password`
- `POST /webhooks/zoho/site-workflow`

The unversioned paths and the older `/v1/site-and-password/*` paths remain as compatibility aliases.

## Direct Omada Plan Webhook

Use `POST /v1/omada/jobs` when you already have an Omada YAML or JSON plan and want the master API host to forward it directly to the Omada service.

- send raw YAML, raw JSON, or a JSON plan body
- include `X-Plan-File-Name` if you want to control the saved file name
- poll `GET /v1/omada/jobs/{job_id}` for completion

This is the clean standalone path for site-template style jobs that should not go through password/PDF generation.

## WorkDrive-Driven Omada Jobs

Use `POST /v1/omada/workdrive/jobs` when the source of truth is a WorkDrive building folder.

Current behavior:

- read the requested WorkDrive folder
- prefer `create.yaml`, `upsert.yaml`, or `omada-plan.yaml`
- if no YAML exists, fall back to the TXT credential export
- if TXT is used, build an Omada plan automatically, save the matching operation file, and submit it

Supported operation values today:

- `create`
- `upsert`
- `update`

Live reads:

- `GET /v1/omada/sites/{site_id}/snapshot`
- returns JSON by default
- `?format=yaml` returns a YAML snapshot
- passwords are intentionally `null` in this live snapshot because the current discovery flow does not expose the PSK

## Credential Modes

`generated`

- send unit numbers or identifiers
- default SSID format is `APT_<unit>_<XX>`
- passwords are generated automatically and exclude ambiguous letters like `i` and `l`

`predefined`

- send explicit SSIDs and passwords
- the workflow uses them unchanged

## Workflow Modes

`pdf_only`

- generate PDFs and exports
- upload to WorkDrive
- also generate and upload `omada-plan.yaml`
- also generate and upload the matching operation file like `create.yaml`, `upsert.yaml`, or `update.yaml`
- skip Omada

`pdf_and_site`

- generate PDFs and exports
- upload to WorkDrive
- also generate and upload `omada-plan.yaml`
- also generate and upload the matching operation file like `create.yaml`, `upsert.yaml`, or `update.yaml`
- then create the Omada site
- refresh and upload `live-site.yaml` after success

`site_only`

- skip PDFs and password documents
- still generate `omada-plan.yaml`
- upload `omada-plan.yaml` to WorkDrive when `workdrive_folder_id` is provided
- upload the matching operation file like `create.yaml`, `upsert.yaml`, or `update.yaml`
- create the Omada site directly
- refresh and upload `live-site.yaml` after success

## Omada Operation Flag

Workflow payloads can also choose the Omada mutation intent:

- `omada_operation: ensure`
- `omada_operation: create`
- `omada_operation: upsert`
- `omada_operation: update`

Practical examples:

- new-site rollout with safe reuse of missing pieces: `omada_operation=upsert`
- password rotation on an existing site: `omada_operation=update`

## Current Omada Mutation Behavior

The Omada service now supports four mutation styles at the plan level:

- `ensure`
- `create`
- `upsert`
- `update`

What is implemented today:

- sites can be required to exist, created, or reused depending on mutation mode
- LANs can be created when missing
- WLAN groups can be created when missing
- existing SSIDs can be updated in place for password, hide flag, and VLAN binding
- `update` fails if the required site, LAN, WLAN group, or SSID does not already exist

Current limitation:

- structural LAN mutation is still conservative
- WLAN-group renaming is not implemented
- if an existing LAN conflicts with the desired definition, the run fails instead of silently mutating it

For AP assignment safety:

- updating inside the same existing WLAN group is the correct approach
- deleting and recreating WLAN groups would risk changing AP assignment behavior

## Zoho OAuth

Recommended Zoho client type:

- `Server-based Application`

Important env vars:

- `ZOHO_OAUTH_CLIENT_ID`
- `ZOHO_OAUTH_CLIENT_SECRET`
- `ZOHO_OAUTH_ACCOUNTS_BASE_URL`
- `ZOHO_OAUTH_REDIRECT_URI`
- `ZOHO_OAUTH_SCOPES`
- `ZOHO_OAUTH_CREDENTIALS_PATH`

Typical callback path:

- `/v1/integrations/zoho/oauth/callback`

The workflow stores the approved Zoho OAuth credentials in the shared credential file, and the PDF service reads that file automatically on future jobs.

## Example Payload

See [example_payload.json](./input/example_payload.json).

For WorkDrive-driven Omada jobs, see [omada_workdrive_job.example.json](./input/omada_workdrive_job.example.json).

## Local Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SITE_WORKFLOW_API_KEY=replace-with-a-long-random-secret
uvicorn workflow.api:app --host 127.0.0.1 --port 8100
```

## Notes

- Default SSID prefix: `APT_`
- Default suffix length: `2`
- Default suffix casing: uppercase
- Default `workflow_mode`: `pdf_and_site`
- `omada-plan.yaml` is generated for every workflow job
- the matching operation file like `create.yaml`, `upsert.yaml`, or `update.yaml` is also generated for every workflow job
- `live-site.yaml` is refreshed after every successful Omada run
- If `credential_mode` is omitted, the workflow still infers generated vs predefined for backward compatibility
- The FastAPI Swagger docs are available at `/docs`
- The OpenAPI document is available at `/openapi.json`
