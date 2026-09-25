# Opticable Autonomous Core

This is the managed, Cloudflare-native durable runtime for Opticable automation.

It complements the existing FastAPI compatibility service. It is intended to become the primary runtime for critical business workflows so the business does not depend on one long-lived VM.

## Managed primitives

- Cloudflare Worker: HTTP/event edge
- Cloudflare Queues: backpressure and asynchronous ingestion
- Cloudflare Workflows: durable multi-step execution, retries, waits and recovery
- Cloudflare D1: event/run/audit/idempotency state

The existing FastAPI service remains available for legacy integrations and workloads that require a conventional Linux runtime. UI-only browser tasks stay outside the critical runtime and are invoked as explicit provider jobs.

## Security

- Event ingestion requires `Authorization: Bearer <CORE_API_KEY>`.
- The API key is a Worker secret, never a source-controlled variable.
- Events support idempotency keys.
- Durable execution and state are separated from provider credentials.
- Provider mutations will continue to use explicit, audited adapters.

## Bootstrap

Deployment is automated by `.github/workflows/deploy-autonomous-core.yml`.

The GitHub repository must have:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `OPTICABLE_AUTONOMOUS_CORE_API_KEY`

The workflow idempotently provisions D1 and Queues, applies the schema, injects the Worker secret, validates TypeScript and deploys the Worker.

The D1 database is created in Cloudflare's `enam` location hint (Eastern North America) for proximity to Opticable's Quebec operations. This is a performance location hint, not a legal data-residency guarantee.

## Migration policy

1. New critical workflows target this runtime first.
2. Existing FastAPI workflows remain untouched until equivalent behavior is tested.
3. Run shadow/event-only mode before moving each production workflow.
4. Migrate durable state from SQLite to D1/provider-owned systems.
5. Keep legacy worker support for Omada/browser/file-system-specific operations as needed.
