# Opticable Automation Master Runbook

Last updated: 2026-09-25
Authority: Git history + this runbook + machine-readable production state.
Rule: never store secret values in Git. Record only locations, scopes, IDs that are safe to retain, and recovery procedures.

## Canonical architecture
ChatGPT is the operator interface. optibrain.opticable.ca is the primary control plane. connect.opticable.ca is manual-disabled standby only.
Core execution lives in this repository and on the production VPS. Provider APIs are executors/data sources; business logic stays versioned here.

## Production infrastructure
- VPS host: vps-214ba8cd.vps.ovh.ca
- Public OptiBrain hostname: optibrain.opticable.ca
- IPv4: 148.113.249.7
- OS: Ubuntu 24.04
- Install root: /opt/opticable-api-platform
- Workflow API env: /etc/opticable-workflow-api.env
- GitHub App private key: /etc/optibrain/github-app.pem
- Zoho OAuth store: /var/lib/opticable-api-platform/shared/zoho-oauth.json
- Old VPS must not be modified until replacement is fully proven.

## Production services
- opticable-workflow-api.service
- opticable-password-pdf.service
- opticable-omada-site.service
- Public health: https://optibrain.opticable.ca/v1/system/health
- PDF health: https://optibrain.opticable.ca/pdf/health
- Omada health: https://optibrain.opticable.ca/omada/api/health

## Verified providers
- Zoho: local OAuth, 96 configured / 96 granted scopes, connected.
- Google: local OAuth, 30 scopes, Workspace/Admin + GA4/GTM/Search Console services configured.
- Windsor: connected and live-read verified.
- OVHcloud: signed API connected and live-read verified.
- Cloudflare: token active; opticable.ca zone read verified.
- GitHub: GitHub App auth, App ID 5077440, Installation ID 164914980; live repo read verified.
- Apollo: connected; credit-consuming endpoints disabled by OPTIBRAIN_ALLOW_APOLLO_CREDIT_CONSUMPTION=false.
- OpenAI: live end-to-end generation verified with gpt-5.6-luna.
- Anthropic: live end-to-end generation verified with workspace header support.
- Gemini: intentionally not configured yet.

## Safety gates
No automatic spending increases, purchases, ad-budget increases, payments, refunds, destructive production deletion, domain transfer, or credential rotation without explicit owner approval.
Normal reversible CRUD, monitoring, enrichment, classification, retries, logging, and idempotent reconciliation may be automated within provider limits.

## Deployment
Validation workflow: .github/workflows/validate-api-platform.yml
API deployment workflow: .github/workflows/deploy-api-platform.yml
Durable control plane deployment: .github/workflows/deploy-control-plane.yml

Known issues as of 2026-09-25:
- Deploy API Platform workflow exists but its VPS deployment secrets are missing, causing the "Verify deployment secrets exist" step to fail before SSH configuration.
- Deploy Durable Control Plane validates successfully but its GitHub Actions secret check currently finds all four required values empty: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, OPTICABLE_CONTROL_PLANE_API_KEY, OPTICABLE_CORE_API_KEY.
Do not assume GitHub can deploy either target until the relevant CI secrets are restored.

## Durable control plane
Cloudflare Worker path: apps/control-plane-worker
Responsibilities: authenticated event intake, queue buffering, dead-letter handling, idempotent workflow execution, correlation/causation propagation, delivery to the core automation API.
Queues: opticable-business-events and opticable-business-events-dlq.
Core event target: POST /v1/automation/events.

## Automatic production health monitoring
Workflow: .github/workflows/monitor-production-health.yml
Cadence: every 15 minutes plus manual dispatch.
Checks: workflow API, password PDF service, Omada service.
Failure behavior: open one GitHub incident issue and add subsequent failure observations as comments.
Recovery behavior: comment on and close the incident automatically.
All three endpoints were independently verified HTTP 200 from OPX001 on 2026-09-25.

## Recovery rules
1. Inspect current health before changing anything.
2. Preserve working state before risky changes.
3. Use branch -> validation -> PR -> merge for code changes.
4. Verify service/API health after deployment.
5. On failure, roll back to the last known-good commit instead of layering ad-hoc fixes.
6. Record each material failure, root cause, and successful repair in this runbook or Git history.
7. Never expose API keys, OAuth refresh tokens, private keys, passwords, or full secret files in chat or Git.

## Important resolved failures
- OpenAI 401 invalid_api_key: replaced invalid key; next failure showed billing_not_active; billing was activated; live test then returned OPTIBRAIN_OPENAI_OK.
- Anthropic 400 missing anthropic-workspace-id: added ANTHROPIC_WORKSPACE_ID support, header injection, installer preservation, regression test; live test then succeeded.
- GitHub static token dependence: replaced with GitHub App installation-token authentication while preserving read-only deploy key for checkout.
- Apollo cost risk: provider connected but credit-consuming endpoints remain disabled by default.
- VPS remote automation from OPX001: dedicated public key authorized on VPS, but Windows OpenSSH inside Remote Desktop Commander currently exits 255 even for local config operations; do not interpret this as VPS key rejection.

## Current autonomy priorities
1. Confirm/deploy durable control plane in Cloudflare.
2. Restore secure VPS CI deployment secrets or establish a direct Linux remote-execution connector.
3. Build provider-specific declarative reconcilers and event workflows.
4. Add self-healing checks, token-expiry detection, retry/DLQ monitoring, and drift reconciliation.
5. Add deterministic UI fallback only for functions that have no adequate API.
6. Keep this runbook and config/automation/production-state.yaml current after material changes.
