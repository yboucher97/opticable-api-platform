# Opticable Autonomous Automation Platform

## Purpose

This service is the provider-neutral automation brain for Opticable.

The design goal is not to reproduce Zoho Flow. The goal is to make business automation:

- API-first
- event-driven
- version controlled
- idempotent
- auditable
- testable
- rollback-friendly
- provider replaceable
- able to use browser automation only when a product has no adequate API

The existing site/password/PDF/Omada workflow remains supported unchanged while workflows are migrated gradually.

## Responsibility split

### `opticable-api-platform`

Owns:

- business events
- workflow definitions
- workflow runs
- retries
- idempotency
- audit history
- provider adapters
- business rules
- long-running orchestration
- internal service coordination

### `opticable-ai-connector`

Owns:

- ChatGPT-facing MCP surface
- secure user-authorized control entrypoint
- thin API adapters when needed
- human-in-the-loop operations

It should not become the primary business workflow engine.

### GitHub

Git is the desired-state source for:

- workflow definitions
- provider configuration templates
- infrastructure-as-code
- schemas
- tests
- runbooks

## Event model

Every business transition should eventually become an event.

Examples:

- `lead.created`
- `lead.qualified`
- `quote.sent`
- `quote.accepted`
- `appointment.created`
- `job.completed`
- `invoice.created`
- `invoice.overdue`
- `payment.received`
- `review.received`
- `form.submitted`
- `email.received`
- `ad.lead.created`

Each event includes:

- unique event ID
- type
- source
- occurrence time
- correlation ID
- optional causation ID
- optional idempotency key
- recursion depth
- JSON payload

The idempotency key prevents provider webhook retries from creating duplicate business actions.

## Workflow model

Workflow files are YAML desired state under:

`apps/workflow-api/config/automation/workflows/`

Example:

```yaml
id: lead.qualify
name: Qualify new lead
version: 1
enabled: true
trigger:
  event_types: [lead.created]
steps:
  - id: normalize
    action: lead.normalize
  - id: score
    action: lead.score
    retry:
      max_attempts: 3
      backoff_seconds: 2
  - id: crm
    action: zoho.crm.upsert_lead
```

The engine does not hard-code provider behavior. Actions are registered by provider adapters.

## Desired-state control plane

The event engine handles **what happened**. The desired-state controller handles **what should exist**.

Desired-state resources live under:

`apps/workflow-api/config/automation/desired-state/`

The controller provides:

- provider/kind adapter registry
- dependency ordering
- idempotent plan/apply
- explicit drift plans
- high-risk/destructive gates
- provider-independent resource contracts
- audit entries for plan/apply operations

API:

- `GET /v1/automation/desired-state/adapters`
- `POST /v1/automation/desired-state/plan`
- `POST /v1/automation/desired-state/apply`

The intended operating loop is:

```
Git desired state
      ↓
discover actual provider state
      ↓
plan
      ↓
review risk/drift
      ↓
apply
      ↓
verify with a new plan
      ↓
no-op = converged
```

This is how fields, tracking tags, automations, workflows and other configuration can be safely recreated or upgraded later without one-off setup knowledge.

## Centralized Zoho credential plane

`connect.opticable.ca` is the authoritative Zoho OAuth/token gateway.

The automation kernel calls:

`POST https://connect.opticable.ca/internal/v1/zoho/request`

using the server-to-server `OPTICABLE_ZOHO_GATEWAY_API_KEY`.

Benefits:

- one Zoho refresh token
- one scope inventory
- one access-token cache
- no duplicated OAuth drift between ChatGPT and the automation server
- one audit trail for provider mutations
- Creator and future Zoho products can be added without new OAuth stacks

The legacy server-side Zoho OAuth path remains for compatibility with existing WorkDrive/PDF flows until they are safely migrated.

## Durable state

The first implementation uses SQLite in WAL mode.

This is intentional:

- zero additional service dependency on the current single VM
- transactional durability
- easy backup
- excellent fit for the current workload
- repository interface allows a later Postgres migration without changing workflows

Runtime DB default:

`<workflow-output-root>/automation/automation.db`

Future scale path:

SQLite -> managed Postgres

The workflow/event/action contracts remain stable.

## Audit model

The kernel stores:

- events
- workflow definitions
- runs
- every step attempt
- errors
- final context
- audit entries

Provider adapters must never write secrets or access tokens into audit metadata.

Destructive provider actions should use explicit action names and provider-level safeguards rather than a generic arbitrary HTTP action.

## API

Current kernel endpoints:

- `GET /v1/automation/capabilities`
- `GET /v1/automation/actions`
- `GET /v1/automation/workflows`
- `POST /v1/automation/workflows/reload`
- `POST /v1/automation/events`
- `POST /v1/automation/smoke-test`
- `GET /v1/automation/runs`
- `GET /v1/automation/runs/{run_id}`
- `GET /v1/automation/audit`

These endpoints use the existing workflow API key protection.

## Capability grades

The capability registry tracks automation access quality instead of assuming that "OAuth connected" means "full control".

- A: 90-100 — near-full programmable configuration + CRUD + automation path
- B: 75-89 — strong write access with configuration gaps
- C: 60-74 — meaningful writes but major admin/platform gaps
- D: 40-59 — partial API plus browser/UI fallback
- E: 20-39 — mostly read/analytics
- F: 0-19 — not connected or no useful automation path

Source:

`apps/workflow-api/config/automation/capabilities.yaml`

The target is to eliminate F grades for systems that are part of the core operating model.

## Provider strategy

### Zoho CRM

Use the native CRM API/connector for schema and automation configuration:

- fields
- layouts
- modules
- workflows
- functions
- webhooks
- buttons
- records

### Zoho Forms

Use API/webhooks for data and event delivery.

Use deterministic browser automation for builder-only operations such as:

- form creation
- adding/reordering fields
- visual properties
- conditional-rule configuration when no supported API exists

All form submissions should eventually emit `form.submitted` into this platform.

### Zoho Flow

Do not make Zoho Flow the core orchestration engine.

Use Flow only when it is the shortest reliable edge integration for a provider.

Critical logic belongs in this repository so it is:

- reviewable
- testable
- versioned
- observable
- portable

### Zoho Creator

Use Creator API v2.1 for:

- records
- files
- metadata
- bulk operations
- custom APIs

Use browser automation only for builder operations that are not exposed through supported APIs.

### Google Tag Manager

Use the GTM API rather than browser automation whenever possible. The API supports accounts, containers, workspaces, tags, triggers, variables, versions, permissions and publishing.

### Advertising/social platforms

Use existing Windsor.ai write actions where they provide a supported API path.

Do not duplicate a working connector inside the kernel unless autonomous server-side execution requires it.

### Browser fallback

Browser automation is a last-mile adapter, not the primary workflow engine.

Every browser-driven action should eventually have:

- deterministic navigation runbook
- precondition check
- postcondition verification
- screenshots/state evidence
- idempotency guard
- rollback notes

## Next provider adapters

Priority order:

1. Zoho CRM desired-state adapter
2. Zoho Creator desired-state/data adapter through centralized gateway
3. Zoho Forms webhook + deterministic configuration-time browser adapter
4. Zoho Books idempotent finance adapter
5. WorkDrive + Writer + Sign document pipeline
6. Google Tag Manager desired-state adapter
7. GA4 Admin desired-state adapter
8. Cloudflare infrastructure-as-code / desired-state adapter
9. Google/Meta attribution feedback adapters
10. Zoho Desk/Projects operational adapters

Zoho Flow is deliberately **not** on the critical-path list. It may remain for simple edge integrations, but critical logic belongs in this kernel.

## Safety / regression strategy

Existing production workflows stay outside the new action registry until equivalent behavior has:

1. tests
2. dry-run comparison
3. idempotency validation
4. rollback path
5. successful shadow execution

Only then should an old workflow be migrated.

This avoids a "big bang" replacement.
