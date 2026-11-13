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

The registry's authenticated probes require SITE_WORKFLOW_API_KEY in a restricted environment. Do not commit credentials or check config into production until owner-approved.
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

## Verified correction and existing-monitor reconciliation

The main loop now dispatches `probe_with_retry(item)`. Four CLI-level tests cover the actual HTTP boundary, not only the retry helper:503->200 makes two calls and records success; repeated503 caps at three attempts despite an excessive config;401/403 make one call;zero retries makes one call. The two retry-sensitive CLI tests fail against the original main dispatcher. All14tests pass after correction.

Live NEW audit is complete. Exact monitoring-only candidate b5dcf192e16d034fbe4f508f13b2b17168b17841 was owner-approved and installed separately. The EXISTING resource timer ran both samplers successfully at2026-11-12T21:37:17–19UTC. No API restart, business flag, OAuth scope or queue replay occurred. Current facts supersede the earlier unresolved-audit section:expired/absent CRM watch remains approval-blocked;local queue has17retained failures and no active work;Cloudflare main0/DLQ8. Missing/stale runtime projection was repaired through the existing resource schedule.

Do not install this standalone checker on the VPS. Use the existing resource/operations/capability/credential-refresh/platform timers and their audit records. Provider inventory/permissions and owner notifications already have canonical stores;the example registry is documentation only. No second state directory, token cache, provider gateway, timer or alert stream is authorized by this PR. Existing Google Ads/GA4/Search Console/Cloudflare native collection stays active;Windsor real reporting remains plan-blocked. Public/financial/customer actions stay closed.

Rollback of this development correction is its exact Git commit only. It has no installed production artifact. Monitoring rollout preimages and validation receipts are under `/var/lib/optibrain/monitoring-self-healing-20261112`;the current master is `/var/lib/optibrain/universal-platform-access/MASTER_UNIVERSAL_PLATFORM_RUNBOOK.txt`.


## Production and recovery integration review — 2026-11-13 UTC

Current main remains be8cdfe2b36b562ba9e2a57484d8a3d2e8c92caa. Production NEW is
ec9a8e85095b57faf21212000652912e08093da4, one intake-hold commit ahead of main.
The seven files in this utility are additions with no overlap against the
production-based PR160 recovery changes. They were integrated in an isolated
development branch; all14 CLI tests pass. PR160 includes the same utility and
requires its offline tests in its CI. No scheduled watchdog was installed.

The approved additional current_readiness.py correction was installed separately
as the only production file change, SHA256
dc842c0ba4ee696f24cd65a6f51d47fe91e5d734003497a8d07f8a6bf543c921.
It reports missing R2 restore/readback proof as UNKNOWN; provider/delta source
timestamps remain unchanged. This utility stays offline/manual with transport
status only. Existing operations/credential/resource/platform collectors and
notification ledgers remain canonical.

Review and integration do not authorize merging, application deployment, Native
watch recreation, historical acknowledgements/replay or production self-repair.
PR160 retains the exact-production recovery base; bringing the intake-hold
revision into main requires its own reviewed integration and release approval.
