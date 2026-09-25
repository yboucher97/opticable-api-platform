# Opticable Durable Control Plane

This Worker is the durable edge orchestration layer for Opticable.

## Responsibilities

- authenticated event ingestion
- queue buffering
- dead-letter handling after retries
- one durable Cloudflare Workflow instance per business event
- idempotency by event_id
- correlation / causation propagation
- durable delivery into the existing Opticable automation kernel

It intentionally does **not** replace provider adapters or desired-state logic. Those remain in `apps/workflow-api` during migration.

## Event endpoint

`POST /v1/events`

Authorization:

`Authorization: Bearer <CONTROL_PLANE_API_KEY>`

Example event:

```json
{
  "event_type": "lead.created",
  "source": "zoho.forms",
  "payload": {
    "lead_id": "example"
  }
}
```

The Worker assigns missing:

- event_id
- occurred_at
- correlation_id
- idempotency_key

The event is queued, then the queue consumer starts a Workflow instance whose ID equals the event_id. Duplicate delivery therefore converges on the same workflow identity.

## Durable execution

Cloudflare Workflow steps deliver to:

`POST https://api01.opticable.ca/v1/automation/events`

The delivery step has exponential retry and the queue consumer has a dead-letter queue.

## Required GitHub Actions secrets

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `OPTICABLE_CONTROL_PLANE_API_KEY`
- `OPTICABLE_CORE_API_KEY`

The Cloudflare token must be allowed to deploy Workers/Workflows and manage Queues.

## Design rules

- API-first
- event-driven
- idempotent
- durable
- no secrets in Git
- provider-neutral event contracts
- browser automation only for UI-only provider configuration
- destructive provider changes remain gated by the desired-state controller


## Production verification

This component is production-targeted through `.github/workflows/deploy-control-plane.yml`.
A documentation-only change may be used to exercise the existing deployment workflow without changing runtime behavior.
Production is considered verified only after the GitHub Actions deployment succeeds and the Worker endpoint is subsequently health-checked.
