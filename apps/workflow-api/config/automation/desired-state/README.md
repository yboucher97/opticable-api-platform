> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](../../../../../docs/OPTIBRAIN_CODEX_ONBOARDING.md).

# Desired State

This directory uses the existing `DesiredStateController`; omitted resources are unmanaged, never implicitly deleted.

- `opticable-crm-governance.json`: 93 existing live CRM resources; final live plan 93 noops. Layout topology includes Zoho's default placement of the two additive fields.
- `opticable-lead-additions.json`: exact two optional Lead additions; both applied once and verified as noops. Leave them present/unused for non-destructive rollback.
- `zoho-crm-notification.template.json`: native lead create/edit channel. Destination, private verification token and expiry are environment references. The root campaign supplies them without putting credentials in Git or plan output.

Document format remains `opticable.io/v1alpha1` / `DesiredState`. Each plan binds document version/hash and normalized current state into `plan_hash`. All desired-state API endpoints require the fail-closed inspection key. Apply accepts `{document, plan_hash, reason}` and permits only low-risk additive creates/noops. High/destructive flags are unavailable through that API.

Use `/v1/automation/desired-state/validate`, `/plan`, `/drift`, `/apply`, `/adapters`, `/last-apply` and `/inventory` with the configured inspection key. Apply re-plans and reads immediately before writing; a stale digest is rejected. Secrets and secret-bearing URLs are refused in desired documents. Use validated uppercase environment references for authentication.

Durable intent and verification live in the existing automation audit table. An ambiguous write stays manual across restart, fresh plans and duplicate requests; request IDs do not authorize retries. No reset/force endpoint exists. Unsupported provider APIs and unproven mutation/rollback contracts remain manual. Existing workflow webhooks are distinct from the authenticated native notification mechanism.

Hourly drift checks are opt-in through `OPTIBRAIN_CRM_DRIFT_ENABLED=true`, run on the existing delta worker and never apply changes. Full business semantics, provider limitations and recovery instructions: [architecture](../../../../../docs/OPTIBRAIN_PHASE5_ARCHITECTURE.md) and [engineering record](../../../../../docs/OPTIBRAIN_PHASE5_ENGINEERING_RECORD.md).
