# Cloudflare Autonomous Runtime

## Decision

The long-term critical automation runtime is moving away from a single manually maintained VM.

The target architecture is:

```
Internet / webhooks / internal publishers
                 |
                 v
      Cloudflare Autonomous Core
        Worker + Queue + Workflow
                 |
      +----------+-----------+
      |                      |
      v                      v
     D1                provider adapters
 durable state         Zoho / Google / Meta
 audit/idempotency     GitHub / Cloudflare
      |
      v
compatibility executors
FastAPI / Omada / browser jobs
```

Cloudflare currently supports durable Workflows with retries and long waits, Queues for asynchronous backpressure, and D1 managed SQL. These are managed services and avoid making the automation brain depend on one long-lived VM.

## Why not simply recreate the old VM?

A VM remains useful for:

- browser automation that needs a full browser/Linux environment
- unusual binaries or native dependencies
- Omada/local-network executors
- temporary compatibility during migration

It is not the source of truth and not the only place where workflow state exists.

## Source of truth

- Git: workflow definitions, desired state, schemas, provider adapters, migrations
- D1: runtime events, run state, idempotency and audits
- provider systems: business records owned by their product
- secrets: platform secret stores only

## Recovery objective

A clean Cloudflare account with the required GitHub secrets should be able to provision the D1 database and queues, apply schema, set the Worker secret and deploy the core from GitHub Actions.

No production database IDs are hard-coded into Git.

## Deployment requirements

Repository Actions secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `OPTICABLE_AUTONOMOUS_CORE_API_KEY`

The first two can use the same Cloudflare account/token permissions already used by the private connector, but GitHub secrets are repository-scoped unless configured at a wider level.

## Rollout

1. deploy core on workers.dev
2. health verification
3. shadow-copy events from existing intake
4. verify D1 event/run/audit state
5. add provider adapters one by one
6. move `api01.opticable.ca` only after compatibility endpoints are covered
7. retain rollback path to legacy runtime until parity is proven
