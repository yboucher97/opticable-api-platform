> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Omada Operation Strategy

This document defines the scalable contract for Omada-triggered automation.

## Source Of Truth

Use two sources for different kinds of truth:

- WorkDrive artifacts for desired credentials and plan files
- Live Omada discovery for what currently exists on the controller

Do not treat live Omada discovery as the password source of truth. Current discovery gives you site, LAN, WLAN group, and SSID identity data, but not the current PSK in a reliable public shape.

## Recommended Public Contract

Use one Omada-focused trigger model:

- `operation`: `create | upsert | update | get`
- `source_preference`: `yaml_then_txt | yaml_only | txt_only`
- `workdrive_folder_id`
- `site_name`
- `building_name`
- optional Omada defaults:
  - `omada_region`
  - `omada_timezone`
  - `omada_scenario`

## Resolution Order

For WorkDrive-driven site application:

1. open the requested WorkDrive building folder
2. if a `Document locataire` child folder exists, read from that child
3. if YAML exists, use it first
4. if no YAML exists, fall back to the TXT credential export
5. if neither exists, fail clearly

Preferred current files:

- `create.yaml`
- `upsert.yaml`
- `update.yaml`
- `omada-plan.yaml`
- `live-site.yaml`

Recommended meaning:

- `create.yaml`
  Current desired baseline for first-time site creation
- `upsert.yaml`
  Current desired state for safe create-missing or update-existing runs
- `update.yaml`
  Current desired state for strict in-place changes like password rotation
- `omada-plan.yaml`
  Neutral execution artifact for the last run
- `live-site.yaml`
  Current actual controller state after the last successful Omada run

TXT fallback:

- `Mot de passe <building>.txt`
- or any `.txt` file in that target folder when it is the only TXT export

## Endpoint Model

Current public routes:

- `POST /v1/omada/jobs`
  Raw YAML or JSON Omada plan execution
- `GET /v1/omada/jobs/{jobId}`
  Omada job tracking
- `POST /v1/omada/workdrive/jobs`
  Resolve a WorkDrive folder, use YAML first, TXT second
- `GET /v1/omada/sites/{siteId}/snapshot`
  Export live Omada state as JSON or YAML

## Operation Meaning

`create`

- intended for a brand new site or a brand new batch of objects
- if the folder already contains `create.yaml`, prefer it
- if only TXT exists, generate a `create.yaml` plan from the TXT export
- if the site or SSID already exists, the run fails

`upsert`

- intended for "create missing, update what already exists where safe"
- today this creates missing sites, LANs, WLAN groups, and SSIDs
- today this also updates existing SSIDs in place
- if TXT is the fallback source, generate `upsert.yaml`

`update`

- intended for strict in-place mutation of an existing site
- today this updates existing SSIDs in place
- today this fails if the site, LAN, WLAN group, or SSID is missing
- this preserves AP assignment by updating inside the existing WLAN group instead of deleting and recreating it

Current conservative limits:

- structural LAN mutation is not implemented
- WLAN-group renaming is not implemented
- if an existing LAN conflicts with the desired definition, the run fails instead of silently mutating it

`get`

- export the live controller state into a stable YAML or JSON shape
- use this as a review artifact or as a starting point for later update work
- the public snapshot endpoint does not expose PSKs
- successful create, upsert, and update runs instead refresh `live-site.yaml` with the applied passwords merged in

## Zoho Webhook Strategy

Use explicit fields in Zoho instead of one-off endpoint proliferation.

Recommended Zoho webhook routing rule:

- `domain = omada`
- `operation = create | upsert | update | get`
- `source_preference = yaml_then_txt | yaml_only | txt_only`

That lets one stable endpoint handle many future behaviors:

- `POST /v1/omada/workdrive/jobs`

Example:

```json
{
  "domain": "omada",
  "operation": "upsert",
  "source_preference": "yaml_then_txt",
  "workdrive_folder_id": "replace-with-workdrive-folder-id",
  "site_name": "123 Main Street",
  "building_name": "123 Main Street",
  "omada_region": "Canada",
  "omada_timezone": "America/Toronto",
  "omada_scenario": "Office"
}
```

For workflow-style PDF generation plus site creation or password rotation, continue using:

- `POST /v1/workflows/site-and-password`

Recommended workflow flags:

- `workflow_mode`
- `credential_mode`
- `omada_operation`

That route remains the right choice for multi-step automation.

## Why This Scales

- one Omada entrypoint for artifact-driven site actions
- one workflow entrypoint for multi-step business flows
- explicit operation type instead of hidden inference
- YAML files for human review and re-use
- stable current files for desired state and actual live state
- TXT fallback keeps old jobs usable even when YAML is missing
- live snapshots give you a stable read contract before broader update coverage lands
