> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 13 bounded parallel P1 cleanup

This manual mission improves reads, scheduling and expendable state only. Phase13 is NOT closed; Phase14 has NOT begun. MANUAL-01 native Forms containment and MANUAL-02 offline owner AGE decryption remain pending, with the owner checklist unchanged. No real or Test business record mutation is needed. One technical Cloudflare smoke instance proves the safe provider-ID mapping; a malformed test-harness instance was terminated before transport, with no business effect.

## Scheduling ownership

Five systemd application timers remain canonical: daily local backup, daily encrypted off-host upload, five-minute Forms/connector receipt collection, hourly service lifecycle observation, and the half-hourly bounded Test runner. All six development service/timer masks remain in place. No recovered development queue is resumed.

Cloudflare remains the canonical hourly mailbox/every-two-hour daytime Sign/daily Books observer. The three GitHub business cron workflows were already disabled before this mission; this mission removes the remaining Cloudflare daily/weekly disabled digest producers. GitHub's fifteen-minute provider-free HTTP health monitor remains intentional. Forms receipts and general mailbox observation serve separate responsibilities. There is no internal background scheduler or legacy cron for these application jobs.

Receipt and service collectors now share per-job, kernel-released O_NOFOLLOW locks across CLI/systemd entry points. Local backup has a destination-specific flock. Explicit timeouts are 300s for each collector, 45m for local backup, existing46m for encrypted upload and existing180s for the Test runner. Cloudflare delivery still has bounded exponential retries for network/408/429/5xx; permanent4xx fails once without logging raw response bodies. The active hourly Mail/daytime Sign producer used Toronto time-slot IDs containing a colon, outside the provider instance-ID alphabet; recent provider instances contained no successful scheduler Mail/Sign IDs. The queue now deterministically hashes invalid provider instance IDs while preserving business IDs/idempotency and all historically valid instance IDs. No recovered/DLQ queue is drained or resumed. See [Cloudflare instance identity contract](https://developers.cloudflare.com/workflows/build/workers-api/). Control-plane deployment now waits for successful exact-main CI, as core deployment already does.

## Measured provider reads

|Workflow|Before|After|Evidence/limit|
|---|---|---|---|
|Receipt collector, unchanged two-message window|7MailGET/run|1MailGET/run|Actual provider GETs over an isolated copy of the receipt ledger; zero new events|
|Receipt Mail/day estimate|2,016|294|288 searches plus six daily full-audit body/header/detail reads; new receipts add three reads each|
|General CF mailbox observation|24MailGET/day|24MailGET/day|Separate responsibility; total scheduled Mail estimate2,040→318 excluding new receipt/other Mail activity|
|Operations Lab view (three projects)|22CRMGET/request|9CRMGET/request|Exact module-ID batches; identical full projection verified against provider|
|Lifecycle observation|5CRMGET/run,48runs/day=240|5CRMGET/run,24runs/day=120|All five modules checked; initial/daily full reads, changed-since in between|
|Unchanged lifecycle response records|161|0|All five conditional provider reads returned304; display projection retained|
|Scheduled Test runner|≤4 due actions/run,≤2 theoretical writes|Same|Existing indexed due selection/reconciliation preserved; all write controlsOFF|

The first conditional-read proof exposed a timestamp-format requirement: fractional seconds caused Zoho to return full lists. Whole-second UTC validators yielded304 for every module. This is recorded separately; no claim of reduced lifecycle calls/run is made.

## Receipt correctness and cache safety

Durable successful/full-scan checkpoints and message metadata hashes skip known immutable notification bodies. Every day the seven-day window is reauthenticated/revalidated in full. Two-day overlap catches delayed delivery; outages extend the checkpoint window up to30days. Longer gaps fail explicitly for backfill instead of silently advancing. Failed collection never advances a successful checkpoint; a partial retry is idempotent. An authenticated unsupported notification may be cached; malformed or unauthenticated notifications may not.

Existing provider Test receipts replayed with zero new events and one MailGET. A fixture using the production collector discovered exactly one new synthetic receipt once, with no provider mutation. Daily revalidation, changed metadata, retention and failed checkpoints are covered by focused tests.

Operations batches are request-local, exact registered IDs only, at most100IDs/chunk, and reject missing/duplicate/unexpected results. No cache survives the operator request. Scheduled lifecycle snapshots are DISPLAY CACHE ONLY: all five modules are checked, all cursors commit after successful projection/event reconciliation, daily full reads detect deletions, and the bounded inventory fails when pagination exceeds200/module. Operator APIs and mutation preconditions retain fresh provider reads. These snapshots cannot execute non-GET requests or authorize writes.

## State, retention and observability

Five active SQLite stores remain because intake events, receipt evidence, lifecycle occurrences, business actions and the original workflow store have distinct recovery responsibilities. Three historical/staging copies remain recovery evidence. Online integrity checks passed for all. No DB was merged or VACUUMed under a production lock; existing WAL/DELETE modes are preserved. New receipt timestamp/canonical lookup indexes and metadata/time indexes improve bounded access.

Provider transport accounting records per-job CRM reads/writes, Mail reads/mutations, other Zoho, Cloudflare, GitHub and OAuth refreshes. Receipt/lifecycle/Test soft budgets are12/6/16calls/run. Logs and the existing job DB record run/hour/day estimates; overruns warn, and metric failures never hide execution failures. No URL, token, payload or business ID is recorded. Pretransport denials count zero calls. Core workflow execution also records counters in its existing DB.

Only expendable metrics (30days/10,000rows), message metadata (30days) and bounded five-module display snapshots are pruned/overwritten. Receipts, business journals, reconciliation evidence, registries, protected baselines and backup generations remain intact. Diagnostic journald bounds are512MB persistent/128MB runtime,2GB free and90days; protected business evidence is held separately. Existing encrypted-cache/generation retention needs a future evidence-aware preservation policy; the owner-proof generation is not deleted. Temporary proof DB copies stay private audit evidence.

OAuth already had a secure shared token cache and interprocess refresh lock. This mission preserves it, proves two independent concurrent managers refresh only once, accounts refreshes and removes raw token-error response logging. No credential was rotated or copied.

## Retirement and recovery

No active unit, cron entry or process referenced the retired `/opt/optibrain-agent` runtime. It is archived at `/var/lib/optibrain/phase13-p1/retired-development.tar.gz` and quarantined at `/var/lib/optibrain-retired-development/optibrain-agent`. Both are root-private. The immutable archive is included in `/var/lib/optibrain` backup coverage; the raw quarantined runtime stays outside active restore state so its historical symlinks are never restored. Keep six unit masks and absent development authorization; do not restore this runtime to an executable path. Existing branches/worktrees and recovery tags remain retained; historic canary/autonomy branches must not be deployed.

Backups now include the journald policy; new caches/metrics live in already-backed-up DBs. Rollback is exact-SHA with the previous validated release and private backup. Preserve the unchanged owner checklist and the owner-required generation20261001T202728Z even when a newer backup succeeds.

## Validation and remaining work

Provider-backed evidence is in [provider proof](phase13-p1-evidence/provider-proof.json) and [conditional proof](phase13-p1-evidence/conditional-proof.json); private runtime/test/release evidence is `/home/optibrain/phase13-p1-evidence` and root `/var/lib/optibrain/phase13-p1`. The deployed receipt and final validation identify the exact merge SHA/CI run.

Formal Phase14 retains ledger/source-of-truth consolidation, advanced provider change feeds/deletion detection, operator navigation/cross-route caching, unified failure alerts, evidence-aware backup-cache retention, older worktree cleanup and larger privilege/release-helper simplification. These are DEFER—NON-CRITICAL for this bounded mission. No change to real write authority, owner P0 requirements, authentication, kill semantics or provider containment is authorized by a read optimization.
