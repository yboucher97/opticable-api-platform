> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# API Blueprint

This document defines how the public API should evolve.

## Core Rule

The public API should be organized by:

1. platform concerns
2. workflows
3. business domains

It should not be organized by internal service implementation details.

## Public API Groups

### `/v1/system/*`

Platform health, service catalog, and shared diagnostics.

Examples:

- `GET /v1/system/health`
- `GET /v1/system/catalog`

### `/v1/integrations/*`

Authentication and integration setup flows.

Examples:

- `GET /v1/integrations/zoho/oauth/start`
- `GET /v1/integrations/zoho/oauth/callback`
- `GET /v1/integrations/zoho/oauth/status`

### `/v1/workflows/*`

End-to-end business automations that may call multiple domain services internally.

Examples:

- `POST /v1/workflows/site-and-password`
- `GET /v1/workflows/site-and-password/jobs/{jobId}`

This is the correct home for one webhook that:

- generates SSIDs and passwords
- creates PDFs
- uploads to WorkDrive
- creates the Omada site

One request enters the workflow API, and the workflow API orchestrates the internal services.

### `/v1/omada/*`

Focused Omada operations.

Start with GET discovery endpoints first, then add POST creation endpoints after callers can reliably resolve IDs.

Examples:

- `GET /v1/omada/sites`
- `GET /v1/omada/sites/{siteId}`
- `GET /v1/omada/sites/{siteId}/lans`
- `GET /v1/omada/sites/{siteId}/wlan-groups`
- `GET /v1/omada/sites/{siteId}/wlan-groups/{groupId}/ssids`
- `GET /v1/omada/sites/{siteId}/snapshot`
- `POST /v1/omada/workdrive/jobs`
- `POST /v1/omada/sites`
- `POST /v1/omada/sites/{siteId}/lans`
- `POST /v1/omada/sites/{siteId}/wlan-groups`
- `POST /v1/omada/sites/{siteId}/wlan-groups/{groupId}/ssids`

### `/v1/zoho/workdrive/*`

Focused WorkDrive operations.

Examples:

- `POST /v1/zoho/workdrive/uploads`
- `GET /v1/zoho/workdrive/folders/{folderId}`
- `POST /v1/zoho/workdrive/folders/{folderId}/files`

### `/v1/zoho/crm/*`

Focused CRM operations.

Examples:

- `PATCH /v1/zoho/crm/modules/{module}/records/{recordId}`
- `POST /v1/zoho/crm/modules/{module}/records`

### `/v1/zoho/desk/*`

Focused Desk operations.

Examples:

- `POST /v1/zoho/desk/tickets/{ticketId}/close`
- `PATCH /v1/zoho/desk/tickets/{ticketId}`

## Current State

Today, the platform works like this:

1. a client posts one webhook to the workflow API
2. the workflow API normalizes the payload
3. the workflow API calls the internal PDF service
4. the PDF service generates documents and uploads to WorkDrive
5. if requested, the workflow API calls the internal Omada service

So yes, one inbound webhook currently fans out across multiple internal services.

That is correct.

The important distinction is:

- one public workflow endpoint
- multiple internal service calls

not:

- three separate public webhooks for one business action

## Internal Paths

These are implementation paths and should be treated as internal/private:

- `/pdf/*`
- `/omada/*`
- `/workflow/*`

They are useful for:

- health checks
- debugging
- local integration

They should not become the long-term public API contract for external systems unless there is a deliberate reason.

## Naming Rules

- use nouns for resources
- use verbs only when a state change does not map cleanly to normal CRUD
- keep versioning at the front: `/v1/...`
- keep provider/domain names stable
- keep workflow routes clearly separate from domain routes

## Recommended Near-Term Migration

1. keep the current workflow endpoint working
2. use `/v1/workflows/site-and-password` as the canonical workflow route
3. keep `/v1/site-and-password/*` as compatibility until callers are migrated
4. begin adding domain routes under:
   - `/v1/omada/*`
   - `/v1/zoho/workdrive/*`
   - `/v1/zoho/crm/*`
   - `/v1/zoho/desk/*`
5. continue using the workflow API as the orchestrator for multi-step automations

## Practical Example

If Zoho sends one payload with units or credentials, the correct public entrypoint is one workflow endpoint:

- `POST /v1/workflows/site-and-password`

That workflow payload can still choose the Omada mutation intent explicitly, for example:

- `omada_operation: ensure`
- `omada_operation: create`
- `omada_operation: upsert`
- `omada_operation: update`

Internally, that workflow may call:

- password generation logic
- PDF generation logic
- WorkDrive upload logic
- Omada site creation logic

That is one public API call, not three public APIs that the caller has to coordinate manually.

## Omada Artifact Strategy

For scalable Omada automation, use explicit operation and source fields instead of one endpoint per case:

- `operation: create | upsert | update | get`
- `source_preference: yaml_then_txt | yaml_only | txt_only`
- `workdrive_folder_id`

Recommended behavior:

- `POST /v1/omada/workdrive/jobs` for WorkDrive-driven site application
- `GET /v1/omada/sites/{siteId}/snapshot` for live controller export

Treat WorkDrive YAML/TXT as the source of truth for passwords. Treat live Omada discovery as the source of truth for what currently exists on the controller.
