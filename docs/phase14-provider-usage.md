> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](OPTIBRAIN_CODEX_ONBOARDING.md).

# Phase 14 provider usage and performance

Counters record actual transport attempts, methods, final response outcome and retries. They omit URLs, resource IDs, payloads and credentials. Schema-2 observations cover CRM reads/writes, Mail reads/mutations, Forms and Sign separately, Books reads/writes, Cloudflare, GitHub/auth exchange, OAuth refresh, Google and R2. Scopes identify workflows, delta streams, native/drift observers, local timers, operator views and route templates. R2 uploader counts actual SDK sends including retries in private bounded JSONL; exact release GitHub CI read is in the release receipt. Remote-effect SDK reads/claims also use the active job scope. Unsent denied mutations count zero.

Expendable DB history: 30 days/10,000 rows. Root uploader metrics have the same limits, independently of immutable upload audit. Monitoring failure never masks an action outcome. A recovered single GET 401 retains its failed-attempt count but reports successful final observation; revoked/forbidden scope 403, throttles and ambiguous mutations are not blindly retried. Shared credential-bound token lock prevents process refresh races.

## Representative GET-only measurements

Private copied DBs and capture-only intake were used; no live event dispatch, mutation or fabricated operator identity. Public evidence excludes customer content. Timings describe this host/sample, not a 24-hour traffic measurement.

| Path | Before | After | Evidence / limits |
|---|---|---|---|
| Mail observer unchanged replay | 33 Mail GET, 32 content; 8.38 s | 4 metadata GET, 0 content; 1.29 s | Second run: 0 events/duplicates/mutations, 54 cache hits, full 307-row overlap |
| Mail seven-day full audit | Old first page only: 100 rows, 33 GET | 593 rows / 6 pages, 129 content + 6 metadata =135 GET; 35.72 s | Complete first/daily audit; all 129 already committed, 0 duplicate intake |
| Lifecycle + recurring pair | 5 + 5 CRM GET; 2.37 + 2.56 s | 5 + 0 GET; 2.44 s + 4 ms | Same complete five-module projection; scope filtered independently |
| Targeted project detail | 9 CRM GET for all 3 Lab projects; 3.67 s | 6 CRM GET for one registered project; 2.78 s | Requested project only; relationship/ownership readback preserved |
| Sales queue | 6 CRM +3 Mail; 3.35 s | Same provider reads; 3.65 s | Local Lab N+1 eliminated; provider baseline intentionally unchanged |
| Receipt collection | Existing P1: 1 Mail +1 Cloudflare / run | Same steady-state calls | Completed P1 7→1 saving is not claimed again |
| Today | New view; no equivalent before endpoint | Cold: 11 CRM +3 Mail, 6.73 s; warm: 0 calls, 27 ms | Live-only 60 s display reuse; each source freshness retained |
| Readiness | New summary; liveness alone hid failures | 0 provider calls, 43 ms | Five small read-only DB observations + root sample |

## Daily estimates and accounting correction

Reconnaissance estimate: Mail ~1,086 GET/day, including ~792 for 24 hourly observer runs. Fresh unchanged baseline reproduced 33/run. On the same corpus, optimized hourly observer estimate is 135 daily-audit GET +23×4 normal GET =227/day. Adding the unchanged ~294 other Mail reads yields ~521/day, roughly 52% lower. New messages, metadata changes, retries and changing volume add calls; this is a measured-corpus estimate, not an observed full day. Daily seven-day audits intentionally do more complete work than the old truncated 100-row scan.

CRM scheduled reconnaissance estimate ~792/day assumed configured cadences. Repaired Leads delta restores a previously stopped legitimate read stream. Native and desired-drift verification remain independently fresh; their duplicate small metadata checks were retained because mutation reconciliation must not depend on a display cache. Scheduled baseline remains ~792/day under those assumptions; improved complete instrumentation is the authority for actual counts. Shared lifecycle/project savings are operator-driven, not invented fixed daily savings. Root R2 new generation typically needs 8 sends for ciphertext+manifest; replay 4 reads; retries counted. Prior four-call shorthand undercounted the two-object transfer.

OAuth shares one trusted refresh cache across core/root collectors and avoids invalidating another process's newer token. One safe GET retry follows a specific 401; no blind mutation retry/fallback was added. Receipt matching, native channels, off-host claims and action journal remain safety contracts. No generalized provider batching framework or speculative parallel mutation layer was introduced.
