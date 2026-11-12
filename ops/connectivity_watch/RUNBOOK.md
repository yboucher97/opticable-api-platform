# OptiBrain connection watch execution record — 2026-11-12

Scope: Existing draft PR #159, development branch only. No production changes.

## Verified existing paths
- GitHub Actions monitor-production-health.yml checks workflow-api, password-pdf, omada, Cloudflare control-plane, authenticated /v1/system/providers and /v1/system/readiness.
- Issue #98 is open: readiness Native watch and Queue returned ACTION REQUIRED. Causes cannot be assigned without live host and queue evidence.
- The example registry reuses known production GET endpoints; it does **not** replace or duplicate the deployed 15-minute production-health workflow.
- Additional third-party API probes must use real provider-specific authorized identity endpoints and credentials supplied by an approved secrets facility; no arbitrary guessed URLs.
- Existing ChatGPT connector watchdog remains a separate vantage point. Legacy OPX001 is excluded.

## Changes
- Bounded transient-error retries (0–2) with backoff. HTTP 401/403 failures are not automatically retried.
- HTTPS-only remote endpoints, explicit loopback HTTP exception, deny URL-embedded passwords and query credentials.
- Transition-only event list and persisted status fingerprints to avoid repeated alerts.
- Unit tests for retry, authentication rejection and URL validation.
- Example registry grounded in the existing production monitoring workflow.

## Safe execution
python3 -m unittest discover -s ops/connectivity_watch -p 'test_*.py'
python3 ops/connectivity_watch/check.py --config ops/connectivity_watch/endpoints.example.json --state /tmp/optibrain-connection-state.json --output /tmp/optibrain-connection-last.json

The registry's authenticated probes require OPTICABLE_CORE_API_KEY in a restricted environment. Do not commit credentials or check config into production until owner-approved.
Readiness endpoints returning HTTP 200 are only transport checks: actionable readiness content remains interpreted by the existing GitHub workflow.

## Remaining gates
- Establish private VPS diagnostics and inspect actual native-watch/queue metrics, service states, job timestamps, failed task logs, and internal dependencies.
- Run offline tests and isolated dry-run on the VPS using approved service credentials.
- Do not deploy or start a new production timer without approval, and do not alter migration fences, business flags, security controls or financial data.
- Keep exact old production SHA and backup/rollback evidence before any future authorized production change.

## Execution results (2026-11-12)
- Added CI workflow test-connection-watchdog.yml scoped to the draft feature branch; no deployment steps and contents:read permission only.
- GitHub Actions run 43287399096 at commit c1427936876ae19c7c9eb8e2e50fdf09e7cc6a3c: completed success. Python compileall passed; 10 offline watchdog unit tests passed. See https://github.com/yboucher97/opticable-api-platform/actions/runs/43287399096
- Optional provider identity probes documented in providers.example.json: GitHub GET /user and Zoho CRM GET /crm/v2/org. They are not active and require approved read-only credentials. They have not been tested against those providers from the VPS.
- WATCHDOG SOURCE CHANGE: status transition events are emitted via JSON only; no customer mail, no external notifications, no new scheduler. This is intended to integrate with the existing alert route rather than produce a duplicate alert stream.
- Live readiness causes for Native watch / Queue remain unresolved: issue #98 reflects readiness state, not definitive root cause. Investigate service logs and queue internals with authorized VPS access.
- The full application regression suite and on-host tests have NOT run; do not infer production readiness from the 10 offline watchdog tests.
- Draft PR remains unmerged; production and OLD fenced server unchanged.
